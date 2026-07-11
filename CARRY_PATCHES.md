# Carry Patches — `consolidated-fixes`

Theo's personal patch stack on top of `origin/main` (NousResearch/hermes-agent).
Everything here is also offered upstream as a focused PR — if upstream merges it,
the patch becomes a `DUPLICATE` (detected via `git patch-id`) and is dropped
on the next sync. If upstream rejects or reshapes it, we keep the local version
and re-apply on rebase.

Workflow: `skill_view hermes-update` → triage → rebase → reapply.

Last synced: **2026-07-10** (rebased onto current `origin/main`; 518 upstream commits absorbed)

---

## Inventory (6 commits, bottom → top)

| # | SHA prefix | Subject | Upstream PR | Risk on rebase |
|---|------------|---------|-------------|----------------|
| 1 | `7656338c8` | fix(discord): restore auto-thread in free-response channels | [#29981](https://github.com/NousResearch/hermes-agent/pull/29981) | CLEAN this sync (dry-run + real pick clean). Deliberate revert of upstream free-response thread suppression. Watch the fail-closed cascade (`50a7dce6b`) — the two fixture tests stayed green this sync. |
| 2 | `4313b1e33` | feat(discord): enrich reply context so agents can fetch full thread | [#29982](https://github.com/NousResearch/hermes-agent/pull/29982) ⚠ author=`Tem Ray` | CLEAN this sync. Append-not-reshape form; `tests/gateway/test_reply_to_injection.py` passes UNMODIFIED. Distinctive `fetch_messages(around=)` pull still has no upstream equivalent. |
| 3 | `d0d528cd5` | fix(kanban): validate per-task --skills against assignee profile at create time | [#44101](https://github.com/NousResearch/hermes-agent/pull/44101) (deferred to @AIalliAI) | CLEAN this sync. **NO PR of our own** — Theo's #45917/#47496 were closed deferring to @AIalliAI's #44101, still OPEN + not on main, so the create-time preflight remains a real gap we carry. Open no new PR. |
| 4 | `a7a9369b2` | feat(gateway): kanban auto-react debouncer | [#29985](https://github.com/NousResearch/hermes-agent/pull/29985) | CLEAN this sync (replayed clean onto the 518-commit delta; the prior `reset_session_vars()` additive collision stayed resolved). No upstream auto-react/fanout mechanism found. |
| 5 | `e4bc33aa4` | feat(discord): periodic thread retitle on top of upstream semantic titles | [#29983](https://github.com/NousResearch/hermes-agent/pull/29983) | **RESHAPED this sync** — see note 5. Upstream `0d9ed9214` landed the first-turn Discord semantic rename; carry reduced to the periodic-retitle delta only. |
| 6 | `965e4521b` | feat(browser): named browser profiles with same-profile concurrency | [#49691](https://github.com/NousResearch/hermes-agent/pull/49691) | Fresh this install (2026-07-10). Adds `browser.profiles` (name→CDP endpoint) + `::profile:<name>` composite session key routing, plus same-profile concurrency (per-session owned tab + per-endpoint serialization lock). 3 files: `tools/browser_tool.py`, `hermes_cli/config.py`, `tests/tools/test_browser_profiles.py`. Reuses the `::local` seam — additive, low reshape risk. Drop when #49691 merges. |

SHAs change on every rebase. The **subject lines** are the stable identifier
for triage; use `git log origin/main..HEAD --format="%h %s"` to refresh.

### Dropped this sync (2026-07-10)

| Dropped subject | Reason |
|-----------------|--------|
| `fix: retry holographic memory sqlite locks` (#40167, author=JimGat) | **SUPERSEDED** — PR #40167 was CLOSED by teknium1 as superseded. The `database is locked` contention is fixed at the root on `origin/main`: `b5226caff` (share one refcounted SQLite connection + lock per DB, autocommit so a failed write can't pin the write lock), merged as #61726 / `a80104666` (confirmed ancestor of `origin/main`). The carry retried *around* the lock; upstream eliminated the cross-connection race. Clean drop, no residual. |
| `docs: refresh CARRY_PATCHES inventory …` | Regenerated in place every sync, not carried as a replayed commit. |

### Partially dropped this sync (the reshaped half)

| Dropped hunk | Reason |
|--------------|--------|
| Carry #5's **first-turn** Discord thread rename (`gateway/run.py`: `_is_discord_thread_lane`, `_schedule_discord_thread_rename`, `_rename_discord_thread_for_session_title`, `_sanitize_discord_thread_name`, `_DISCORD_THREAD_NAME_MAX`, `_DISCORD_RENAME_DEDUPE_TTL_S`) | **SUPERSEDED** by upstream `0d9ed9214` ("Add semantic titles for Discord auto-threads") + `1deeaf71a` (UTF-16 truncation). Upstream's `_sanitize_discord_thread_title` + `_schedule_discord_semantic_thread_rename` now own the first-turn path. Carry's own trio removed as dead code; periodic retitle reuses upstream's callback via `maybe_auto_title_kwargs`. |

### Dropped previous syncs (historical)

| Dropped subject | Reason |
|-----------------|--------|
| `feat(kanban): auto-subscribe origin conversation on kanban_create` | **SUPERSEDED** (2026-06-21) by upstream `f8d8f045f` (config gate + TUI/desktop + `subscribed` bool). Parent-task subscription-inheritance gap was re-offered as a delta PR. |
| `fix(gateway): stop VIRTUAL_ENV leaking into agent subprocesses` (#29980) | **SUPERSEDED** — upstream `_HERMES_PROVIDER_ENV_BLOCKLIST` (GHSA-rhgp-j443-p4rf) subsumes it. |
| `fix(cli): honor root-level provider when model is a string` (#29979) | **SUPERSEDED** (2026-06-07) — upstream `_normalize_root_model_keys()`. |

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
