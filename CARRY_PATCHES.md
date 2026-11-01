# Carry patches

Local commits carried on `consolidated-fixes` on top of `origin/main`
(NousResearch/hermes-agent). Regenerated every sync: the live stack is
`git log origin/main..HEAD`; this file is the annotation layer.

**Last synced:** 2026-10-31 (absorbed 5,354 upstream commits)
**Rollback branch:** `consolidated-fixes-old-2026-10-31` (local)
**Pre-sync snapshot:** `sync/2026-10-31-pre-upstream` (local + `fork`)

---

## Inventory

| SHA | Subject | Upstream PR | Risk class | Conflict shape |
|---|---|---|---|---|
| `5df610fbca` | docs(desktop): correct the import.meta.env.DEV claim in the perf note | none (local-only) | low | One doc file. |
| `9c78008bbb` | feat(discord): periodic thread retitle on top of upstream semantic titles | [#29983](https://github.com/NousResearch/hermes-agent/pull/29983) (open) | high | Hooks into upstream title code, which moves often. |
| `e7df59d65c` | fix(dashboard): clamp the multiplex-standalone banner to two lines with a Details toggle | none yet | low | One component. |
| `e3029450b7` | fix(launchers): never bake a caller's sandbox HOME into the shared install launcher | none yet | high | `hermes_cli/_launchers.py` store-root anchor + one test. Upstream still builds `runtime / entry / rel` (2026-10-31). |
| `dc9147d4b0` | feat(dashboard): Passwords & Logins page (Desktop vault parity over `vault.*` JSON-RPC) | branch `TheoLong:feat/dashboard-vault-page` | low | New page + hook; route/nav in `web/src/App.tsx`. Rebuild `web_dist` after every sync. |
| `1c593e2987` | feat(discord): voice channel recorder (WIP carry) | none (local-only) | medium | `/voice record` slash command, `plugins/platforms/discord/voice_recorder.py`, adapter + `gateway/run_voice.py`. ALSO carries the server (guild) ID as a Discord channel-gate key (`_discord_channel_keys_from_channel`); `discord.free_response_channels` names the home server by ID and depends on it. |
| `9dc59f7991` | feat(discord): reply fetch hint anchored on the replied-to message's channel | [#29982](https://github.com/NousResearch/hermes-agent/pull/29982) (open) | medium | `reply_to_channel_id` on `MessageEvent` (upstream has `reply_to_author_id/_name`); hint in `gateway/run_inbound.py`; `around` in `tools/discord_tool.py` incl. `_HANDLER_DEFAULTS`. |
| `34e7043388` | feat(vault): generated disposable logins and secure signup/password-change fills | none: #111816 closed unmerged | high | Re-seated 2026-10-31 on upstream's shadow-DOM walk, `fill_context`/`snapshot_refusal` and `_fill_bound_page` split. Inspection state lives in the `hermes-vault` isolated world (`_eval_js` and `_eval_js_secret` both pass `world_name`). |
| `3e62df37b7` | feat(browser): named browser profiles honored by browser_exec | [#49691](https://github.com/NousResearch/hermes-agent/pull/49691) (open) | medium | Re-implemented 2026-10-31 as `tools/browser_profiles.py` + `profile` arg in `tools/browser_use_cli.py`. The agent-browser half (browser_navigate profile arg, owned-tab pinning) was dropped: unused since 08/2026 and its modules were removed upstream. |
| (this file) | docs: CARRY_PATCHES inventory | | | |

**Dropped 2026-10-31:**
- `62bbe659da` Copilot picker list: upstream removed Copilot from core (`1da2eb42dc`); it is now the `github-copilot` labs plugin. Re-probe that plugin's list instead.
- `817ede1be4` oneshot skill-edit wording: upstream deleted the sentence it reworded (`0778f334b0`).

**Known upstream test failures (not carry regressions, 2026-10-31):** `tests/gateway/test_voice_command.py` (4), `tests/agent/test_title_generator.py::TestModelSwitchMarkerNotTitleable::test_marker_prefix_matches_gateway_constant`.

---

## Vault password lifecycle

- (part of `34e7043388`) generated local-vault credentials and isolated-world fills, adopted from [#111816](https://github.com/NousResearch/hermes-agent/pull/111816) (**closed unmerged 2026-10-02**; #111287 stages generated signups through 1Password instead and is still open). Preserve upstream attribution; reconcile against that PR on sync. It overlaps the 1Password-only staging proposal #111287 but serves the built-in encrypted vault.
- (part of `34e7043388`) explicit `signup` and `password_change` modes on `browser_vault action=fill` (`mode`, `current_handle`; upstream folded the five vault tools into one `browser_vault` tool, and the 2026-10-17 sync re-seated the carry on it), generated new credentials, optional distinct current credential bound to the same origin and identity, complete-field validation before writes, no form submission. Local extension; ordinary login and OTP protections remain. Risk: high, touches the classifier and supervised secret-fill boundary.
- Gates: `scripts/run_tests.sh tests/tools/test_vault_password_change.py tests/tools/test_browser_vault.py tests/hermes_cli/test_vault_generate_login.py tests/agent/test_vault_backends.py` (67 passed); `HERMES_E2E_BROWSER=1 scripts/run_tests.sh -m integration tests/tools/test_vault_password_change_e2e.py` (38 real Chromium cases passed). The dispatch regression fails on `0e0d6f2c629` with one field filled instead of three.
- (part of `34e7043388`) supports single unambiguous password sets in form-less SPAs and controlled inputs that reset sibling values during callbacks. Retained targets are revalidated before each event-driven rewrite. A late callback mutation produces an explicit partial-state warning, never a false claim that nothing was written. Verified against synthetic controls and a real password change followed by successful login.
- `fix(vault): preserve explicit direct browser credential entry` — keeps Vault autofill available and preferred for saved secrets, but removes model instructions that made it mandatory. When the user explicitly provides or shows a password, payment detail, CVC, or verification code and asks Hermes to enter it on the current page, the browser input tools may comply. Hermes still must not guess, unnecessarily solicit, or repeat credentials.
- Fresh runtimes load these operations. An already-running gateway retains its imported tool modules until reloaded; do not confuse on-disk installation with gateway activation.

## Notes per patch

### `9dc59f7991` — reply fetch hint
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

### `9c78008bbb` — periodic retitle
Upstream owns first-turn semantic titling; this is the periodic half it
still lacks — re-evaluates the title against the whole condensed
conversation every few turns and renames only on genuine topic drift.
Guarded by `_looks_like_title()` (rejects prose the model returns when it
answers the prompt conversationally instead of emitting a title).

### `3e62df37b7` — named browser profiles (+ browser_exec)

Per-call `profile=` routing to `browser.profiles` endpoints. Live-verified:
no `profile=` lands on Tem's profile (the default), `profile="theo"` lands on
Theo's, and an unknown name is refused with the configured-profiles list rather
than silently falling back. Upstream's `real_profile_pin` is a different feature
(global, config-time, single identity) and does not supersede it.

**2026-10-17 reshape:** upstream added `force_local_sidecar`/`real_profile` and a `_route_exec` wrapper; `profile` is now a keyword passed through `_route_exec` into `_route_backend`, still short-circuiting every other route.

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
| `fix(codex): coalesce pending Responses calls by call_id` (`140070f6e64`) | DUPLICATE/landed. Upstream merged the same alias coalescing via #135285 (`d687605c7b6`, #94708's commit with authorship). External guard `~/.hermes/scripts/check-responses-dedup.py` keeps running against upstream's code. Recoverable from `sync/2026-10-17-pre-upstream`. |
| 10 `docs:` commits editing this file | Regenerated once from the final branch; never cherry-picked. |

**Known test-env artifact:** with the checkout at `~/.hermes/hermes-agent`, upstream's `tests/home_io_guard.py` trips on `pm/environments.py` probing `<checkout>/../manifest.json` (= the real `~/.hermes/manifest.json`). Affects `test_title_generator.py::test_marker_prefix_matches_gateway_constant` and `test_browser_extension_router_wiring.py::test_every_browser_registry_handler_routes_through_wrapper`. Both pass from a `/tmp` worktree of the same HEAD; not a carry regression.

---

## Deferred (not in the live stack)

None. The browser-profiles feature that sat here was rebased and shipped this
sync as `3e62df37b7` — see the Inventory.


---

## Conventions

- Every carry is offered upstream as a focused PR; it stays local until the
  PR merges (drops as DUPLICATE on patch-id) or is rejected.
- A carry adopted from someone else's PR keeps their authorship and records
  the drop condition in the commit body.
- SHAs change on every rebase — reconcile this file against
  `git log origin/main..HEAD` before trusting it.
