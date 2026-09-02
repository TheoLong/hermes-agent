# Carry Patches — `consolidated-fixes`

Theo's personal patch stack on top of `origin/main` (NousResearch/hermes-agent).
Everything here is also offered upstream as a focused PR — if upstream merges it,
the patch becomes a `DUPLICATE` (detected via `git patch-id`) and is dropped
on the next sync. If upstream rejects or reshapes it, we keep the local version
and re-apply on rebase.

Workflow: `skill_view hermes-update` → triage → rebase → reapply.

Last synced: **2026-09-02** (rebased onto current `origin/main`; ~3,938 upstream commits absorbed, Jul 23 → Sep 2). **The adopted 413 byte-measurement carry dropped this sync — upstream landed it.**

---

## Inventory (4 commits, bottom → top)

| # | SHA prefix | Subject | Upstream PR | Risk on rebase |
|---|------------|---------|-------------|----------------|
| 1 | `77c38f963` | fix(discord): restore auto-thread in free-response channels | [#29981](https://github.com/NousResearch/hermes-agent/pull/29981) (OPEN) | **CLEAN** this sync. `skip_thread = … or is_free_channel` still live on `origin/main` (adapter.py:8277) → still a real gap. Verified post-pick: line reads `skip_thread = bool(channel_keys & no_thread_channels)`. |
| 2 | `21130f18c` | feat(discord): enrich reply context so agents can fetch full thread | [#29982](https://github.com/NousResearch/hermes-agent/pull/29982) (OPEN) ⚠ author=`Tem Ray` | **CLEAN** this sync — no conflict despite ~3.9k commits of churn. `reply_to_channel_id` still absent from main (0 files). Append-not-reshape form intact; `test_reply_to_injection.py` passes UNMODIFIED (upstream tests green). |
| 3 | `f223c897b` | feat(discord): periodic thread retitle on top of upstream semantic titles | [#29983](https://github.com/NousResearch/hermes-agent/pull/29983) (OPEN) | CONFLICT (single hunk, additive) in `gateway/run.py`. Upstream added `_TELEGRAM_LOBBY_REMINDER_COOLDOWN_S` + `_telegram_topic_cooldown_key` in the same region; carry side was empty → kept upstream's block wholesale. **Arity re-verified against upstream `808a22ea00d` ("gate relay-only thread rename kwargs")**: `_on_session_title` is still 2-arg `(title, title_source)` and now gates on `title_source == "llm"`, which the carry's `lambda t: cb(t, "llm")` shim satisfies. Not a no-op. |
| 4 | `62bb6aa7b` | feat(browser): **parallel browser execution across multiple agents & profiles** | [#49691](https://github.com/NousResearch/hermes-agent/pull/49691) (OPEN) | CONFLICT (true semantic) in `tools/browser_tool.py`. Upstream wrapped `browser_navigate` registration in `routed_browser_handler(...)` + `check_browser_navigate_requirements`; the carry passed `profile=args.get("profile")`. **Synthesized both** — kept upstream's routing structure and threaded `profile=` into its `fallback=` lambda. Faithful to the original carry, which also only threaded profile through `browser_navigate` (verified against the carry's own diff — no scope creep). All `::profile:` routing machinery auto-merged clean. |

SHAs change on every rebase. The **subject lines** are the stable identifier
for triage; use `git log origin/main..HEAD --format="%h %s"` to refresh.

### Dropped this sync (2026-09-02)

| Dropped subject | Reason |
|-----------------|--------|
| `fix(agent): 413 recovery measures bytes, not token estimates` (upstream [#97197](https://github.com/NousResearch/hermes-agent/pull/97197), author Brian) | **REDUNDANT — absorbed by upstream.** Adopted locally 2026-09-02 (a few hours before this sync) because our tree was ~3.9k commits behind and the fix was already merged upstream as `b855f86bc8e5` on 2026-08-28. This rebase brings it in natively. Proof: `git cherry-pick` of the carry onto the new base reports *"The previous cherry-pick is now empty"* (zero-byte diff). Post-rebase verification confirms `serialized_messages_bytes()` and the `new_bytes < original_bytes` check are present **from upstream**, not from the carry. Companion fix #97160 (compaction frees historical image bytes) also arrives with this sync. |
| `docs: refresh CARRY_PATCHES inventory …` | Regenerated in place every sync, not carried as a replayed commit. |

### Dropped previous syncs (historical)

| Dropped subject | Reason |
|-----------------|--------|
| `fix: retry holographic memory sqlite locks` (#40167) | **SUPERSEDED** (2026-07-10) — CLOSED, root-caused on main by `b5226caff` / #61726 (one refcounted SQLite connection + lock per DB). |
| `feat(kanban): auto-subscribe origin conversation on kanban_create` | **SUPERSEDED** (2026-06-21) by upstream `f8d8f045f`. |
| `fix(gateway): stop VIRTUAL_ENV leaking into agent subprocesses` (#29980) | **SUPERSEDED** — `_HERMES_PROVIDER_ENV_BLOCKLIST` (GHSA-rhgp-j443-p4rf). |
| `fix(cli): honor root-level provider when model is a string` (#29979) | **SUPERSEDED** (2026-06-07) — `_normalize_root_model_keys()`. |

---

## Per-patch rationale & rebase notes

### 1. `fix(discord): restore auto-thread in free-response channels`

**Problem:** A refactor broke auto-thread creation in free-response Discord
channels — responses landed inline. Deliberate REVERT of upstream's suppression
(Theo wants free-response AND per-message auto-thread for isolation).

**Files:** `plugins/platforms/discord/adapter.py`,
`tests/gateway/test_discord_free_response.py`.

**Rebase:** CLEAN this sync. Cascade risk is upstream `50a7dce6b` (fail-closed
auto-thread) + the double-dispatch dedup (`807bdc17f`,
`tests/gateway/test_discord_double_dispatch.py`) — both green in this sync's
slice (136 passed in the discord/title slice). Verify post-restart by sending a
top-level message in a known free-response channel and confirming a fresh thread
opens.

---

### 2. `feat(discord): enrich reply context so agents can fetch full thread`

**Problem:** Discord reply events delivered only the single quoted parent;
agents couldn't fetch the rest of the thread above.

**Files:** `gateway/platforms/base.py`, `gateway/run.py`,
`plugins/platforms/discord/adapter.py`, `tools/discord_tool.py`.

**Author quirk:** committed as `Tem Ray <tem@anaheim.dev>` — won't match the
upstream AUTHOR_MAP. If upstream merges #29982, they may ask for an amend to
`Theo Long <9421870+TheoLong@users.noreply.github.com>` first.

**Rebase:** CLEAN this sync. Append-not-reshape form keeps upstream's
`[Replying to: "…"]` prefix + 500-char cap byte-identical and appends only the
`fetch_messages(around=<msg_id>)` hint as a separate line, so
`tests/gateway/test_reply_to_injection.py` passes UNMODIFIED. The active
`around=` pull still has no upstream equivalent — keep.

---

### 3. `fix(kanban): validate per-task --skills against assignee profile at create time`

**Problem:** `kanban create --skill <name>` accepted skills installed only under
the default root HERMES_HOME but not under the target assignee profile; the
spawned worker crashed at CLI startup and the circuit breaker auto-blocked the
task.

**Files:** `hermes_cli/kanban_db.py`,
`tests/hermes_cli/test_kanban_core_functionality.py`.

**Mechanism:** create-time pre-flight gate — for non-default assignees whose
profile dir exists, every `skills` entry must resolve via the worker's skill
search path. Defense-in-depth: `_default_spawn` drops still-unresolvable per-task
skills (gated by `HERMES_KANBAN_SKIP_SKILL_PREFLIGHT`).

**PR posture:** Theo's own PRs (#45917, #47496) were CLOSED on a prior sync,
deferring to @AIalliAI's **#44101**. As of this sync #44101 is still **OPEN and
NOT on main** (grep for `_skill_resolvable_for_profile`/preflight on main's
`kanban_db.py` is empty), so the create-time preflight is still a real local
gap. **Keep the carry; open NO new PR** (reopening would re-create the duplicate
mess and is poor etiquette toward the deferred-to contributor). Drop next sync
if #44101 merges.

**Rebase:** CLEAN this sync.

---

### 4. `feat(gateway): kanban auto-react debouncer`

**Problem:** When a kanban worker hits `blocked` / `crashed` / `gave_up` /
`timed_out`, the originating chat's notifier ping often went unread for hours.

**Files:** `gateway/kanban_react.py` (new), `gateway/kanban_watchers.py`,
`gateway/run.py`, `tests/gateway/test_kanban_react.py`.

**Mechanism:** per-session debouncer batches terminal events. On a real user turn
it drains buffered events and prepends them as a preamble (piggyback); otherwise
it dispatches a synthetic `internal=True` `MessageEvent` to wake the session's
agent.

**Rebase:** CLEAN this sync (prior `reset_session_vars()` additive collision
stayed resolved). No upstream auto-react/fanout mechanism found — becomes
SUPERSEDED if one lands. PR #29985 opened as 3 commits; local carry is 1 squashed
commit — reconcile on PR refresh.

---

### 5. `feat(discord): periodic thread retitle on top of upstream semantic titles`

**Problem (original carry):** Discord threads defaulted to the first line of the
originating message — a poor title for a multi-turn agent session. The original
carry did BOTH first-turn rename and periodic retitle.

**Reshaped this sync (2026-07-10):** upstream `0d9ed9214` ("Add semantic titles
for Discord auto-threads") now owns the **first-turn** rename via
`_sanitize_discord_thread_title` (UTF-16-aware, `1deeaf71a`) +
`_schedule_discord_semantic_thread_rename`. The carry is reduced to the
**residual delta upstream still lacks** — periodic retitle:

- `agent/title_generator.py`: `maybe_retitle_session` re-evaluates the session
  title every few user turns after the initial auto-title and fires the existing
  title_callback only when the durable topic has drifted. `regenerate_title`
  assesses a condensed whole-conversation view (`_condense_history`) and is
  biased to KEEP the current title; unchanged titles are a no-op.
- `gateway/run.py`: the periodic call site reuses upstream's semantic rename
  callback via the shared `maybe_auto_title_kwargs`, so no duplicate rename
  plumbing exists. The carry's own first-turn trio + name-sanitizer + constants
  were removed as dead code.

**Prose-rejection guard (retained):** `_looks_like_title()` multi-signal shape
guard (reject >10 words / >80 chars / mid-sentence lowercase ". " break /
internal newline) wired into `regenerate_title` — junk conversational output
returns `None` → caller keeps the current title. The harmful
`len>80 → title[:77]+"…"` truncation branch is gone.

**Files:** `agent/title_generator.py`, `gateway/run.py`,
`tests/agent/test_title_generator.py`.

**Rebase:** RESHAPED (first-turn half superseded, periodic-retitle delta kept).
`gateway/run.py` conflicted on the title_callback branch; resolved by taking
upstream's `_is_discord_auto_thread_lane` / `_schedule_discord_semantic_thread_rename`.
`title_generator.py` + its tests applied clean. Smoke green
(`tests/agent/test_title_generator.py` in the 174-test gate-clearing run).

**Opt-out:** upstream's semantic-title path owns the first-turn config now;
periodic retitle piggybacks it.
