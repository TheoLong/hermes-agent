# Carry Patches — `consolidated-fixes`

Theo's personal patch stack on top of `origin/main` (NousResearch/hermes-agent).
Everything here is also offered upstream as a focused PR — if upstream merges it,
the patch becomes a `DUPLICATE` (detected via `git patch-id`) and is dropped
on the next sync. If upstream rejects or reshapes it, we keep the local version
and re-apply on rebase.

Workflow: `skill_view hermes-update` → triage → rebase → reapply.

Last synced: **2026-07-05** (rebased onto `f26ae4f68`; 1,575 upstream commits absorbed)

---

## Inventory (6 commits, bottom → top)

| # | SHA prefix | Subject | Upstream PR | Risk on rebase |
|---|------------|---------|-------------|----------------|
| 1 | `d9594dfdb` | feat(discord): auto-rename threads from session titles + periodic retitle | [#29983](https://github.com/NousResearch/hermes-agent/pull/29983) | CLEAN this sync. Carry uses `self.adapters.get(source.platform)` (generic registry) so plugin relocation didn't break the adapter handle. Opt-out flag `disable_thread_auto_rename` retained. |
| 2 | `2f2afcc9d` | fix(discord): restore auto-thread in free-response channels | [#29981](https://github.com/NousResearch/hermes-agent/pull/29981) | **CONFLICT this sync** — upstream renamed `channel_ids`→`channel_keys` in the `skip_thread` line. One-line resolution (keep upstream var, drop `or is_free_channel`). **Test cascade**: upstream `50a7dce6b` (fail-closed auto-thread, 2026-07-01) broke 2 upstream tests once the carry un-suppressed free-response threading — fixed by disabling auto-thread in those 2 fixture tests, folded into this carry. See note 2. |
| 3 | `55870822e` | feat(discord): enrich reply context so agents can fetch full thread | [#29982](https://github.com/NousResearch/hermes-agent/pull/29982) ⚠ author=`Tem Ray` | CLEAN this sync. Append-not-reshape form (keeps upstream's 500-char `[Replying to: "…"]` prefix byte-identical, appends the `fetch_messages(around=)` hint as a 2nd line) — `tests/gateway/test_reply_to_injection.py` passes UNMODIFIED. base.py carries all reply fields (upstream's `reply_to_author_id`/`_name` + our `reply_to_channel_id`/`reply_to_author`). |
| 4 | `84c43c3bf` | fix(kanban): validate per-task --skills against assignee profile at create time | [#45917](https://github.com/NousResearch/hermes-agent/pull/45917) | CLEAN this sync (replayed clean onto the 1,575-commit delta; the #50473 bundle-removal collision resolved at the 2026-06-26 sync stayed resolved). Partial overlap remains with upstream `018009bc3` (warn-not-crash at dispatch) — but the carry's *create-time* preflight has no upstream equivalent, so OVERLAPPING/keep. See note 4. |
| 5 | `375a0b25b` | feat(gateway): kanban auto-react debouncer | [#29985](https://github.com/NousResearch/hermes-agent/pull/29985) | **CONFLICT this sync** — upstream added a cross-session leak guard (`reset_session_vars()`) at the top of `_handle_message_impl`, colliding with the carry's piggyback block. Additive resolution: keep both, leak-guard first. `gateway/kanban_react.py` still a clean-add (no upstream equivalent). PR was opened as 3 commits; local carry is now 1 squashed commit. |
| 6 | `945c4a7fc` | fix: retry holographic memory sqlite locks (author=`jarvis`/JimGat) | [#40167](https://github.com/NousResearch/hermes-agent/pull/40167) | DUPLICATE-WHEN-MERGED — cherry-pick of the upstream PR head; `git patch-id` will drop it once #40167 lands. CLEAN replay while open (touches `plugins/memory/holographic/{store,__init__}.py` + `tests/agent/test_memory_provider.py`). #40167 still OPEN as of this sync; still a real gap. |

SHAs change on every rebase. The **subject lines** are the stable identifier
for triage; use `git log origin/main..HEAD --format="%h %s"` to refresh.

### Dropped this sync (2026-07-05)

| Dropped subject | Reason |
|-----------------|--------|
| `docs: refresh CARRY_PATCHES inventory after 2026-06-26 sync` | Regenerated, not carried — this file is rewritten in place every sync rather than tracked as a replayed commit. |

Nothing was SUPERSEDED or OBSOLETE this sync — all 6 carries survived triage
(patch-id all `unique`, per-subsystem reshaped-supersession grep clean, dry-run
cherry-pick confirmed the 2 conflicts below).

### Dropped previous syncs (historical)

| Dropped subject | Reason |
|-----------------|--------|
| `feat(kanban): auto-subscribe origin conversation on kanban_create` | **SUPERSEDED** (2026-06-21) by upstream `f8d8f045f`. Upstream's version adds TUI/desktop support, a `kanban.auto_subscribe_on_create` config gate, and a `subscribed` bool. Gap retained: our carry's *parent-task subscription inheritance* had no upstream equivalent. |
| `fix(gateway): stop VIRTUAL_ENV leaking into agent subprocesses` (#29980) | **SUPERSEDED** — upstream now has a full `_HERMES_PROVIDER_ENV_BLOCKLIST` system in `tools/environments/local.py` (security advisory GHSA-rhgp-j443-p4rf) that subsumes the carry. |
| `fix(cli): honor root-level provider when model is a string` (#29979) | **SUPERSEDED** (2026-06-07) — upstream `_normalize_root_model_keys()` in `hermes_cli/config.py` extracts root-level provider/base_url/context_length gated on `has_root`, bypassing the "auto"-truthy bug. |

---

## Per-patch rationale & rebase notes

### 1. `feat(discord): auto-rename threads from session titles + periodic retitle`

**Problem:** Discord threads default to the first line of the originating
message — a poor title for a multi-turn agent session.

**Periodic-retitle full-context behavior:** the periodic retitle path assesses a
condensed view of the WHOLE conversation (opening turns + most-recent turns via
`_condense_history`) and is prompted to KEEP the existing title unless the
durable topic has clearly drifted. Unchanged titles are a no-op so the DB and
thread name don't churn. 59/59 in `tests/agent/test_title_generator.py`.

**Prose-rejection guard (2026-07-06):** the retitle model sometimes answers the
"should this change?" question CONVERSATIONALLY ("The title remains accurate.
The conversation is still about …") instead of returning a title. The old code
sanitized + truncated that sentence at 80 chars and stored it AS the title,
which became the live Discord thread name (Theo caught it in this very thread).
Fix: `_looks_like_title()` multi-signal shape guard (reject >10 words / >80
chars / mid-sentence lowercase ". " break / internal newline) wired into
`regenerate_title` — junk output returns `None` → caller keeps the current
title, no rename. The harmful `len>80 → title[:77]+"…"` truncation branch is
gone. The no-op guard in `maybe_retitle_session` also normalizes trailing
punctuation so "Title." doesn't count as a change from "Title". Folded into this
carry via `--fixup`; +15 regression tests (44→59) including the exact
real-world prose string.

**Files:** `agent/title_generator.py`, `gateway/run.py`.

**Opt-out:** `gateway.platforms.discord.extra.disable_thread_auto_rename`
(default `False`), mirroring the Telegram `disable_topic_auto_rename` pattern
from #28986 — added at the triage bot's request on #29983.

**Rebase:** CLEAN this sync. Generic `self.adapters.get()` registry lookup
survives plugin relocation. Note upstream `3b739b990` (strip `<think>` blocks
from title output) touches `agent/title_generator.py` but a different function
(`generate_title` scrubbing) — no overlap with the carry's retitle path.

---

### 2. `fix(discord): restore auto-thread in free-response channels`

**Problem:** A refactor broke auto-thread creation in free-response Discord
channels — responses started landing inline. This carry is a deliberate
REVERT of upstream's suppression (Theo wants free-response AND per-message
auto-thread for conversation isolation).

**Files:** `plugins/platforms/discord/adapter.py`,
`tests/gateway/test_discord_free_response.py`.

**Conflict resolved this sync (2026-07-05):** upstream renamed the variable
`channel_ids`→`channel_keys` in the `skip_thread` assignment. Resolution kept
upstream's variable name and applied the carry's intent — drop the
`or is_free_channel` suffix so free-response channels are NOT skipped:

```python
skip_thread = bool(channel_keys & no_thread_channels)   # NOT `or is_free_channel`
```

**Test cascade fixed + folded into this carry:** upstream landed `50a7dce6b`
("auto-thread failure must not silently fall back to inline reply", 2026-07-01)
AFTER our last sync — making a failed `create_thread` fail-CLOSED (skip the
agent). Two pure-upstream tests
(`test_discord_free_response_channel_overrides_mention_requirement`,
`test_discord_free_response_channel_can_come_from_config_extra`) then broke:
they assert free-response *mention-override*, but with the carry un-suppressing
threading, the `FakeTextChannel` fixture (no real `create_thread`) hit the new
fail-closed path and the agent was never invoked. Fix mirrors the file's own
established pattern (line ~206): set `DISCORD_AUTO_THREAD=false` in those two
tests to keep the assertion focused on gating, marked as LOCAL OVERRIDE tied to
this carry. Folded via `git commit --fixup` + autosquash, so the carry now
contains both the production revert AND the test proof.

**Rebase:** CONFLICT (one line) + test cascade (2 tests) — both resolved.
Verify post-restart by sending a top-level message in a known free-response
channel and confirming a fresh thread opens.

---

### 3. `feat(discord): enrich reply context so agents can fetch full thread`

**Problem:** Discord reply events delivered only the single quoted parent;
agents couldn't fetch the rest of the thread above.

**Files:** `gateway/platforms/base.py`, `gateway/run.py`,
`plugins/platforms/discord/adapter.py`, `tools/discord_tool.py`.

**Author quirk:** committed as `Tem Ray <tem@anaheim.dev>` — won't match the
upstream AUTHOR_MAP. If upstream merges #29982, they may ask for an amend to
`Theo Long <9421870+TheoLong@users.noreply.github.com>` first.

**Rebase:** CLEAN this sync. The carry is in append-not-reshape form (settled at
the 2026-06-26 sync): it keeps upstream's `[Replying to: "…"]` prefix and 500-
char cap BYTE-IDENTICAL and appends only the
`discord(action='fetch_messages', around=<msg_id>)` hint as a separate line, so
upstream's `tests/gateway/test_reply_to_injection.py` passes UNMODIFIED (verified
green in this sync's slice). The distinctive capability — active context pull via
`around=` — still has no upstream equivalent (`fetch_messages` has no `around`
param on main), so this stays a keep.

---

### 4. `fix(kanban): validate per-task --skills against assignee profile at create time`

**Problem:** `kanban create --skill <name>` accepted skills installed only
under the default root HERMES_HOME but not under the target assignee profile.
The spawned worker crashed at CLI startup with `ValueError: Unknown skill(s)`,
the dispatcher recorded `pid <N> not alive`, `consecutive_failures` incremented,
and the circuit breaker auto-blocked the task at threshold=2.

**Files:** `hermes_cli/kanban_db.py`, `tests/hermes_cli/test_kanban_core_functionality.py`.

**Mechanism:** pre-flight gate in `create_task` — for non-default assignees
whose profile dir exists, every `skills` entry must resolve via the worker's
skill search path. Adds `_skill_resolvable_for_profile(name, hermes_home)`;
legacy `_kanban_worker_skill_available` kept as a back-compat shim.
Defense-in-depth: `_default_spawn` drops still-unresolvable per-task skills
(gated by `HERMES_KANBAN_SKIP_SKILL_PREFLIGHT`).

**Partial overlap (not superseded):** upstream `018009bc3` ("unknown skill
warns instead of crashing the worker") now handles the same *symptom* at
worker-startup/dispatch time — so the carry's dispatch-time defense-in-depth
layer is partially redundant. But upstream has NO create-time preflight
(grep for `_skill_resolvable_for_profile`/`preflight` on main's `kanban_db.py`
is empty), which is the carry's headline value: reject a bad task before it
ever spawns. Classify OVERLAPPING/keep. (Optional future trim: slim the
dispatch-time layer now that `018009bc3` covers it.)

**Rebase:** CLEAN this sync (the #50473 bundle-removal collision from the
2026-06-26 sync stayed resolved).

**Upstream PR housekeeping:** keep #45917 as the canonical PR; close any
duplicate (#47496) as a dup; rebuild #45917's branch on current main.

---

### 5. `feat(gateway): kanban auto-react debouncer`

**Problem:** When a kanban worker hits `blocked` / `crashed` / `gave_up` /
`timed_out`, the originating chat got a notifier ping that often went unread
for hours.

**Files:** `gateway/kanban_react.py` (new), `gateway/kanban_watchers.py`,
`gateway/run.py`, `tests/gateway/test_kanban_react.py`.

**Mechanism:** per-session debouncer batches terminal events. On a real user
turn it drains buffered events and prepends them as a preamble (piggyback);
otherwise it dispatches a synthetic `internal=True` `MessageEvent` into
`_handle_message` so the session's agent wakes up.

**Conflict resolved this sync (2026-07-05):** upstream added a cross-session
leak guard (`reset_session_vars()` at the top of `_handle_message_impl`, to
stop a concurrent message's `HERMES_SESSION_*` ContextVars leaking into a
subprocess) at the exact spot the carry inserts its kanban piggyback block.
Additive collision, independent concerns — resolution keeps BOTH, ordered
leak-guard first (it must run before any subprocess spawn), then the carry's
piggyback (session key derives from `source`, not ContextVars, so ordering is
safe). `ast.parse` OK, smoke green.

**Rebase:** CONFLICT (additive) resolved. No upstream auto-react / fanout
mechanism found — if one lands, this becomes SUPERSEDED. PR #29985 was opened
as 3 commits (debouncer + 2 log bumps); local carry is now 1 squashed commit —
reconcile on PR refresh.

---

### 6. `fix: retry holographic memory sqlite locks`

**Author:** `jarvis <jarvis@jarvis.gat.ink>` (JimGat) — NOT a Theo/Tem carry.
Straight cherry-pick of the head of upstream PR
[#40167](https://github.com/NousResearch/hermes-agent/pull/40167), applied
locally ahead of merge.

**Problem:** `memory_store.db` is a single SQLite file written by BOTH the
always-on gateway and any concurrent CLI/cron session. Under writer contention
the subprocess's `fact_store` / `fact_feedback` writes fast-fail with
`database is locked` even though WAL is enabled.

**Fix:** explicit `PRAGMA busy_timeout = 60000` + connect `timeout` 10s→60s,
plus retry-on-`locked` with `rollback()` and exponential backoff on the two
write paths. The retry counter rides through `args` as `_lock_retry` — safe,
since the action handlers consume named keys and never splat `args`.

**Rebase:** CLEAN replay while #40167 is open. Once it merges, `git patch-id`
flags this as **DUPLICATE** and the next sync drops it. #40167 still OPEN as of
2026-07-05; upstream `plugins/memory/holographic/` still has no `busy_timeout`
or retry logic. Still a real gap. **Watch this one next sync.**

---

## Sync procedure

Always use `skill_view hermes-update`. Short version:

```bash
cd ~/.hermes/hermes-agent
git status --porcelain                      # must be empty (stash WIP first)
git fetch origin --quiet
git rev-list --left-right --count HEAD...origin/main

# safety net
git branch sync/$(date +%Y-%m-%d)-pre-upstream
git push fork sync/$(date +%Y-%m-%d)-pre-upstream

# triage: for each commit in origin/main..HEAD run patch-id dedup vs
# HEAD..origin/main, classify SUPERSEDED / OBSOLETE / DUPLICATE / CLEAN /
# OVERLAPPING. patch-id only catches byte-identical diffs — ALSO grep
# upstream log per-subsystem for RESHAPED supersessions, AND dry-run
# cherry-pick each carry onto origin/main to size conflicts before planning.

# fresh branch at upstream HEAD, cherry-pick surviving carries one at a time
git checkout -B consolidated-fixes-new origin/main
git cherry-pick <sha> ...   # resolve conflicts per-commit

.venv/bin/python -m pytest \
  tests/gateway/test_kanban_react.py \
  tests/hermes_cli/test_kanban_core_functionality.py \
  tests/agent/test_title_generator.py \
  tests/gateway/test_discord_free_response.py \
  tests/gateway/test_reply_to_injection.py \
  tests/gateway/test_discord_double_dispatch.py \
  tests/agent/test_memory_provider.py \
  -q -p no:cacheprovider -o 'addopts=' --timeout=60

# branch swap (date-suffix old for rollback) + push
git branch -m consolidated-fixes consolidated-fixes-old-$(date +%Y-%m-%d)
git branch -m consolidated-fixes-new consolidated-fixes
git push fork consolidated-fixes --force-with-lease
# never push to origin
```

Then for each upstream PR (#29981…#29985, #40167, #45917), check
`gh pr view <n> --json state` and if `MERGED`, drop the matching local commit
on the next rebase.

---

## Hard rules

- Never `git push origin` from this repo (origin = NousResearch, read-only for us).
- Never `git pull` plain — always triage via this doc + `hermes-update` skill.
- Working tree must be clean before rebase; stash WIP, restore after.
- Force-pushes use `--force-with-lease`, never `--force`.
- patch-id only catches byte-identical carries. After a large sync (100s of
  commits), ALSO grep the upstream log per-subsystem for reshaped
  supersessions, AND dry-run cherry-pick each carry — a feature can merge
  upstream in a different shape that patch-id won't flag.
- **A carry that reverts upstream behavior will cascade into upstream tests.**
  This sync: carry #2 un-suppresses free-response auto-thread; upstream's new
  fail-closed path (`50a7dce6b`) then broke 2 upstream fixture tests. Trace the
  reverted behavior through the test bodies and fold the fix into the carry via
  `--fixup`. Re-run the FULL slice after any fixup (downstream SHAs change).
- The running gateway carries stale `.pyc` until restarted. After a sync, the
  on-disk repo is new but the live gateway still runs old code until
  `systemctl --user restart hermes-gateway`. Don't self-restart mid-turn — ask Theo.
