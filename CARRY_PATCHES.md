# Carry Patches — `consolidated-fixes`

Theo's personal patch stack on top of `origin/main` (NousResearch/hermes-agent).
Everything here is also offered upstream as a focused PR — if upstream merges it,
the patch becomes a `DUPLICATE` (detected via `git patch-id`) and is dropped
on the next sync. If upstream rejects or reshapes it, we keep the local version
and re-apply on rebase.

Workflow: `skill_view hermes-update` → triage → rebase → reapply.

Last synced: **2026-06-26** (rebased onto `7d568293f`; 630 upstream commits absorbed)

---

## Inventory (6 commits, bottom → top)

| # | SHA prefix | Subject | Upstream PR | Risk on rebase |
|---|------------|---------|-------------|----------------|
| 1 | `40532609a` | feat(discord): auto-rename threads from session titles + periodic retitle | [#29983](https://github.com/NousResearch/hermes-agent/pull/29983) | CLEAN this sync. Carry uses `self.adapters.get(source.platform)` (generic registry) so plugin relocation didn't break the adapter handle. |
| 2 | `ae41a6fde` | fix(discord): restore auto-thread in free-response channels | [#29981](https://github.com/NousResearch/hermes-agent/pull/29981) | CLEAN this sync. Deliberate revert of upstream's free-response auto-thread suppression; target `plugins/platforms/discord/adapter.py`. Verified against upstream's new `test_discord_double_dispatch.py` (thread-starter dedup `807bdc17f`) — no cascade, both green. |
| 3 | `7250cc14c` | feat(discord): enrich reply context so agents can fetch full thread | [#29982](https://github.com/NousResearch/hermes-agent/pull/29982) ⚠ author=`Tem Ray` | CLEAN this sync (the #49212 passive-hydration collision resolved at the 2026-06-21 sync stayed resolved; replayed clean onto 630-commit delta). base.py carries all 5 reply fields (3 upstream + 2 ours). |
| 4 | `daa1a46f9` | fix(kanban): validate per-task --skills against assignee profile at create time | [#45917](https://github.com/NousResearch/hermes-agent/pull/45917) | **OVERLAPPING this sync** — conflicted with upstream `84e1d31e5` (#50473, "fold worker/orchestrator skills into injected guidance") in `hermes_cli/kanban_db.py` + `tests/hermes_cli/test_kanban_core_functionality.py`. See note 4. |
| 5 | `af8eaebd5` | feat(gateway): kanban auto-react debouncer | [#29985](https://github.com/NousResearch/hermes-agent/pull/29985) | CLEAN this sync. `gateway/kanban_react.py` (new) + `gateway/run.py` + tests. INFO/WARNING log bumps folded into this commit. If upstream lands its own auto-react/fanout, this becomes SUPERSEDED. |
| 6 | `23db8af5d` | fix: retry holographic memory sqlite locks (author=`jarvis`/JimGat) | [#40167](https://github.com/NousResearch/hermes-agent/pull/40167) | DUPLICATE-WHEN-MERGED — cherry-pick of the upstream PR head; `git patch-id` will drop it once #40167 lands. CLEAN replay while open (touches `plugins/memory/holographic/{store,__init__}.py` + `tests/agent/test_memory_provider.py`). #40167 still OPEN as of this sync; still a real gap. |

SHAs change on every rebase. The **subject lines** are the stable identifier
for triage; use `git log origin/main..HEAD --format="%h %s"` to refresh.

### Dropped this sync (2026-06-26)

| Dropped subject | Reason |
|-----------------|--------|
| `docs: refresh CARRY_PATCHES inventory after 2026-06-21 sync` | Regenerated, not carried — this file is rewritten in place every sync rather than tracked as a replayed commit. |

### Dropped previous syncs (historical)

| Dropped subject | Reason |
|-----------------|--------|
| `feat(kanban): auto-subscribe origin conversation on kanban_create` | **SUPERSEDED** (2026-06-21) by upstream `f8d8f045f`. Upstream's version adds TUI/desktop support, a `kanban.auto_subscribe_on_create` config gate, and a `subscribed` bool. Gap retained: our carry's *parent-task subscription inheritance* had no upstream equivalent — re-offer as a follow-up on top of `f8d8f045f`; close our PR #29984 as superseded. |
| `fix(gateway): stop VIRTUAL_ENV leaking into agent subprocesses` (#29980) | **SUPERSEDED** — upstream now has a full `_HERMES_PROVIDER_ENV_BLOCKLIST` system in `tools/environments/local.py` (security advisory GHSA-rhgp-j443-p4rf) that subsumes the carry. Absent from the live stack since before the 2026-06-21 sync. |
| `fix(cli): honor root-level provider when model is a string` (#29979) | **SUPERSEDED** (2026-06-07) — upstream `_normalize_root_model_keys()` in `hermes_cli/config.py` extracts root-level provider/base_url/context_length gated on `has_root`, bypassing the "auto"-truthy bug. |

---

## Per-patch rationale & rebase notes

### 1. `feat(discord): auto-rename threads from session titles + periodic retitle`

**Problem:** Discord threads default to the first line of the originating
message — a poor title for a multi-turn agent session.

**Periodic-retitle full-context fix (2026-07-04):** the periodic retitle path
originally called `generate_title(user_message, assistant_response)` — it only
saw the *latest exchange*, so a brief sub-task (e.g. "write the PDF" inside a
long RFE conversation) clobbered a title describing the real subject. Reworked
to `regenerate_title(history_snapshot, current_title)`, which assesses a
condensed view of the WHOLE conversation (opening turns + most-recent turns via
`_condense_history`) and is prompted to KEEP the existing title unless the
durable topic has clearly drifted. Unchanged titles are treated as a no-op so
the DB and thread name don't churn. Folded into this carry (not a separate
commit); 40/40 in `tests/agent/test_title_generator.py`.

**Files:** `agent/title_generator.py`, `gateway/run.py`.

**Wind direction:** upstream is *refining* rename behavior, NOT adding a disable
flag. No opt-out needed on #29983 yet. If upstream adds
`disable_topic_auto_rename`-style semantics to a generic helper, switch our
Discord path to consume that helper instead of duplicating it, and offer a
matching `gateway.platforms.discord.extra.disable_thread_auto_rename`.

**Rebase:** CLEAN this sync. Generic `self.adapters.get()` registry lookup
survives plugin relocation.

---

### 2. `fix(discord): restore auto-thread in free-response channels`

**Problem:** A refactor broke auto-thread creation in free-response Discord
channels — responses started landing inline. This carry is a deliberate
REVERT of upstream's suppression.

**Files:** `plugins/platforms/discord/adapter.py`.

**Rebase:** CLEAN this sync (cherry-pick applied with no conflict). Upstream
added `807bdc17f` ("prevent double dispatch of Discord messages via
thread-starter dedup") + `tests/gateway/test_discord_double_dispatch.py` this
cycle — a DIFFERENT concern (dedup of the thread-starter echo), additive to the
adapter, no overlap with the carry's auto-thread restore. Both green in the
smoke slice. Verify post-restart by sending a top-level message in a known
free-response channel and confirming a fresh thread opens.

---

### 3. `feat(discord): enrich reply context so agents can fetch full thread`

**Problem:** Discord reply events delivered only the single quoted parent;
agents couldn't fetch the rest of the thread above.

**Files:** `gateway/platforms/base.py`, `gateway/run.py`,
`plugins/platforms/discord/adapter.py`, `tools/discord_tool.py`.

**Author quirk:** committed as `Tem Ray <tem@anaheim.dev>` — won't match the
upstream AUTHOR_MAP. If upstream merges #29982, they may ask for an amend to
`Theo Long <9421870+TheoLong@users.noreply.github.com>` first.

**Rebase:** CLEAN this sync. The #49212 passive-hydration collision was
resolved at the 2026-06-21 sync (base.py keeps all 5 reply fields — upstream's
3 cross-platform + our 2 Discord-populated; run.py merges both decoration
paths). That resolution replayed clean onto the 630-commit delta. The
distinctive carry capability — `discord(action='fetch_messages', around=...)`
for active context pull — still has no upstream equivalent, so this stays a
keep.

---

### 4. `fix(kanban): validate per-task --skills against assignee profile at create time`

**Problem:** `kanban create --skill <name>` accepted skills installed only
under the default root HERMES_HOME but not under the target assignee profile.
The spawned worker crashed at CLI startup with `ValueError: Unknown skill(s)`,
the dispatcher recorded `pid <N> not alive`, `consecutive_failures` incremented,
and the circuit breaker auto-blocked the task at threshold=2.

**Files:** `hermes_cli/kanban_db.py`, `tests/hermes_cli/test_kanban_core_functionality.py`.
(NOTE: the kanban DB/dispatch code lives in `hermes_cli/kanban_db.py` on current
main, NOT `tools/kanban_tools.py` — an earlier version of this doc had the wrong
path. Upstream relocated the create/dispatch logic.)

**Mechanism:** pre-flight gate in `create_task` — for non-default assignees
whose profile dir exists, every `skills` entry must resolve via the worker's
skill search path (`<profile_home>/skills/`, `<profile_home>/plugins/`,
`config.yaml` `skills.external_dirs`). Adds `_skill_resolvable_for_profile(name,
hermes_home)`; legacy `_kanban_worker_skill_available` kept as a back-compat
shim. Defense-in-depth: `_default_spawn` drops still-unresolvable per-task
skills (gated by `HERMES_KANBAN_SKIP_SKILL_PREFLIGHT`).

**Conflict resolved this sync (2026-06-26):** upstream landed `84e1d31e5`
(#50473, "fold worker/orchestrator skills into injected guidance") which
**removed the bundled `kanban-worker` skill entirely**, promoting its content
into `KANBAN_GUIDANCE`. Collision shape:
- **`create_task`** — upstream added skill *syntax* validation (strip/dedupe,
  comma-refuse, toolset-typo detection). Our carry's profile-scoped
  *resolvability* preflight auto-merged cleanly *after* upstream's normalization
  block — complementary, not redundant: upstream normalizes the list, our gate
  checks the normalized names against the assignee profile.
- **`_default_spawn`** — the vestigial `sk == "kanban-worker"` dedup the carry
  carried is now dead (no bundled skill to dedupe against). Dropped it +
  rewrote the comment to match upstream's verbatim-passthrough world; KEPT the
  carry's distinctive `enforce` resolvability gate.
- **Tests** — adopted upstream's corrected test names/docstrings
  (`_passes_task_skills_verbatim`, "no skill auto-loaded anymore") and KEPT the
  carry's `HERMES_KANBAN_SKIP_SKILL_PREFLIGHT=1` setenv (required because the
  carry's `enforce` gate would otherwise drop the fixture's unresolvable
  skills). Dropped the now-no-op `_kanban_worker_skill_available` monkeypatch.
  The carry's dedicated resolvability tests auto-merged untouched and stay.

Classify **OVERLAPPING, not SUPERSEDED** — upstream solved a *different*
problem (skill syntax + removing the bundle); the carry's resolvability
preflight has no upstream equivalent. Smoke slice green (370 passed).

**Upstream PR housekeeping:** three open PRs exist for this same fix — #45917,
#47496, and the implicit carry. Consolidate: keep #45917 as the canonical PR,
close #47496 as a duplicate, rebuild #45917's branch on current main.

---

### 5. `feat(gateway): kanban auto-react debouncer`

**Problem:** When a kanban worker hits `blocked` / `crashed` / `gave_up` /
`timed_out`, the originating chat got a notifier ping that often went unread
for hours.

**Files:** `gateway/kanban_react.py` (new), `gateway/run.py`,
`tests/gateway/test_kanban_react.py`. (The earlier separate INFO/WARNING log
bumps are folded into this commit now.)

**Mechanism:** per-session debouncer batches terminal events, then dispatches a
synthetic `internal=True` `MessageEvent` into `_handle_message` so the session's
agent wakes up, sees the events, and decides whether to unblock / retry /
escalate / document. Synthetic-turn prompt is in `_kanban_react_flush` in
`gateway/run.py`.

**Rebase:** CLEAN this sync. No upstream auto-react / fanout mechanism found —
if one lands, this becomes SUPERSEDED.

---

### 6. `fix: retry holographic memory sqlite locks`

**Author:** `jarvis <jarvis@jarvis.gat.ink>` (JimGat) — NOT a Theo/Tem carry.
Straight cherry-pick of the head of upstream PR
[#40167](https://github.com/NousResearch/hermes-agent/pull/40167), applied
locally ahead of merge.

**Problem:** `memory_store.db` is a single SQLite file written by BOTH the
always-on gateway and any concurrent CLI/cron session (e.g. the
`daily-self-reflect` cron's headless `hermes chat` subprocess). Under writer
contention the subprocess's `fact_store` / `fact_feedback` writes fast-fail with
`database is locked` even though WAL is enabled.

**Fix:** explicit `PRAGMA busy_timeout = 60000` + connect `timeout` 10s→60s,
plus retry-on-`locked` with `rollback()` and exponential backoff (0.5·2^n, cap
5s, max 5 retries) on the two write paths. The retry counter rides through
`args` as `_lock_retry` — safe, since the action handlers consume named keys and
never splat `args`.

**Rebase:** CLEAN replay while #40167 is open. Once it merges, `git patch-id`
flags this as **DUPLICATE** and the next sync drops it. #40167 still OPEN as of
2026-06-26 (the `busy_timeout` hits on current main are all in
`hermes_cli/kanban_db.py` — a *different* kanban-specific lock fix, not the
fact-store). Still a real gap.

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
  tests/gateway/test_discord_double_dispatch.py \
  tests/agent/test_memory_provider.py \
  -q -p no:cacheprovider

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
  upstream in a different shape that patch-id won't flag (this sync: the
  kanban `--skills` carry OVERLAPPED #50473's bundle-removal that way).
- The running gateway carries stale `.pyc` until restarted. After a sync, the
  on-disk repo is new but the live gateway still runs old code until
  `systemctl --user restart hermes-gateway`. Don't self-restart mid-turn — ask Theo.
