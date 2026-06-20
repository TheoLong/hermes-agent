# Carry Patches — `consolidated-fixes`

Theo's personal patch stack on top of `origin/main` (NousResearch/hermes-agent).
Everything here is also offered upstream as a focused PR — if upstream merges it,
the patch becomes a `DUPLICATE` (detected via `git patch-id`) and is dropped
on the next sync. If upstream rejects or reshapes it, we keep the local version
and re-apply on rebase.

Workflow: `skill_view hermes-update` → triage → rebase → reapply.

Last synced: **2026-06-07** (rebased onto `e3b8b6d32`; 1,776 upstream commits absorbed)

---

## Inventory (10 commits, bottom → top)

| # | SHA prefix | Subject | Upstream PR | Risk on rebase |
|---|------------|---------|-------------|----------------|
| 1 | `c9222920a` | feat(kanban): auto-subscribe origin conversation on `kanban_create` | [#29984](https://github.com/NousResearch/hermes-agent/pull/29984) | CLEAN this sync (was OVERLAP-LIKE) |
| 2 | `77bcb956f` | feat(gateway): kanban auto-react debouncer (blocked/crashed/gave_up/timed_out) | [#29985](https://github.com/NousResearch/hermes-agent/pull/29985) | CLEAN this sync (was OVERLAP-LIKE) |
| 3 | `eb29ec998` | chore(gateway): bump kanban notifier+react log lines to INFO | (part of #29985) | CLEAN, trivial |
| 4 | `98f0fe1ae` | fix(gateway): promote kanban-react hook exception log to WARNING | (part of #29985) | CLEAN, trivial |
| 5 | `31ca8bec0` | feat(discord): enrich reply context so agents can fetch full thread | [#29982](https://github.com/NousResearch/hermes-agent/pull/29982) ⚠ author=`Tem Ray` | PLUGIN-MOVED: discord adapter migrated to `plugins/platforms/discord/adapter.py` (PR cc8e5ec2a) — git rename detection handled it automatically; verify on next sync |
| 6 | `a6845dd6b` | fix(gateway): stop VIRTUAL_ENV leaking into agent subprocesses | [#29980](https://github.com/NousResearch/hermes-agent/pull/29980) | OVERLAP-LIKE (`tools/environments/local.py` blocklist — Vercel keys added upstream same spot, additive concat resolved 2026-06-07) |
| 7 | `ec41e78f3` | fix(discord): restore auto-thread in free-response channels | [#29981](https://github.com/NousResearch/hermes-agent/pull/29981) | PLUGIN-MOVED: target now `plugins/platforms/discord/adapter.py:4806`; rename detection auto-resolved |
| 8 | `04dd0d08f` | feat(discord): auto-rename threads + periodic retitle | [#29983](https://github.com/NousResearch/hermes-agent/pull/29983) | PLUGIN-MOVED: carry uses `self.adapters.get(source.platform)` (generic registry) so plugin relocation didn't break the adapter handle |
| 9 | `123e4915d` | docs: inventory carry-patches stack with upstream PR links | (n/a) | SELF — rewrite SHAs on every rebase |
| 10 | `781868427` | fix: retry holographic memory sqlite locks (author=`jarvis`/JimGat) | [#40167](https://github.com/NousResearch/hermes-agent/pull/40167) | DUPLICATE-WHEN-MERGED — cherry-pick of the upstream PR head; `git patch-id` will drop it once #40167 lands. CLEAN replay while open (touches `plugins/memory/holographic/{store,__init__}.py` + `tests/agent/test_memory_provider.py`). |

SHAs change on every rebase. The **subject lines** are the stable identifier
for triage; use `git log origin/main..HEAD --format="%h %s"` to refresh.

### Dropped this sync (2026-06-07)

| Dropped SHA | Subject | Reason |
|-------------|---------|--------|
| `8bc51ea59` | fix(cli): honor root-level provider when model is a string | **SUPERSEDED** — upstream `hermes_cli/config.py` now has `_normalize_root_model_keys()` that runs migration gated only on `has_root`, bypassing the "auto"-truthy bug. PR #29979 effectively absorbed (different mechanism, same outcome). |

---

## Per-patch rationale & rebase notes

### ~~1. `fix(cli): honor root-level provider when model is a string`~~ (DROPPED 2026-06-07)

**Status:** SUPERSEDED by upstream `_normalize_root_model_keys()` in
`hermes_cli/config.py`. The new migration extracts root-level `provider`,
`base_url`, and `context_length` into the `model:` section whenever the
root has any of them, gated only on `has_root` — bypassing the "auto"
truthy bug entirely. Different mechanism, same outcome. Verified working
against profile configs of the short-form `model: <name>` shape.

If "Primary provider auth failed" warnings reappear in
`~/.hermes/profiles/*/logs/errors.log`, re-introduce a regression test
before re-adding any carry.

---

### 2. `feat(discord): enrich reply context so agents can fetch full thread`

**Problem:** Discord reply events delivered only the single quoted parent;
agents couldn't fetch the rest of the thread above.

**Files:** `gateway/platforms/base.py`, `gateway/platforms/discord.py`,
`gateway/run.py`, `tools/discord_tool.py`.

**Author quirk:** committed as `Tem Ray <tem@anaheim.dev>` — won't match the
upstream AUTHOR_MAP. If upstream merges #29982, they may ask for an amend to
`Theo Long <9421870+TheoLong@users.noreply.github.com>` first.

**Rebase:** expect conflicts wherever upstream touches `gateway/run.py` reply
handling (high-churn area). Watch for upstream adding their own reply-context
plumbing — if they do, this becomes SUPERSEDED.

---

### 3. `fix(gateway): stop VIRTUAL_ENV leaking into agent subprocesses`

**Problem:** Gateway running under systemd or `uv run` propagated its own
`VIRTUAL_ENV` to every agent subprocess, breaking tool resolution in user
project venvs (surprise `ModuleNotFoundError`).

**Files:** `hermes_cli/gateway.py`, `tools/environments/local.py`,
`tests/hermes_cli/test_gateway_service.py`.

**Rebase:** check `_HERMES_PROVIDER_ENV_BLOCKLIST` — if upstream extends it
(see merge-base `3034eee` which already partially addressed this), our addition
may be a DUPLICATE candidate. Run `git patch-id` check before keeping.

---

### 4. `fix(discord): restore auto-thread in free-response channels`

**Problem:** A refactor broke auto-thread creation in free-response Discord
channels — responses started landing inline.

**Files:** `gateway/platforms/discord.py`.

**Rebase:** OVERLAP-LIKE because the file is high-churn. Verify post-rebase by
sending a top-level message in a known free-response channel and confirming
a fresh thread opens.

---

### 5. `feat(discord): auto-rename threads from session titles + periodic retitle`

**Problem:** Discord threads default to the first line of the originating
message — a poor title for a multi-turn agent session.

**Files:** `agent/title_generator.py`, `gateway/run.py`.

**Wind direction:** upstream just landed `disable_topic_auto_rename` for
Telegram (PR by B0Tch1, sha `9d789f3a5`). Operators want opt-out on
unsolicited renames. If upstream wants the same on Discord before merging
#29983, add `gateway.platforms.discord.extra.disable_thread_auto_rename`
(default False) and bridge a top-level alias for consistency with Telegram.

**Related WIP (uncommitted on this branch):** `generate_retitle()` + digest
builder that retitles based on the *whole conversation arc* (opening + recent
exchanges), not just the latest message. See "Uncommitted WIP" section below.

**Rebase:** expect conflicts in `gateway/run.py`. If upstream adds
`disable_topic_auto_rename` semantics to a generic helper, our Discord path
may need to switch to consuming that helper instead of duplicating it.

---

### 6. `feat(kanban): auto-subscribe origin conversation on kanban_create`

**Problem:** Agent in a gateway session calls `kanban_create`; the originating
conversation got no notify subscription, so terminal events (done/blocked) had
nowhere to phone home until the user ran `/kanban notify-subscribe` manually.

**Files:** `tools/kanban_tools.py`, `tests/tools/test_kanban_tools.py`.

**Resolution order baked into `_auto_subscribe_origin`:**
1. Live `HERMES_SESSION_*` env vars (gateway-injected) — preferred
2. Parent task's subscriptions (worker fanout — child inherits)
3. No-op (CLI usage with no originating conversation)

DB-layer UNIQUE constraint makes the call idempotent.

**Rebase:** last sync hit a conflict in the kanban-tools test file — pure
additive (upstream added board-param tests, we added origin-subscribe tests).
Resolution = concatenate both blocks. Expect the same shape next time.

---

### 7. `feat(gateway): kanban auto-react debouncer`

**Problem:** When a kanban worker hits `blocked` / `crashed` / `gave_up` /
`timed_out`, the originating chat got a notifier ping that often went unread
for hours. Agents in active sessions could be reacting to these.

**Files:** `gateway/kanban_react.py` (new), `gateway/run.py`,
`tests/gateway/test_kanban_react.py`.

**Mechanism:** per-session debouncer batches terminal events, then dispatches
a synthetic `internal=True` `MessageEvent` into `_handle_message` so the
session's agent wakes up, sees the events, and decides whether to unblock /
retry / escalate / document. Synthetic-turn prompt is in
`_kanban_react_flush` in `gateway/run.py`.

**Rebase:** last sync hit a conflict in `gateway/run.py` — pure additive
(upstream added `_deliver_kanban_artifacts`, we added `_kanban_react_flush`).
Resolution = keep both methods, separated by a blank line. Expect the same
shape next time. If upstream lands its own auto-react / fanout mechanism,
this becomes SUPERSEDED.

---

### 8 & 9. `chore(gateway): bump …INFO` + `fix(gateway): promote …WARNING`

Operational visibility for the kanban-react path. Always clean replay.
If #29985 lands upstream, all three are dropped together as DUPLICATE.

---

### 10. `fix: retry holographic memory sqlite locks`

**Author:** `jarvis <jarvis@jarvis.gat.ink>` (JimGat) — NOT a Theo/Tem carry.
This is a straight cherry-pick of the head of upstream PR
[#40167](https://github.com/NousResearch/hermes-agent/pull/40167), applied
locally ahead of merge.

**Problem:** the holographic memory store (`memory_store.db`) is a single
SQLite file written by BOTH the always-on gateway and any concurrent CLI/cron
session (e.g. the `daily-self-reflect` cron's headless `hermes chat`
subprocess). Under writer contention the subprocess's `fact_store` /
`fact_feedback` writes fast-fail with `database is locked` even though WAL is
enabled — the connect-`timeout` doesn't reliably translate to a writer-lock
wait on a reused connection. Surfaced during the 2026-06-20 self-reflect cron
timeout investigation: the subprocess could read but every fact_store removal
hit `{"error": "database is locked"}` while the gateway held the WAL write lock.

**Fix:** explicit `PRAGMA busy_timeout = 60000` on the connection + connect
`timeout` 10s→60s, plus retry-on-`locked` with `rollback()` and exponential
backoff (0.5·2^n, cap 5s, max 5 retries) on the two write paths. The retry
counter rides through `args` as `_lock_retry` — safe, since the action handlers
consume named keys and never splat `args`.

**Rebase:** CLEAN replay while #40167 is open. Once it merges, `git patch-id`
will flag this as **DUPLICATE** and the next sync drops it — the fix simply
becomes upstream's copy. Verified locally: 3 new tests pass, full memory
provider + holographic suite 144 passed / 0 failed.

---

## Uncommitted WIP

`agent/title_generator.py` + `hermes_cli/models.py` + `tests/agent/test_title_generator.py`
carry an in-progress extension: `generate_retitle()` builds a digest of the
opening exchange + most recent exchanges (cap ~4KB) and asks the aux model to
reassess the overall arc rather than just describe the latest message. Hooks
into the periodic-retitle path from patch #5.

Status: not yet committed. Resolve before the next rebase — either commit on
top of `d5d5ff6a8` as a follow-up, stash, or drop.

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
# OVERLAP-LIKE. Drop SUPERSEDED + DUPLICATE.

git rebase --onto origin/main <old-merge-base> consolidated-fixes
# resolve conflicts (most have been pure-concat — keep both halves)

.venv/bin/python -m pytest \
  tests/gateway/test_kanban_react.py \
  tests/tools/test_kanban_tools.py \
  tests/agent/test_title_generator.py \
  tests/cli/test_cli_init.py \
  tests/hermes_cli/test_gateway_service.py \
  -x -q

git push fork consolidated-fixes --force-with-lease
# never push to origin
```

Then for each upstream PR (#29979…#29985), check `gh pr view <n> --json state`
and if `MERGED`, drop the matching local commit on the next rebase.

---

## Hard rules

- Never `git push origin` from this repo (origin = NousResearch, read-only for us).
- Never `git pull` plain — always triage via this doc + `hermes-update` skill.
- Working tree must be clean before rebase; stash WIP, restore after.
- Force-pushes use `--force-with-lease`, never `--force`.
- Conflict resolutions on `gateway/run.py` and the kanban test file have
  historically been pure-concat additive merges. If you ever see a *true*
  semantic conflict (same method body touched by both sides), stop and read
  both diffs end-to-end before resolving.
