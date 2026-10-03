// @vitest-environment jsdom
import { act, useEffect, useState, type ComponentType } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The page must drive exactly the Desktop's vault.* JSON-RPC contract (tui_gateway/methods_vault.py):
 * these tests assert the method names and params that reach the gateway client.
 */

type Call = { method: string; params: Record<string, unknown> };
const rpc = vi.hoisted(() => ({
  calls: [] as Call[],
  handlers: {} as Record<string, (params: Record<string, unknown>) => unknown>,
}));

vi.mock("@/hooks/useGatewayRpc", async () => {
  const { useCallback } = await import("react");
  return {
    useGatewayRpc: (profile: string) => {
      // Stable per profile, like the real hook's useCallback.
      const request = useCallback(
        async (method: string, params: Record<string, unknown> = {}) => {
          const sent = profile ? { ...params, profile } : params;
          rpc.calls.push({ method, params: sent });
          const handler = rpc.handlers[method];
          if (!handler) throw new Error(`unexpected RPC ${method}`);
          return handler(sent);
        },
        [profile],
      );
      return { state: "open", request };
    },
  };
});

let container: HTMLDivElement;
let root: Root;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function waitFor(cond: () => boolean, timeoutMs = 5000) {
  const start = Date.now();
  while (!cond()) {
    if (Date.now() - start > timeoutMs) throw new Error("waitFor: condition never became true");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  }
}

function typeInto(id: string, value: string) {
  const el = document.getElementById(id) as HTMLInputElement | null;
  if (!el) throw new Error(`#${id} not rendered`);
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function button(text: string): HTMLButtonElement {
  const b = Array.from(document.querySelectorAll("button")).find((x) => x.textContent?.trim() === text);
  if (!b) throw new Error(`button "${text}" not rendered`);
  return b as HTMLButtonElement;
}

async function submitForm() {
  await act(async () => {
    document.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

// App.tsx lazy-loads pages, so a page mounts after PageHeaderProvider's path-change layout effect.
function Deferred({ Page }: { Page: ComponentType }) {
  const [ready, setReady] = useState(false);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- test-only deferred mount
  useEffect(() => setReady(true), []);
  return ready ? <Page /> : null;
}

async function renderPage() {
  const [{ default: VaultPage }, { I18nProvider }, { PageHeaderProvider }] = await Promise.all([
    import("./VaultPage"),
    import("@/i18n"),
    import("@/contexts/PageHeaderProvider"),
  ]);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <I18nProvider>
        <MemoryRouter initialEntries={["/vault"]}>
          <PageHeaderProvider pluginTabs={[]}>
            <Deferred Page={VaultPage} />
          </PageHeaderProvider>
        </MemoryRouter>
      </I18nProvider>,
    ),
  );
}

const LOGIN = {
  id: "vault_aaa", kind: "login", label: "GitHub", origin: "https://github.com",
  created_at: "2026-10-03T00:00:00Z", identifier_type: "email", identifier: "op@example.com",
  has_otp: true, backend: "local",
};
const BW_ITEM = { ...LOGIN, id: "bw:1", label: "Bank", backend: "bitwarden", has_otp: false };
const SOURCES = [
  { name: "local", display_name: "Hermes vault", enabled: true, needs_unlock: false, unlocked: true, installed: true },
  { name: "onepassword", display_name: "1Password", enabled: false, needs_unlock: true, unlocked: false, installed: false },
  { name: "bitwarden", display_name: "Bitwarden", enabled: true, needs_unlock: true, unlocked: false, installed: true },
];

beforeEach(() => {
  rpc.calls = [];
  rpc.handlers = {
    "vault.list": () => ({ items: [LOGIN, BW_ITEM] }),
    "vault.sources": () => ({ sources: SOURCES }),
  };
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
});

describe("VaultPage", () => {
  it("lists items with kind, 2FA and date, and only local items are deletable", async () => {
    await renderPage();
    await waitFor(() => document.body.textContent?.includes("GitHub") ?? false);

    const text = document.body.textContent ?? "";
    expect(text).toContain("2 saved");
    expect(text).toContain("2FA auto");
    expect(text).toContain("Added ");
    expect(document.querySelector('[data-testid="vault-profile-scope"]')?.textContent).toContain("default");
    expect(document.querySelector('button[aria-label="Remove saved item GitHub"]')).not.toBeNull();
    expect(document.querySelector('button[aria-label="Remove saved item Bank"]')).toBeNull();
    expect(rpc.calls.map((c) => c.method).sort()).toEqual(["vault.list", "vault.sources"]);
  });

  it("adds a login through vault.add and never sends or keeps a secret anywhere else", async () => {
    rpc.handlers["vault.add"] = () => ({ id: "vault_new" });
    await renderPage();
    await waitFor(() => document.body.textContent?.includes("GitHub") ?? false);

    act(() => button("Add login").click());
    await waitFor(() => document.getElementById("vault-password") !== null);
    expect((document.getElementById("vault-password") as HTMLInputElement).type).toBe("password");
    typeInto("vault-label", "Example");
    typeInto("vault-origin", "https://example.com");
    typeInto("vault-identifier", "me@example.com");
    typeInto("vault-password", "hunter2-not-real");
    await submitForm();

    const add = rpc.calls.find((c) => c.method === "vault.add");
    expect(add?.params).toEqual({
      kind: "login",
      label: "Example",
      origin: "https://example.com",
      secret: { identifier_type: "email", identifier: "me@example.com", password: "hunter2-not-real" },
    });
    await waitFor(() => document.getElementById("vault-password") === null);
    // Only vault.add ever carried the password.
    const leaked = rpc.calls.filter((c) => c.method !== "vault.add" && JSON.stringify(c.params).includes("hunter2"));
    expect(leaked).toEqual([]);
    // Re-opening the dialog starts empty.
    act(() => button("Add login").click());
    await waitFor(() => document.getElementById("vault-password") !== null);
    expect((document.getElementById("vault-password") as HTMLInputElement).value).toBe("");
  });

  it("requires a valid origin for cards too, like the Desktop", async () => {
    rpc.handlers["vault.add"] = () => ({ id: "vault_card" });
    await renderPage();
    await waitFor(() => document.body.textContent?.includes("GitHub") ?? false);

    act(() => button("Add payment card").click());
    await waitFor(() => document.getElementById("vault-card-number") !== null);
    typeInto("vault-label", "Visa");
    typeInto("vault-card-number", "4111 1111 1111 1111");
    typeInto("vault-exp-month", "12");
    typeInto("vault-exp-year", "2031");
    typeInto("vault-cvc", "737");
    await submitForm();
    expect(document.body.textContent).toContain("Enter a valid URL like https://example.com.");
    expect(rpc.calls.some((c) => c.method === "vault.add")).toBe(false);

    typeInto("vault-origin", "https://shop.example.com");
    await submitForm();
    expect(rpc.calls.find((c) => c.method === "vault.add")?.params).toMatchObject({
      kind: "payment",
      origin: "https://shop.example.com",
      secret: { card_number: "4111111111111111", exp_month: "12", exp_year: "2031", cvc: "737" },
    });
  });

  it("removes through vault.remove after confirmation", async () => {
    rpc.handlers["vault.remove"] = () => ({ removed: true });
    await renderPage();
    await waitFor(() => document.querySelector('button[aria-label="Remove saved item GitHub"]') !== null);

    act(() => (document.querySelector('button[aria-label="Remove saved item GitHub"]') as HTMLButtonElement).click());
    await waitFor(() => document.body.textContent?.includes("will be removed") ?? false);
    await act(async () => button("Delete").click());
    await waitFor(() => rpc.calls.some((c) => c.method === "vault.remove"));
    expect(rpc.calls.find((c) => c.method === "vault.remove")?.params).toEqual({ id: "vault_aaa" });
  });

  it("unlocks a password manager with vault.unlock and clears the master password", async () => {
    rpc.handlers["vault.unlock"] = () => ({ name: "bitwarden", unlocked: true });
    await renderPage();
    await waitFor(() => document.querySelector('[data-testid="vault-source-bitwarden"]') !== null);

    expect(document.querySelector('[data-testid="vault-source-onepassword"]')?.textContent).toContain("Not detected");
    act(() => button("Unlock").click());
    await waitFor(() => document.getElementById("vault-master-password") !== null);
    typeInto("vault-master-password", "master-not-real");
    await act(async () => {
      document.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(rpc.calls.find((c) => c.method === "vault.unlock")?.params).toEqual({
      name: "bitwarden",
      password: "master-not-real",
    });
    await waitFor(() => document.getElementById("vault-master-password") === null);
  });

  it("toggles a password manager with vault.source.set", async () => {
    rpc.handlers["vault.source.set"] = (p) => ({ name: p.name, enabled: p.enabled });
    await renderPage();
    await waitFor(() => document.querySelector('[aria-label="Bitwarden"]') !== null);

    await act(async () => (document.querySelector('[aria-label="Bitwarden"]') as HTMLElement).click());
    await waitFor(() => rpc.calls.some((c) => c.method === "vault.source.set"));
    expect(rpc.calls.find((c) => c.method === "vault.source.set")?.params).toEqual({ name: "bitwarden", enabled: false });
  });
});
