"""Auto-generate short session titles from the user's opening message.

Two stages, both off the critical path: an **instant** deterministic title (written before the model
is called, cannot fail), then an **upgrade** from one small-model call (cheap tier, thinking off,
JSON-constrained). Storage enforces provenance ``derived < llm < user``: stage 2 only replaces stage 1
and neither replaces a name the user typed."""

import json
import logging
import re
import threading
from contextlib import suppress
from typing import Any, Callable, Optional

from agent.auxiliary_client import call_llm
from agent.context_compressor import LEGACY_SUMMARY_PREFIX
from agent.message_content import flatten_message_text

logger = logging.getLogger(__name__)

# (task_name, exception) -> None; surfaces auxiliary failures so silent drops don't pile up as NULL titles.
FailureCallback = Callable[[str, BaseException], None]
# (title, source) -> None; source is the persisted provenance (``derived`` / ``llm``). Consumers paying a
# rate-limited remote rename per title (Discord thread, Telegram topic) should act on ``llm`` only.
TitleCallback = Callable[[str, str], None]
# () -> bool, called right before the LLM request; False skips (e.g. the user switched models and
# the request would reload one the runtime already evicted).
# Validation callback: () -> bool. See #19027.
RuntimeValidator = Callable[[], bool]

# Text budget handed to the model (Claude Code / OpenClaw converged on 1000).
MAX_TITLE_INPUT_CHARS = 1000
# Cap on the instant derived title; a raw fragment reads worse the longer it runs.
MAX_DERIVED_TITLE_CHARS = 48
# Answer-shaped guard: a tiny model sometimes answers instead of titling; longer is rejected, not truncated.
# Upper bound on accepted title word count. Titling is a 3-7 word task; a small tiny-model sometimes ignores
# the task and answers the user's message instead — that answer must never become the session title (see the
# answer-shaped output guard in generate_title; port of can1357/oh-my-pi#7306). 12 leaves headroom for
# legitimate wordy titles while excluding full-sentence answers.
_MAX_TITLE_WORDS = 12

_TITLE_PROMPT_TEMPLATE = (
    "You name chat sessions. Given the user's opening message, write a title "
    "that lets them find this conversation again in a list.\n\n"
    "Rules:\n"
    "- 3 to 7 words, sentence case (capitalize only the first word and proper nouns).\n"
    "- Name what the user wants DONE, not that they asked a question.\n"
    "- Keep technical terms, filenames, numbers, and error codes exact.\n"
    "- Drop filler words: the, this, my, a, an.\n"
    "- No trailing punctuation, no quotes, no tool names, no 'Title:' prefix.\n"
    "- Never answer the message. Name it.\n"
    "- Always produce something, even for a bare greeting.\n"
    "__LANGUAGE_RULE__\n"
    'Good: {"title": "Fix login button on mobile"}\n'
    'Good: {"title": "Postgres connection pool exhaustion"}\n'
    'Good: {"title": "Friendly greeting"}\n'
    'Too vague: {"title": "Code changes"}\n'
    'Too long: {"title": "Investigate and fix the issue where the login button '
    'does not respond on mobile devices"}\n\n'
    'Reply with JSON only: {"title": "..."}'
)

_LANGUAGE_RULE_MATCH_USER = "- Write the title in the same language as the user's message."
_LANGUAGE_RULE_PINNED = "- Write the title in {language}."

# Constrains the response to a single title field ("model answered instead of titling" failure class).
_TITLE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "session_title", "strict": True, "schema": {
        "type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"], "additionalProperties": False}},
}

# Control-tag wrappers around machine-authored content inside a nominal "user" message (Codex CLI's
# RECOGNIZED_CONTROL_WRAPPERS): stripped, titling continues on what remains.
_CONTROL_WRAPPERS = tuple(
    (f"<{tag}>", f"</{tag}>")
    for tag in ("command-message", "command-name", "command-args", "local-command-caveat", "local-command-stderr",
                "local-command-stdout", "task-notification", "system-reminder", "ide_opened_file", "ide_selection")
)

# Hermes' own machine-authored openers: a compaction handoff or resumed session must not be titled after them.
_MACHINE_PREFIXES = (
    "[CONTEXT COMPACTION", LEGACY_SUMMARY_PREFIX, "[Runtime note:", "[System note:", "[SYSTEM]",
    # tui_gateway.server._MODEL_SWITCH_MARKER_PREFIX (keep in sync); persisted as role="user" because
    # strict providers reject a non-first system message.
    # Model-switch marker from tui_gateway.server._append_model_switch_marker. It is persisted with
    # role="user" (strict OpenAI-compatible providers reject a system message that is not first — #48338),
    # so without this entry it looks like a real opening turn: switching models before the first real
    # message titled the session "[System: The active model for this chat has…" instead of the user's actual
    # question.
    "[System: The active model for this chat has changed to ",
)

# Re-title prompt. Unlike the first-exchange prompts above, this one is shown
# the WHOLE conversation plus the current title, and is biased to KEEP the
# existing title unless the durable topic has clearly drifted. This is what
# stops a localized detour (e.g. "write the PDF" inside a long USCIS-RFE
# conversation) from clobbering a title that describes the real subject.
_RETITLE_PROMPT = (
    "You are maintaining the title of an ongoing conversation. Below is the conversation "
    "so far (it may be condensed to its opening and most recent turns) and its CURRENT title.\n\n"
    "Assess whether the current title still captures the conversation's main topic and intent "
    "considered as a WHOLE — not just the most recent message.\n\n"
    "Rules:\n"
    "- If the current title is still accurate, return it UNCHANGED, verbatim.\n"
    "- Strongly prefer keeping or only lightly adjusting the current title. Most of the time it "
    "does not need to change.\n"
    "- Only write a substantially different title if the conversation's main subject has clearly "
    "and durably moved away from what the current title describes.\n"
    "- Do NOT retitle based on the latest message alone; a brief detour or sub-task is not a "
    "topic change.\n"
    "- Keep it short (3-7 words). Write the title in the same language the user is writing in.\n"
    "Return ONLY the title text, nothing else. No quotes, no punctuation at the end, no prefixes."
)

_RETITLE_PROMPT_PINNED_LANGUAGE = (
    "You are maintaining the title of an ongoing conversation. Below is the conversation "
    "so far (it may be condensed to its opening and most recent turns) and its CURRENT title.\n\n"
    "Assess whether the current title still captures the conversation's main topic and intent "
    "considered as a WHOLE — not just the most recent message.\n\n"
    "Rules:\n"
    "- If the current title is still accurate, return it UNCHANGED, verbatim.\n"
    "- Strongly prefer keeping or only lightly adjusting the current title. Most of the time it "
    "does not need to change.\n"
    "- Only write a substantially different title if the conversation's main subject has clearly "
    "and durably moved away from what the current title describes.\n"
    "- Do NOT retitle based on the latest message alone; a brief detour or sub-task is not a "
    "topic change.\n"
    "- Keep it short (3-7 words). Write the title in {language}.\n"
    "Return ONLY the title text, nothing else. No quotes, no punctuation at the end, no prefixes."
)


def _title_config() -> dict:
    """``auxiliary.title_generation`` (lazy read-only import: no hermes_cli cycle, no migration writes)."""
    from hermes_cli.config import load_config_readonly
    return ((load_config_readonly() or {}).get("auxiliary") or {}).get("title_generation") or {}


def _title_language() -> str:
    """Configured title language, or "" to match the user."""
    try:
        return str(_title_config().get("language", "")).strip()
    except Exception:
        return ""


def _auto_title_enabled() -> bool:
    try:
        from utils import is_truthy_value
        return is_truthy_value(_title_config().get("enabled"), default=True)
    except Exception:
        logger.debug("Failed to read title_generation.enabled", exc_info=True)
        return True


def strip_control_wrappers(text: str) -> str:
    """Remove leading control wrappers (nested too) so a slash-command turn reduces to the prose the user typed."""
    current = (text or "").strip()
    for _ in range(len(_CONTROL_WRAPPERS) * 2):  # bounded: each pass must remove a wrapper or we stop
        stripped = _strip_one_wrapper(current)
        if stripped == current:
            break
        current = stripped
    return current


def _strip_one_wrapper(text: str) -> str:
    lowered = text.lower()
    for open_tag, close_tag in _CONTROL_WRAPPERS:
        if not lowered.startswith(open_tag):
            continue
        end = lowered.find(close_tag)
        if end == -1:  # unterminated wrapper: drop the opening tag and keep the body
            return text[len(open_tag):].strip()
        # Prefer trailing prose; otherwise the wrapper body is all we have.
        return (text[end + len(close_tag):].strip() or text[len(open_tag):end].strip()).strip()
    return text


def _summarize_user_message(user_message: str) -> str:
    """Text worth titling: describe a ``/skill`` invocation (it embeds the whole skill body), then strip wrappers."""
    if not user_message:
        return ""
    described = None
    try:
        from agent.skill_commands import describe_skill_invocation
        described = describe_skill_invocation(user_message)
    except Exception:
        logger.debug("Skill-scaffolding summary failed; titling raw", exc_info=True)
    return strip_control_wrappers(user_message if described is None else described)


def is_titleable_user_message(user_message: str) -> bool:
    """False for machine-authored openers and turns that reduce to nothing once scaffolding is stripped."""
    return (isinstance(user_message, str) and bool(user_message.strip()) and not user_message.lstrip().startswith(_MACHINE_PREFIXES)
            and bool(_summarize_user_message(user_message).strip()))


def derive_title(user_message: str) -> Optional[str]:
    """Instant title: first meaningful line trimmed to a word boundary. No model, never fails."""
    line = " ".join(_first_line(_summarize_user_message(user_message)).split())
    if len(line) > MAX_DERIVED_TITLE_CHARS:
        cut = line[:MAX_DERIVED_TITLE_CHARS]
        space = cut.rfind(" ")
        line = (cut[:space] if space > MAX_DERIVED_TITLE_CHARS // 2 else cut).rstrip(" ,.;:—-") + "…"
    return line or None


def _strip_title_prefix(text: str) -> str:
    return text[6:].strip() if text.lower().startswith("title:") else text


def _first_line(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")


def _extract_title_text(content: str) -> str:
    """Strict JSON, then a loose JSON scan, then first-line prose (a provider ignoring ``response_format`` still titles)."""
    if not content:
        return ""
    raw = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and isinstance(parsed.get("title"), str):
            return parsed["title"].strip()
    except (ValueError, TypeError):
        pass
    match = re.search(r'"title\"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    if match:
        with suppress(ValueError):
            return json.loads(f'"{match.group(1)}"').strip()
        return match.group(1).strip()
    # Prose fallback: scrub <think> blocks so reasoning can't leak into a title.
    try:
        from agent.agent_runtime_helpers import strip_think_blocks
        raw = strip_think_blocks(None, raw).strip()
    except Exception:
        logger.debug("strip_think_blocks unavailable for title output", exc_info=True)
    return _strip_title_prefix(_first_line(raw)).strip("\"'").strip()


def _clean_title(text: str) -> Optional[str]:
    """Normalize a model-produced title, or None when nothing usable remains."""
    title = _strip_title_prefix(" ".join((text or "").split()).strip("\"'").strip()).rstrip(".!,;:")
    if len(title) > 80:
        title = title[:77].rstrip() + "..."
    return title or None


def _safe_callback(callback: Optional[Callable], args: tuple, log_fmt: str, label: str) -> None:
    """Invoke an optional consumer callback, never raising."""
    try:
        if callback is not None:
            callback(*args)
    except Exception:
        logger.debug(log_fmt, label, exc_info=True)


def _report_failure(failure_callback: Optional[FailureCallback], exc: BaseException, label: str) -> None:
    _safe_callback(failure_callback, ("title generation", exc), "%s failure_callback raised", label)


def _notify_title(title_callback: Optional[TitleCallback], title: str, source: str, label: str) -> None:
    _safe_callback(title_callback, (title, source), "%s callback failed", label)


def generate_title(
    user_message: str,
    timeout: Optional[float] = None,
    failure_callback: Optional[FailureCallback] = None,
    main_runtime: dict = None,
    runtime_validator: Optional[RuntimeValidator] = None,
) -> Optional[str]:
    """Title from the opening message alone (waiting for the assistant made this slow and bought
    nothing). ``runtime_validator`` runs right before the request; False skips silently.

    If it returns False (e.g. the user's model was switched since the background thread captured its runtime
    snapshot), the call is skipped silently — no request is sent, so a stale title request can't reload a
    model the runtime already unloaded (#19027).
    """
    if not _auto_title_enabled():
        logger.debug("Auto-title skipped: auxiliary.title_generation.enabled=false")
        return None
    try:
        if runtime_validator is not None and not runtime_validator():
            logger.debug("Title generation skipped: runtime validator returned False")
            return None
    except Exception:  # fail open: a broken validator must not disable titling
        logger.debug("Title runtime validator raised; proceeding", exc_info=True)
    user_snippet = _summarize_user_message(user_message)[:MAX_TITLE_INPUT_CHARS]
    if not user_snippet.strip():
        return None
    language = _title_language()
    # str.replace, not str.format: the prompt embeds literal JSON braces.
    prompt = _TITLE_PROMPT_TEMPLATE.replace(
        "__LANGUAGE_RULE__", _LANGUAGE_RULE_PINNED.format(language=language) if language else _LANGUAGE_RULE_MATCH_USER,
    )
    try:
        response = call_llm(
            task="title_generation",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user_snippet}],
            # A title is a handful of tokens; a larger ceiling let chatty models burn seconds.
            max_tokens=64, temperature=0.3, timeout=timeout, main_runtime=main_runtime,
            extra_body={"response_format": _TITLE_RESPONSE_FORMAT},
            # The module contract above promises thinking-disabled operation,
            # but nothing enforced it: with the aux default reasoning_effort
            # "" (provider default), Gemini enables internal thinking and
            # bills thought tokens against max_tokens=64 — the JSON payload
            # never lands, and the prose fallback stores the opening fence
            # ("```json") as the session title (#91927).
            reasoning_config={"enabled": False},
        )
        title = _clean_title(_extract_title_text(response.choices[0].message.content or ""))
        # Answer-shaped output guard: titling is a 3-7 word task, so a title with many words is a model that
        # ignored the task and answered the user's message instead ("I don't have context on X — that's not
        # something I recognize..."). Truncating would store half an assistant blob as the session title,
        # which is still an assistant blob — reject instead so the caller retries on the next exchange
        # (maybe_auto_title fires for the first two exchanges). Port of can1357/oh-my-pi#7306.
        if title is not None and len(title.split()) > _MAX_TITLE_WORDS:
            # Answer-shaped output: reject (not truncate) so the caller retries next exchange.
            logger.debug("Rejecting answer-shaped title output (%d words > %d)", len(title.split()), _MAX_TITLE_WORDS)
            return None
        return title
    except Exception as e:
        # WARNING so it shows in agent.log without debug mode; stack at debug.
        logger.warning("Title generation failed: %s", e)
        logger.debug("Title generation traceback", exc_info=True)
        _report_failure(failure_callback, e, "Title generation")
        return None


def _has_upgraded_title(session_db, session_id: str) -> bool:
    """True when the session already carries an ``llm``/``user`` title (or the check fails)."""
    try:
        source_fn = getattr(session_db, "get_session_title_source", None)
        if source_fn is not None:
            return source_fn(session_id) not in (None, "derived")
        return bool(session_db.get_session_title(session_id))
    except Exception:
        return True


def _persist_session_title(session_db, session_id, title, *, source, dedupe=True):
    """Persist at *source* authority via ``set_auto_title`` (precedence check + write in one
    transaction, so a manual ``/title`` is never overwritten); None when a higher authority held the row.
    ``ValueError`` = unique-title index collision → append ``#N`` via ``get_next_title_in_lineage``;
    ``dedupe=False`` re-raises instead (the derived title is on the critical path, collides constantly
    on "hi", and the model replaces it a second later anyway).

    ``ValueError`` means the name is taken by an unrelated session (the unique-title index); rather than
    leave the session untitled (#50537), append a ``#N`` suffix via ``get_next_title_in_lineage``.
    """
    auto_fn = getattr(session_db, "set_auto_title", None)

    def _set(candidate):
        if auto_fn is not None:
            if auto_fn(session_id, candidate, source=source):
                return candidate
            logger.debug("Skipping %s title: a higher-authority title already holds session %s", source, session_id)
            return None
        legacy_fn = getattr(session_db, "set_auto_title_if_empty", None)  # older store without provenance
        if legacy_fn is not None:
            return candidate if legacy_fn(session_id, candidate) else None
        if session_db.set_session_title(session_id, candidate) is False:
            raise RuntimeError(f"session {session_id} not found when storing title")
        return candidate

    try:
        return _set(title)
    except ValueError:
        next_title_fn = getattr(session_db, "get_next_title_in_lineage", None)
        deduped = next_title_fn(title) if dedupe and next_title_fn is not None else None
        if not deduped or deduped == title:
            raise
        return _set(deduped)


def apply_instant_title(session_db, session_id: str, user_message: str, title_callback: Optional[TitleCallback] = None) -> Optional[str]:
    """Write the derived title inline. Returns it, or None (no usable text, or a ``derived``+ title exists). Never raises."""
    if not session_db or not session_id:
        return None
    try:
        title = derive_title(user_message) if is_titleable_user_message(user_message) else None
        persisted = _persist_session_title(session_db, session_id, title, source="derived", dedupe=False) if title else None
        if persisted:
            _notify_title(title_callback, persisted, "derived", "Instant-title")
        return persisted
    except Exception:
        logger.debug("Instant title failed", exc_info=True)
        return None


def _condense_history(
    conversation_history: list,
    head_turns: int = 1,
    tail_turns: int = 3,
    per_message: int = 400,
) -> str:
    """Render a conversation into a compact transcript for whole-conversation
    title assessment.

    Keeps the OPENING ``head_turns`` user/assistant exchanges (they anchor the
    conversation's original intent — the thing a good title names) and the most
    recent ``tail_turns`` exchanges (they reveal genuine topic drift). Anything
    in between is elided with a ``[…]`` marker so the request stays cheap on a
    long conversation instead of dumping the entire transcript into the
    auxiliary model.

    Only ``user`` and ``assistant`` roles are included; system/tool messages
    are skipped. Each message is truncated to ``per_message`` chars.
    """
    msgs = [
        m for m in (conversation_history or [])
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    if not msgs:
        return ""

    # A "turn" here is a single message; head/tail are counted in messages so
    # the head captures the opening user+assistant pair at head_turns=1 -> 2.
    head_n = max(0, head_turns) * 2
    tail_n = max(0, tail_turns) * 2

    if len(msgs) <= head_n + tail_n:
        selected = list(msgs)
        elided_at = -1
    else:
        head = msgs[:head_n]
        tail = msgs[len(msgs) - tail_n:] if tail_n else []
        selected = head + tail
        elided_at = len(head)

    lines = []
    for i, m in enumerate(selected):
        if i == elided_at:
            lines.append("[… earlier turns omitted …]")
        role = "User" if m.get("role") == "user" else "Assistant"
        content = (m.get("content") or "").strip()
        if len(content) > per_message:
            content = content[:per_message] + "…"
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _looks_like_title(text: str) -> bool:
    """Return True if ``text`` is shaped like a real title, not prose.

    The retitle model is asked "should the title change?" and sometimes answers
    CONVERSATIONALLY ("The title remains accurate. The conversation is still
    about …") instead of returning a title. Without this guard that sentence is
    sanitized, truncated at 80 chars, and stored AS the title — then pushed to
    the Discord thread name. A genuine 3-7 word title never trips these signals;
    prose reliably does. Multi-signal reject (approved threshold):

    - >10 words         → prose, not a 3-7 word title
    - >80 chars         → longer than any legitimate short title
    - mid-sentence '. ' → a period followed by more words is a sentence, not a title
    - internal newline  → multi-line output is never a title
    """
    if not text:
        return False
    if len(text) > 80:
        return False
    if "\n" in text:
        return False
    if len(text.split()) > 10:
        return False
    # A sentence break — a lowercase word ending in '.' followed by a space and
    # more text — means prose ("… accurate. The conversation …"). Requiring a
    # LOWERCASE letter before the dot avoids false-flagging abbreviations whose
    # dotted component is uppercase or single-letter ("U.S. Visa Renewal",
    # "e.g. Docker", "Q3 Review"). A trailing period is stripped elsewhere.
    if re.search(r"[a-z]\.\s+\S", text):
        return False
    return True


def regenerate_title(
    conversation_history: list,
    current_title: str,
    timeout: float = 30.0,
    failure_callback: Optional[FailureCallback] = None,
    main_runtime: dict = None,
) -> Optional[str]:
    """Re-assess an existing session title against the WHOLE conversation.

    Unlike :func:`generate_title` (which only sees the first exchange), this
    reads a condensed view of the entire conversation plus the current title,
    and is prompted to KEEP the existing title unless the durable topic has
    clearly drifted. Returns the (possibly unchanged) title, or ``None`` on
    failure / empty transcript.
    """
    transcript = _condense_history(conversation_history)
    if not transcript:
        return None

    language = _title_language()
    prompt = (
        _RETITLE_PROMPT_PINNED_LANGUAGE.format(language=language)
        if language else _RETITLE_PROMPT
    )

    user_block = (
        f"CURRENT TITLE: {current_title or '(none)'}\n\n"
        f"CONVERSATION:\n{transcript}"
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_block},
    ]

    try:
        response = call_llm(
            task="title_generation",
            messages=messages,
            max_tokens=500,
            temperature=0.3,
            timeout=timeout,
            main_runtime=main_runtime,
        )
        title = (response.choices[0].message.content or "").strip()
        title = title.strip('"\'')
        if title.lower().startswith("title:"):
            title = title[6:].strip()
        # Reject conversational / prose output instead of truncating it into a
        # title. When the model answers "should this change?" in prose rather
        # than returning a title, treat it as "no usable new title" → None,
        # which the caller reads as "keep the current title, don't rename".
        # (Do NOT fall back to title[:77]+"..." here — that is exactly how a
        # 100-char sentence became a Discord thread name.)
        if not _looks_like_title(title):
            logger.debug("Retitle: rejected non-title output: %r", title[:120])
            return None
        return title if title else None
    except Exception as e:
        logger.warning("Title regeneration failed: %s", e)
        logger.debug("Title regeneration traceback", exc_info=True)
        if failure_callback is not None:
            try:
                failure_callback("title regeneration", e)
            except Exception:
                logger.debug("Title regeneration failure_callback raised", exc_info=True)
        return None


def auto_title_session(
    session_db,
    session_id: str,
    user_message: str,
    failure_callback: Optional[FailureCallback] = None,
    main_runtime: dict = None,
    title_callback: Optional[TitleCallback] = None,
    runtime_validator: Optional[RuntimeValidator] = None,
) -> None:
    """Generate and store the model title (daemon-thread target); skips sessions already carrying an
    ``llm``/``user`` title (a ``derived`` one is expected — upgrading it is the point). Never lets an
    exception escape (the threading excepthook would spray a traceback into the terminal); the canonical
    trigger is the post-``hermes update`` window where lazy imports read NEW source against OLD modules."""
    try:
        if not session_db or not session_id or _has_upgraded_title(session_db, session_id):
            return
        # This thread starts AFTER the turn's ambient context was reset; republish it so the call carries
        # the same Portal ``conversation=`` tag (root-of-lineage) and bills usage to this session.
        from agent.aux_accounting import set_accounting_context
        from agent.portal_tags import set_conversation_context
        conversation_id = session_id
        with suppress(Exception):
            conversation_id = session_db.get_conversation_root(session_id) or session_id
        set_conversation_context(conversation_id)
        # Same for the accounting context, so the title call's token usage is recorded against this session
        # (task='title_generation', #23270).
        set_accounting_context(session_db, session_id)
        title, source = generate_title(
            user_message, failure_callback=failure_callback, main_runtime=main_runtime, runtime_validator=runtime_validator,
        ), "llm"
        if not title:  # the inline attempt declined collisions; off the critical path the lineage scan is affordable
            title, source = derive_title(user_message), "derived"
        if not title:
            return
        try:
            persisted = _persist_session_title(session_db, session_id, title, source=source)
        except Exception as e:
            logger.debug("Failed to set auto-generated title: %s", e)
            return
        if persisted is not None:
            logger.debug("Auto-generated session title: %s", persisted)
            _notify_title(title_callback, persisted, source, "Auto-title")
    except Exception as e:
        # WARNING so operators see it in agent.log; names the likely cause.
        logger.warning("Auto-title failed (harmless; if this started after an update, restart the running Hermes process): %s", e)
        logger.debug("Auto-title traceback", exc_info=True)
        _report_failure(failure_callback, e, "Auto-title")


def _is_real_user_turn(message: Any) -> bool:
    """A question a person actually asked (Hermes persists machinery under ``role="user"``)."""
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    content = message.get("content")
    return is_titleable_user_message(content if isinstance(content, str) else flatten_message_text(content))


def _session_is_untitled(session_db, session_id: str) -> bool:
    """No title of any provenance; False when it can't tell (no model call per turn for an unreadable title)."""
    getter = getattr(session_db, "get_session_title", None)
    try:
        return callable(getter) and not str(getter(session_id) or "").strip()
    except Exception:
        logger.debug("Untitled check failed for %s", session_id, exc_info=True)
        return False


def maybe_retitle_session(
    session_db,
    session_id: str,
    user_message: str,
    assistant_response: str,
    conversation_history: list,
    failure_callback: Optional[FailureCallback] = None,
    main_runtime: dict = None,
    title_callback: Optional[TitleCallback] = None,
    every_n_turns: int = 6,
) -> None:
    """Periodically re-evaluate a session's title to keep it relevant as the
    conversation evolves. Fires every ``every_n_turns`` user turns AFTER the
    initial auto-title (so first-turn handling stays exclusively with
    :func:`maybe_auto_title`).

    Cheap path:
    - Only runs every Nth turn.
    - Only acts once conversation_history has at least 3 user messages.
    - Assesses the WHOLE conversation (condensed) against the current title via
      :func:`regenerate_title`, which is biased to keep the existing title
      unless the durable topic has clearly drifted. Only saves + fires the
      callback (which drives the thread rename) when the title actually changes.
    """
    if not session_db or not session_id or not user_message or not assistant_response:
        return
    user_msg_count = sum(1 for m in (conversation_history or []) if m.get("role") == "user")
    # First-turn is handled by maybe_auto_title; only act on 3rd+ user turns.
    if user_msg_count < 3:
        return
    if every_n_turns <= 0 or (user_msg_count % every_n_turns) != 0:
        return

    # Snapshot history now — the background thread must assess the conversation
    # as it stands at this turn, not whatever it has mutated into later.
    history_snapshot = list(conversation_history or [])

    def _runner():
        try:
            existing = session_db.get_session_title(session_id) or ""
        except Exception:
            return
        new_title = regenerate_title(
            history_snapshot, existing,
            failure_callback=failure_callback, main_runtime=main_runtime,
        )
        if not new_title:
            return
        new_title = new_title.strip()
        # regenerate_title is prompted to return the current title verbatim when
        # nothing has drifted; treat an unchanged title as a no-op so we don't
        # churn the DB or spuriously rename the thread. Compare case- and
        # trailing-punctuation-insensitively so "USCIS RFE Response." doesn't
        # count as a change from "USCIS RFE Response".
        def _norm(t: str) -> str:
            return t.strip().rstrip(".!?,;: ").lower()
        if not new_title or _norm(new_title) == _norm(existing):
            return
        try:
            session_db.set_session_title(session_id, new_title)
        except Exception:
            return
        if title_callback is not None:
            try:
                title_callback(new_title)
            except Exception:
                logger.debug("Retitle callback failed", exc_info=True)

    thread = threading.Thread(target=_runner, daemon=True, name="retitle")
    thread.start()


def maybe_auto_title(
    session_db,
    session_id: str,
    user_message: str,
    conversation_history: Optional[list] = None,
    failure_callback: Optional[FailureCallback] = None,
    main_runtime: dict = None,
    title_callback: Optional[TitleCallback] = None,
    runtime_validator: Optional[RuntimeValidator] = None,
) -> None:
    """Instant inline title, then a daemon-thread upgrade. Call at the START of a turn, before the model."""
    if not session_db or not session_id or not user_message:
        return
    # History may be pre- or post-message. Skip only when BOTH past the opening turn AND named: count alone
    # left a machinery-opened session nameless; title alone never titles on an old store.
    user_msg_count = sum(1 for m in (conversation_history or []) if _is_real_user_turn(m))
    if (user_msg_count > 1 and not _session_is_untitled(session_db, session_id)) or not is_titleable_user_message(user_message):
        return
    if not _auto_title_enabled():  # config read after the cheap guards so the file isn't touched every turn
        logger.debug("Auto-title skipped: auxiliary.title_generation.enabled=false")
        return
    apply_instant_title(session_db, session_id, user_message, title_callback)
    threading.Thread(
        target=auto_title_session,
        args=(session_db, session_id, user_message),
        kwargs=dict(failure_callback=failure_callback, main_runtime=main_runtime, title_callback=title_callback, runtime_validator=runtime_validator),
        daemon=True,
        name="auto-title",
    ).start()
