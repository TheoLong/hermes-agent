# Carry patches

Local commits carried on `consolidated-fixes` on top of `origin/main`
(NousResearch/hermes-agent). Regenerated every sync — the live stack is
`git log origin/main..HEAD`; this file is the annotation layer.

**Last synced:** 2026-09-13 (absorbed ~7,097 upstream commits)
**Live stack:** 5 commits
**Rollback branch:** `consolidated-fixes-old-2026-09-13`
**Pre-sync snapshot (incl. dropped work):** `sync/2026-09-13-pre-upstream`

---

## Inventory

| SHA | Subject | Upstream PR | Risk class | Conflict shape |
|---|---|---|---|---|
| `acf443c2d11` | fix(discord): restore auto-thread in free-response channels | [#29981](https://github.com/NousResearch/hermes-agent/pull/29981) (open) | medium | Single-line revert inside a churn-heavy block. Upstream keeps `skip_thread = … or is_free_channel`; we drop the `or`. Re-resolve by keeping upstream's `_extra_or_env_flag` helper and deleting only that clause. |
| `2106bb1c7fc` | feat(discord): enrich reply context so agents can fetch full thread | [#29982](https://github.com/NousResearch/hermes-agent/pull/29982) (open) | high | 4 files; the reply-prefix builder keeps relocating (now `gateway/run_inbound.py`) and `MessageEvent` moved to `gateway/platforms/event.py`. Keep the carry **additive** — upstream's pointer line byte-identical, hint appended as a second line — or `test_reply_to_injection.py` fails. |
| `7ef48b11ce3` | feat(discord): periodic thread retitle on top of upstream semantic titles | [#29983](https://github.com/NousResearch/hermes-agent/pull/29983) (open) | high | Turn-end call site now lives in `gateway/run_turn_runner.py` (`_finalize_turn_result`), not `gateway/run.py`. Needs `final_response` + full history, so it cannot move to upstream's turn-START auto-title site. Callback is `agent._on_session_title(title, title_source)` — wrap in a 1-arg shim passing `"llm"`. Session DB is `self._runner._session_db`. |
| `7c21daefcb9` | fix(codex): coalesce pending Responses calls by call_id | [#94708](https://github.com/NousResearch/hermes-agent/pull/94708) (open, VictorYXL) | medium | **Adopted from upstream** — drop once #94708 merges. Ported onto the refactored `_CodexResponseAssembler`. |
| `fa1d62911a6` | chore(models): refresh the Copilot picker list against live probes | none (local-only) | low | Curated list moved to `hermes_cli/models_catalog_static.py`. Re-probe rather than replaying the diff — the callable set drifts. |

---

## Notes per patch

### `acf443c2d11` — free-response auto-thread
Theo runs `free_response_channels='*'` and wants every message in its own
thread for conversation isolation. Upstream suppresses auto-thread on
free-response channels. Test cascade to expect: upstream's
`test_discord_free_response_channel_skips_auto_thread` enforces the
suppression; the carry flips it to `_auto_threads` and the `chat_type`
assertion follows (`"group"` → `"thread"`).

### `2106bb1c7fc` — enrich reply context
Gives the agent the replied-to message's `channel_id` + author and an
explicit `discord(action='fetch_messages', around=…)` hint so it can pull
surrounding context. Three insertion points, all of which have moved at
least once:
- `gateway/platforms/event.py` — `reply_to_channel_id` / `reply_to_author` on `MessageEvent`.
- `plugins/platforms/discord/adapter.py` — populate both from `message.reference`.
- `gateway/run_inbound.py` — append the fetch hint after upstream's pointer line.
- `tools/discord_tool.py` — the `around` param, its schema property, **and `_HANDLER_DEFAULTS`**.

**`_HANDLER_DEFAULTS` is the easy miss.** It gates which params reach the
handler; omitting `around` there makes the whole carry a silent no-op with
every other piece correctly in place.

### `7ef48b11ce3` — periodic retitle
Upstream owns first-turn semantic titling; this is the periodic half it
still lacks — re-evaluates the title against the whole condensed
conversation every few turns and renames only on genuine topic drift.
Guarded by `_looks_like_title()` (rejects prose the model returns when it
answers the prompt conversationally instead of emitting a title).

### `7c21daefcb9` — Responses duplicate tool call (adopted)
Fixes [#94707](https://github.com/NousResearch/hermes-agent/issues/94707).
GitHub's Responses surface re-mints the opaque item `id` between
`output_item.added` and `output_item.done` while keeping `call_id` stable;
clearing pendings by item id alone left the announced entry behind, so
`response.completed` settled it again with empty `{}` arguments. The
duplicate executes, fails on a missing required field, and three in a row
trip the repeated-failure guardrail — the turn halts mid-task.

**Verified on 11 live Copilot Responses models** (gpt-6-astra,
gpt-5.6-sol/sol-fast/luna/terra, gpt-5.5, gpt-5.4, gpt-5.4-mini,
gpt-5.3-codex, grok-4.6, grok-4.5): all duplicated before, all clean after.
This is an **endpoint-wide** bug, not a per-model one — every
Responses-API model is affected; chat-completions models (claude-\*,
gemini-\*) are not.

One local addition beyond the PR: `result()` only invoked
`_settled_output()` when pendings survived, so with the alias fix nothing
stayed pending and the recovered announced ordering was discarded. Tracking
`resolved_aliases` and re-running the merge makes upstream's own
`test_done_aliases_preserve_announced_order_without_output_indexes` pass —
it does **not** pass on the straight port.

---

## Dropped this sync

| Subject | Reason |
|---|---|
| `docs: refresh CARRY_PATCHES inventory` (`81e4d048e73`) | Regenerated every sync; never cherry-picked. |
| Local `agent/codex_runtime.py` Responses fix + `tests/agent/test_codex_responses_remint_item_id.py` | SUPERSEDED by upstream #94708, adopted instead. Theirs also recovers the announced sequence/index from the alias, which the local patch did not. Independently diagnosed before searching the tracker — the local work was a reimplementation of an open PR. |
| Local `plugins/platforms/discord/adapter.py` auto-thread 429 handling + `tests/gateway/test_discord_auto_thread_ratelimit.py` | DROPPED at Theo's direction in favour of upstream [#76060](https://github.com/NousResearch/hermes-agent/pull/76060). Four competing open PRs on [#88653](https://github.com/NousResearch/hermes-agent/issues/88653) (#76060, #87358 wait-it-out; #96101, #103296 fail-fast) with no maintainer decision — carrying our own means forking a contested fix. Recoverable from `sync/2026-09-13-pre-upstream`. **Behaviour note:** #76060 caps its wait at 30s and returns a rate-limit notice beyond that; the observed cooldowns here were ~161s, so auto-thread will notify rather than thread on a long bucket. |

---

## Deferred (not in the live stack)

| Subject | State |
|---|---|
| `feat(browser): named browser profiles with same-profile concurrency` ([#49691](https://github.com/NousResearch/hermes-agent/pull/49691), open) | **Not rebased this sync.** Upstream split `tools/browser_tool.py` into ~10 siblings (`browser_tool_cdp/cloud/session/lifecycle/real_profile/...`), producing 7 conflicts whose carry sides are the whole pre-split file. Resolving to HEAD auto-merged the carry's helpers (`_profile_from_session_key`, `_ensure_owned_tab`, `_endpoint_lock_for`, …) but stranded them: every one is defined and never called, and `_resolve_profile_cdp` / `_get_browser_profiles` / `_DEFAULT_PROFILE` were lost entirely. The wiring lives in the regions that must take upstream's side, so this needs a deliberate port onto the new module layout (which sibling owns endpoint resolution vs. tab ownership), not a conflict resolution. Carry preserved on `consolidated-fixes-old-2026-09-13` and `sync/2026-09-13-pre-upstream`. |

---

## Conventions

- Every carry is offered upstream as a focused PR; it stays local until the
  PR merges (drops as DUPLICATE on patch-id) or is rejected.
- A carry adopted from someone else's PR keeps their authorship and records
  the drop condition in the commit body.
- SHAs change on every rebase — reconcile this file against
  `git log origin/main..HEAD` before trusting it.
