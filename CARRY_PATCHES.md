# Carry Patches — `consolidated-fixes`

Theo's personal patch stack on top of `origin/main` (NousResearch/hermes-agent).
Everything here is also offered upstream as a focused PR — if upstream merges it,
the patch becomes a `DUPLICATE` (detected via `git patch-id`) and is dropped
on the next sync. If upstream rejects or reshapes it, we keep the local version
and re-apply on rebase.

Workflow: `skill_view hermes-update` → triage → rebase → reapply.

Last synced: **2026-08-17** (rebased onto current `origin/main`; ~7,346 upstream commits absorbed). **Kanban carries dropped this sync at Theo's request — kanban is now pure upstream/master.**

---

## Inventory (4 commits, bottom → top)

| # | SHA prefix | Subject | Upstream PR | Risk on rebase |
|---|------------|---------|-------------|----------------|
| 1 | `f53aafce1` | fix(discord): restore auto-thread in free-response channels | [#29981](https://github.com/NousResearch/hermes-agent/pull/29981) (OPEN) | CONFLICT (single-hunk) this sync. Upstream extracted `_get_no_thread_channels()`; kept upstream's helper + applied the carry's intent (drop `or is_free_channel`). `skip_thread = … or is_free_channel` still live on main (adapter.py:8162) → real gap. Test block additive. |
| 2 | `e9cde709b` | feat(discord): enrich reply context so agents can fetch full thread | [#29982](https://github.com/NousResearch/hermes-agent/pull/29982) (OPEN) ⚠ author=`Tem Ray` | CONFLICT (additive) this sync in `base.py` — upstream's Phase-4 relay refactor added `prompt_response`; UNION'd with the carry's `reply_to_channel_id`/`reply_to_author`. run.py/adapter/discord_tool auto-merged. Append-not-reshape form intact; `test_reply_to_injection.py` passes UNMODIFIED. `fetch_messages(around=)` still no upstream equivalent. |
| 3 | `45d7d3502` | feat(discord): periodic thread retitle on top of upstream semantic titles | [#29983](https://github.com/NousResearch/hermes-agent/pull/29983) (OPEN) | CONFLICT (major reshape) this sync. Upstream extracted the whole inline `run_sync` into `agent/turn_context.py` + moved auto-title to TURN START. Took upstream's extraction wholesale; **re-injected the periodic `maybe_retitle_session` call at the turn-END return site in `run.py` (~L6357)** where `final_response`+history are in scope, adapting to upstream's new 2-arg `_on_session_title(title, title_source)` callback via a `lambda t: cb(t, "llm")` shim. `title_generator.py` + test conflicts were independent-symbol additive concatenations. |
| 4 | `db2218599` | feat(browser): **parallel browser execution across multiple agents & profiles** | [#49691](https://github.com/NousResearch/hermes-agent/pull/49691) (OPEN) | CONFLICT (major reshape) this sync. Upstream extracted `DEFAULT_CONFIG` into `hermes_cli/config_defaults.py` AND already landed `restrict_evaluate`. Took upstream's import; **added the carry's `browser.profiles: {}` key into `config_defaults.py`** (new home). `browser_tool.py` conflict was just the `browser_navigate` signature (+`profile` arg) — kept upstream's new `evaluate_url_safety` + carry's signature; all profile routing machinery (`::profile:` composite key, per-endpoint lock, owned tabs) auto-merged clean. Drop when #49691 merges. |

SHAs change on every rebase. The **subject lines** are the stable identifier
for triage; use `git log origin/main..HEAD --format="%h %s"` to refresh.

### Dropped this sync (2026-08-17)

| Dropped subject | Reason |
|-----------------|--------|
| `fix(kanban): validate per-task --skills against assignee profile at create time` (was #29985/#44101 family) | **DROPPED at Theo's request** (2026-08-17) — Theo doesn't use kanban much now and wants kanban synced to upstream master. Carry removed; kanban is now pure upstream. Close our PR #29985; leave @AIalliAI's #44101 alone (we were only deferring to it). |
| `feat(gateway): kanban auto-react debouncer` ([#29985](https://github.com/NousResearch/hermes-agent/pull/29985)) | **DROPPED at Theo's request** (2026-08-17) — same reason. Also note the carry never had a production `_kanban_react` instantiation (getattr-only), so nothing in the running gateway depended on it. Close PR #29985 upstream. |
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
