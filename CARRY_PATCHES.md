# Carry Patches — `consolidated-fixes`

Theo's personal patch stack on top of `origin/main` (NousResearch/hermes-agent).
Everything here is also offered upstream as a focused PR — if upstream merges it,
the patch becomes a `DUPLICATE` (detected via `git patch-id`) and is dropped
on the next sync. If upstream rejects or reshapes it, we keep the local version
and re-apply on rebase.

Workflow: `skill_view hermes-update` → triage → rebase → reapply.

Last synced: **2026-06-21** (rebased onto `8a506ed3a`; 521 upstream commits absorbed)

---

## Inventory (6 commits, bottom → top)

| # | SHA prefix | Subject | Upstream PR | Risk on rebase |
|---|------------|---------|-------------|----------------|
| 1 | `4c23430f4` | feat(discord): auto-rename threads from session titles + periodic retitle | [#29983](https://github.com/NousResearch/hermes-agent/pull/29983) | CLEAN this sync. Carry uses `self.adapters.get(source.platform)` (generic registry) so plugin relocation didn't break the adapter handle. |
| 2 | `37250f840` | fix(discord): restore auto-thread in free-response channels | [#29981](https://github.com/NousResearch/hermes-agent/pull/29981) | CLEAN this sync. Deliberate revert of upstream's free-response auto-thread suppression; target `plugins/platforms/discord/adapter.py`. |
| 3 | `c62b8dc1e` | feat(discord): enrich reply context so agents can fetch full thread | [#29982](https://github.com/NousResearch/hermes-agent/pull/29982) ⚠ author=`Tem Ray` | OVERLAPPING this sync — conflicted with upstream `ba49fb51a` (#49212, passive reply hydration) in `gateway/run.py` + `gateway/platforms/base.py`. Resolved: kept upstream's `reply_to_is_own_message` distinction + `reply_to_author_name` (signal-populated) AND our active `fetch_messages(around=)` pointer. base.py now carries all 5 reply fields (3 upstream + 2 ours). |
| 4 | `36c000a20` | fix(kanban): validate per-task --skills against assignee profile at create time | [#29985-adjacent / TODO open PR] | CLEAN this sync. Adds `_skill_resolvable_for_profile` pre-flight gate in `create_task`; touches `tools/kanban_tools.py` + `tests/tools/test_kanban_tools.py`. |
| 5 | `5ab879ae8` | feat(gateway): kanban auto-react debouncer | [#29985](https://github.com/NousResearch/hermes-agent/pull/29985) | CLEAN this sync. `gateway/kanban_react.py` (new) + `gateway/run.py` + tests. INFO/WARNING log bumps folded into this commit. If upstream lands its own auto-react/fanout, this becomes SUPERSEDED. |
| 6 | `9d8f60c89` | fix: retry holographic memory sqlite locks (author=`jarvis`/JimGat) | [#40167](https://github.com/NousResearch/hermes-agent/pull/40167) | DUPLICATE-WHEN-MERGED — cherry-pick of the upstream PR head; `git patch-id` will drop it once #40167 lands. CLEAN replay while open (touches `plugins/memory/holographic/{store,__init__}.py` + `tests/agent/test_memory_provider.py`). No upstream sqlite-lock activity this sync; still a real gap. |

SHAs change on every rebase. The **subject lines** are the stable identifier
for triage; use `git log origin/main..HEAD --format="%h %s"` to refresh.

### Dropped this sync (2026-06-21)

| Dropped subject | Reason |
|-----------------|--------|
| `feat(kanban): auto-subscribe origin conversation on kanban_create` | **SUPERSEDED** by upstream `f8d8f045f` (flooryyyy, "feat(kanban): auto-subscribe calling session on kanban_create"). Upstream's version is strictly more complete: adds TUI/desktop (`HERMES_SESSION_KEY`) support, a `kanban.auto_subscribe_on_create` config gate (default True) that resolves the over-eager concern which got the earlier #19718 reverted, and a `subscribed` bool in the kanban_create response. **Gap retained:** our carry's *parent-task subscription inheritance* (worker fan-out — child cards inherit parent's notify subs so the origin thread manages the whole subtree) has no upstream equivalent. Re-offer that delta as a small follow-up PR on top of `f8d8f045f`, and close our PR #29984 as superseded. |

### Dropped previous syncs (historical)

| Dropped subject | Reason |
|-----------------|--------|
| `fix(gateway): stop VIRTUAL_ENV leaking into agent subprocesses` (#29980) | **SUPERSEDED** — upstream now has a full `_HERMES_PROVIDER_ENV_BLOCKLIST` system in `tools/environments/local.py` (`_build_provider_env_blocklist()`, security advisory GHSA-rhgp-j443-p4rf) that subsumes the carry. Already absent from the live stack before the 2026-06-21 sync. |
| `fix(cli): honor root-level provider when model is a string` (#29979) | **SUPERSEDED** (2026-06-07) — upstream `_normalize_root_model_keys()` in `hermes_cli/config.py` extracts root-level provider/base_url/context_length gated on `has_root`, bypassing the "auto"-truthy bug. |

---

## Per-patch rationale & rebase notes

### 1. `feat(discord): auto-rename threads from session titles + periodic retitle`

**Problem:** Discord threads default to the first line of the originating
message — a poor title for a multi-turn agent session.

**Files:** `agent/title_generator.py`, `gateway/run.py`.

**Wind direction (2026-06-21):** upstream is *refining* rename behavior
(`38f1a923a` "rename the Telegram topic from /title, not only auto-titles"),
NOT adding a disable flag. No opt-out needed on #29983 yet. If upstream adds
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

**Rebase:** CLEAN this sync (cherry-pick applied with no conflict). Upstream's
`tests/gateway/test_discord_free_response.py` was checked — its current
assertions (`test_discord_free_response_in_server_channels` →
`assert_awaited_once()`) are consistent with our restored behavior, so no test
cascade fired this sync. Verify post-restart by sending a top-level message in
a known free-response channel and confirming a fresh thread opens.

---

### 3. `feat(discord): enrich reply context so agents can fetch full thread`

**Problem:** Discord reply events delivered only the single quoted parent;
agents couldn't fetch the rest of the thread above.

**Files:** `gateway/platforms/base.py`, `gateway/run.py`,
`plugins/platforms/discord/adapter.py`, `tools/discord_tool.py`.

**Author quirk:** committed as `Tem Ray <tem@anaheim.dev>` — won't match the
upstream AUTHOR_MAP. If upstream merges #29982, they may ask for an amend to
`Theo Long <9421870+TheoLong@users.noreply.github.com>` first.

**Conflict resolved this sync (2026-06-21):** upstream landed `ba49fb51a`
(#49212, "hydrate channel context when replying to a message") — *passive*
reply hydration that collides with our carry in `base.py` (reply dataclass
fields) and `run.py` (reply-decoration block). Resolution:
- **base.py** — kept ALL 5 reply fields. Upstream's `reply_to_author_id`,
  `reply_to_author_name`, `reply_to_is_own_message` are cross-platform
  (signal.py populates them, run.py reads `reply_to_is_own_message`); our
  `reply_to_channel_id`, `reply_to_author` are Discord-populated. Complementary,
  not redundant.
- **run.py** — merged both decoration paths: upstream's own-message branch
  (`[Replying to your previous message …]`) AND our active `fetch_messages`
  pointer + truncation note. `author` falls back from `reply_to_author` to
  `reply_to_author_name` so the pointer works on both Discord and signal.

The distinctive carry capability — `discord(action='fetch_messages',
around=<msg_id>)` for *active* context pull — has no upstream equivalent, so
this stays OVERLAPPING (keep), not SUPERSEDED.

---

### 4. `fix(kanban): validate per-task --skills against assignee profile at create time`

**Problem:** `kanban create --skill <name>` accepted skills installed only
under the default root HERMES_HOME but not under the target assignee profile.
The spawned worker crashed at CLI startup with `ValueError: Unknown skill(s)`,
the dispatcher recorded `pid <N> not alive`, `consecutive_failures` incremented,
and the circuit breaker auto-blocked the task at threshold=2.

**Files:** `tools/kanban_tools.py`, `tests/tools/test_kanban_tools.py`.

**Mechanism:** pre-flight gate in `create_task` — for non-default assignees
whose profile dir exists, every `skills` entry must resolve via the worker's
skill search path (`<profile_home>/skills/`, `<profile_home>/plugins/`,
`config.yaml` `skills.external_dirs`). Generalizes
`_kanban_worker_skill_available` into `_skill_resolvable_for_profile(name,
hermes_home)` (legacy fn kept as a back-compat shim).

**Rebase:** CLEAN this sync. No upstream activity on kanban skill validation.
**TODO:** not yet offered upstream as its own PR — open one.

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
`database is locked` even though WAL is enabled — the connect-`timeout` doesn't
reliably translate to a writer-lock wait on a reused connection.

**Fix:** explicit `PRAGMA busy_timeout = 60000` + connect `timeout` 10s→60s,
plus retry-on-`locked` with `rollback()` and exponential backoff (0.5·2^n, cap
5s, max 5 retries) on the two write paths. The retry counter rides through
`args` as `_lock_retry` — safe, since the action handlers consume named keys and
never splat `args`.

**Rebase:** CLEAN replay while #40167 is open. Once it merges, `git patch-id`
flags this as **DUPLICATE** and the next sync drops it. No upstream sqlite-lock
activity this sync — still a real gap.

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
# upstream log per-subsystem for RESHAPED supersessions (this sync caught
# the kanban auto-subscribe supersession that way; patch-id missed it).

# fresh branch at upstream HEAD, cherry-pick surviving carries one at a time
git checkout -B consolidated-fixes-new origin/main
git cherry-pick <sha> ...   # resolve conflicts per-commit

.venv/bin/python -m pytest \
  tests/gateway/test_kanban_react.py \
  tests/tools/test_kanban_tools.py \
  tests/agent/test_title_generator.py \
  tests/gateway/test_discord_free_response.py \
  tests/agent/test_memory_provider.py \
  -q -p no:cacheprovider

# branch swap (date-suffix old for rollback) + push
git branch -m consolidated-fixes consolidated-fixes-old-$(date +%Y-%m-%d)
git branch -m consolidated-fixes-new consolidated-fixes
git push fork consolidated-fixes --force-with-lease
# never push to origin
```

Then for each upstream PR (#29981…#29985, #40167), check
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
  supersessions — a feature can merge upstream in a different shape that
  patch-id won't flag.
- The running gateway carries stale `.pyc` until restarted. After a sync, the
  on-disk repo is new but the live gateway still runs old code until
  `systemctl --user restart hermes-gateway`. Don't self-restart mid-turn — ask Theo.
