# Carry patches

Local commits carried on `consolidated-fixes` on top of `origin/main`
(NousResearch/hermes-agent). Regenerated every sync — the live stack is
`git log origin/main..HEAD`; this file is the annotation layer.

**Last synced:** 2026-10-02 (absorbed 13,196 upstream commits)
**Live stack:** runtime patches are enumerated in the Inventory below. Additional
commits maintain this inventory and correct the desktop performance note at
`apps/desktop/scripts/profile-typing-lag.md`. Documentation commits are not separate
runtime patches. `git log --oneline origin/main..HEAD` lists the complete stack.
**Rollback branch:** `consolidated-fixes-old-2026-10-02` (local only); pre-tidy stack 2026-10-03: `consolidated-fixes-pre-tidy-2026-10-03`
**Pre-sync snapshot (incl. dropped work):** `sync/2026-10-02-pre-upstream` (local + `fork`)
**Pre-rebase remote stack:** `pre-rebase-backup-2026-09-14` (on `fork` only) —
the pre-rebase originals of these carries, kept until the rebased stack is trusted.

---

## Inventory

| SHA | Subject | Upstream PR | Risk class | Conflict shape |
|---|---|---|---|---|
| `140070f6e64` | fix(codex): coalesce pending Responses calls by call_id | [#94708](https://github.com/NousResearch/hermes-agent/pull/94708) (adopted, open) | high | Responses stream assembly; drop the day #94708 merges. Health check guards it. |
| `9dbece8aef3` | chore(models): current Copilot picker list | none (local-only) | low | `hermes_cli/models_catalog_static.py`. Do not replay a stale list: re-probe the live models each sync and rewrite this one commit. |
| `cc9785e6e21` | docs(desktop): correct the import.meta.env.DEV claim in the perf note | none (local-only) | low | One doc file. |
| `e23eb798bc1` | feat(browser): named browser profiles with same-profile concurrency, honored by browser_exec | [#49691](https://github.com/NousResearch/hermes-agent/pull/49691) (open; covers the profiles half) | high | `tools/browser_tool*.py`, `browser_exec`. Most likely to conflict on sync. |
| `325ed743036` | feat(discord): reply fetch hint anchored on the replied-to message's channel | [#29982](https://github.com/NousResearch/hermes-agent/pull/29982) (open, needs refresh to this smaller shape) | medium | `reply_to_channel_id` on `MessageEvent`; Discord adapter fills it plus upstream's `reply_to_author_id/_name`; hint is a model-only suffix in `gateway/run_inbound.py`, peeled off the durable row by `strip_discord_triggering_note`; `around` param in `tools/discord_tool.py` incl. `_HANDLER_DEFAULTS`. |
| `acf08b5acab` | feat(discord): periodic thread retitle on top of upstream semantic titles | [#29983](https://github.com/NousResearch/hermes-agent/pull/29983) (open) | high | Hooks into upstream title code, which moves often. |
| `44f41182336` | feat(vault): generated disposable logins and secure signup/password-change fills | none: source PR #111816 closed unmerged 2026-10-02; upstream favours #111287 (1Password) | medium | Permanently local. `hermes_cli/vault.py`, `agent/vault_store.py`, `tools/browser_vault*.py`. |
| `03541fe9013` | fix(dashboard): clamp the multiplex-standalone banner to two lines with a Details toggle | none yet (offer when the account can open PRs) | low | One component. |
| `3f5b1125965` | fix(launchers): never bake a caller's sandbox HOME into the shared install launcher | none yet (offer when the account can open PRs) | high | `hermes_cli/_launchers.py` store-root anchor + one test. |
| `fead88e75bc` | feat(dashboard): Passwords & Logins page (Desktop vault parity over `vault.*` JSON-RPC) | branch `TheoLong:feat/dashboard-vault-page`; PR blocked, GitHub refuses CreatePullRequest for this account (2026-10-03) | low | New page + hook; route/nav in `web/src/App.tsx`. Rebuild `web_dist` after every sync. |

**Retired 2026-10-03 (Theo-approved consolidation):** `ba6686d091c` never-close-attached-CDP (+ its docstring fix `e2cbd862d0d`) dropped as no-value — the kill it targeted had another cause. Copilot refreshes `b4230f1330c`+`b2d23751119`, browser profiles `1006415f2db`+`7c6d1b7440e`, and vault `0e0d6f2c629`+`4a5d2c7626d`+`65bf99cad1a`+`ebfc37f2f21` squashed into the rows above. Reply context trimmed to what upstream still lacks; its hint no longer leaks into stored transcripts.
**Rollback:** `consolidated-fixes-pre-squash-2026-10-03` (fork).

---

## Vault password lifecycle

- (part of `44f41182336`) generated local-vault credentials and isolated-world fills, adopted from [#111816](https://github.com/NousResearch/hermes-agent/pull/111816) (**closed unmerged 2026-10-02**; #111287 stages generated signups through 1Password instead and is still open). Preserve upstream attribution; reconcile against that PR on sync. It overlaps the 1Password-only staging proposal #111287 but serves the built-in encrypted vault.
- (part of `44f41182336`) explicit `signup` and `password_change` modes on `browser_vault_fill`, generated new credentials, optional distinct current credential bound to the same origin and identity, complete-field validation before writes, no form submission. Local extension; ordinary login and OTP protections remain. Risk: high, touches the classifier and supervised secret-fill boundary.
- Gates: `scripts/run_tests.sh tests/tools/test_vault_password_change.py tests/tools/test_browser_vault.py tests/hermes_cli/test_vault_generate_login.py tests/agent/test_vault_backends.py` (67 passed); `HERMES_E2E_BROWSER=1 scripts/run_tests.sh -m integration tests/tools/test_vault_password_change_e2e.py` (38 real Chromium cases passed). The dispatch regression fails on `0e0d6f2c629` with one field filled instead of three.
- (part of `44f41182336`) supports single unambiguous password sets in form-less SPAs and controlled inputs that reset sibling values during callbacks. Retained targets are revalidated before each event-driven rewrite. A late callback mutation produces an explicit partial-state warning, never a false claim that nothing was written. Verified against synthetic controls and a real password change followed by successful login.
- `fix(vault): preserve explicit direct browser credential entry` — keeps Vault autofill available and preferred for saved secrets, but removes model instructions that made it mandatory. When the user explicitly provides or shows a password, payment detail, CVC, or verification code and asks Hermes to enter it on the current page, the browser input tools may comply. Hermes still must not guess, unnecessarily solicit, or repeat credentials.
- Fresh runtimes load these operations. An already-running gateway retains its imported tool modules until reloaded; do not confuse on-disk installation with gateway activation.

## Notes per patch

### `325ed743036` — reply fetch hint
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

### `acf08b5acab` — periodic retitle
Upstream owns first-turn semantic titling; this is the periodic half it
still lacks — re-evaluates the title against the whole condensed
conversation every few turns and renames only on genuine topic drift.
Guarded by `_looks_like_title()` (rejects prose the model returns when it
answers the prompt conversationally instead of emitting a title).

### `140070f6e64` — Responses duplicate tool call (adopted)

**⚠️ LOAD-BEARING FOR THE MODEL CHAIN — external guard, do not drop silently.**
This carry is the only thing making responses-only models usable, so it
gates which models may sit at `model.default` / `fallback_providers[]`.
Dropping it without noticing silently degrades every turn on
`gpt-6-astra`, `gpt-5.6-*`, `gpt-5.x`, `grok-4.x`, `mai-code-*`.

Because the fix and its regression test live in the SAME commit, an update
that drops the carry deletes the test too — the repo then reports green
while broken. The tripwire therefore lives **outside the repo**:

- `~/.hermes/scripts/check-responses-dedup.py` — replays a captured REAL
  `gpt-6-astra` SSE stream (`scripts/fixtures/astra_remint_stream.json`,
  item `id` re-minted across `added`/`done`) through the live assembler and
  asserts exactly ONE tool call. Exit 0 + silent when healthy; exit 1 with
  the remediation (cherry-pick found by subject, so it survives SHA rewrites) when the fix is gone.
- Cron `2edab2d539bd` ("Responses dedup carry guard"), daily 08:00,
  `no_agent` — silent unless it fails.

**Run it as the last step of any `hermes update`**, and again after the
gateway restarts. Two gotchas if you ever rewrite the guard: hand-written
synthetic frames do NOT reproduce the bug (only the real capture does), and
output items come back as a MIX of dicts and `SimpleNamespace` — the
duplicate is a namespace, so an `isinstance(o, dict)` filter drops it and
the guard passes on broken code. Verify any change in BOTH directions by
reverting the carry in the live tree (`patch -R -p1 < <(git show
$(git log -1 --format=%h --grep='coalesce pending Responses') -- agent/codex_runtime.py)`), clearing `__pycache__`,
confirming exit 1, then restoring.

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

### `e23eb798bc1` — named browser profiles (+ browser_exec)

Per-call `profile=` routing to `browser.profiles` endpoints. Live-verified:
no `profile=` lands on Tem's profile (the default), `profile="theo"` lands on
Theo's, and an unknown name is refused with the configured-profiles list rather
than silently falling back. Upstream's `real_profile_pin` is a different feature
(global, config-time, single identity) and does not supersede it.

**2026-10-02 reshape:** upstream split `_run_browser_command` into a retry loop around
`run_fenced_pair(_dispatch_browser_command)` (Bot Desktop lease fence + stale-daemon recycle) and
now always passes `--session <name> --cdp <url>`. The carry's lock + owned-tab activation moved into
a thin `_dispatch_with_profile_tab` wrapper inside that fence; `_run_raw_agent_browser` now uses the
same `--session --cdp` form so the tab it activates is the one the session daemon acts on.
`TestSameProfileCommandRouting` was re-seated on the `_dispatch_browser_command` seam (control run:
bypassing the wrapper fails it).

## Dropped this sync

| Subject | Reason |
|---|---|
| `fix(discord): restore auto-thread in free-response channels` (`acf443c2d11`) | SUPERSEDED. Upstream added an opt-in flag, `discord.free_response_auto_thread` (default `false`), checked in the same `skip_thread` line the carry edited. Replaced by setting `discord.free_response_auto_thread: true` in `config.yaml`. Recoverable from `sync/2026-10-02-pre-upstream`. |
| 10 `docs:` commits editing this file | Regenerated once from the final branch; never cherry-picked. |

**Known test-env artifact:** with the checkout at `~/.hermes/hermes-agent`, upstream's `tests/home_io_guard.py` trips on `pm/environments.py` probing `<checkout>/../manifest.json` (= the real `~/.hermes/manifest.json`). Affects `test_title_generator.py::test_marker_prefix_matches_gateway_constant` and `test_browser_extension_router_wiring.py::test_every_browser_registry_handler_routes_through_wrapper`. Both pass from a `/tmp` worktree of the same HEAD; not a carry regression.

---

## Deferred (not in the live stack)

None. The browser-profiles feature that sat here was rebased and shipped this
sync as `e23eb798bc1` — see the Inventory.


---

## Conventions

- Every carry is offered upstream as a focused PR; it stays local until the
  PR merges (drops as DUPLICATE on patch-id) or is rejected.
- A carry adopted from someone else's PR keeps their authorship and records
  the drop condition in the commit body.
- SHAs change on every rebase — reconcile this file against
  `git log origin/main..HEAD` before trusting it.
