// @vitest-environment jsdom
import { act, useEffect, useState, type ComponentType } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  getVaultItems: vi.fn(),
  getVaultSources: vi.fn(),
  addVaultItem: vi.fn(),
  removeVaultItem: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMocks }));

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

// App.tsx lazy-loads pages, so a page mounts AFTER PageHeaderProvider's path-change
// layout effect has cleared the header slot. Mount it a tick later here the same way.
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

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  vi.clearAllMocks();
});

const LOGIN = {
  id: "vault_aaa", kind: "login", label: "Amazon", origin: "https://www.amazon.com",
  created_at: "2026-10-03T00:00:00Z", identifier_type: "email", identifier: "op@example.com",
  has_otp: true, backend: "local",
};
const MANAGER_LOGIN = { ...LOGIN, id: "op:xyz", label: "Bank", backend: "onepassword", has_otp: false };

describe("VaultPage", () => {
  it("lists items by kind, shows 2FA, and offers removal only for local items", async () => {
    apiMocks.getVaultItems.mockResolvedValue({ items: [LOGIN, MANAGER_LOGIN] });
    apiMocks.getVaultSources.mockResolvedValue({ sources: [] });
    await renderPage();
    await waitFor(() => document.body.textContent?.includes("Amazon") ?? false);

    expect(document.body.textContent).toContain("Logins (2)");
    expect(document.body.textContent).toContain("op@example.com · https://www.amazon.com");
    expect(document.body.textContent).toContain("2FA");
    expect(document.querySelector('button[aria-label="Remove Amazon"]')).not.toBeNull();
    expect(document.querySelector('button[aria-label="Remove Bank"]')).toBeNull();
  });

  it("submits a login with the identifier and password in the secret payload", async () => {
    apiMocks.getVaultItems.mockResolvedValue({ items: [] });
    apiMocks.getVaultSources.mockResolvedValue({ sources: [] });
    apiMocks.addVaultItem.mockResolvedValue({ item: LOGIN });
    await renderPage();
    await waitFor(() => document.body.textContent?.includes("Logins (0)") ?? false);

    await waitFor(() => Array.from(document.querySelectorAll("button")).some((b) => b.textContent?.trim() === "Add"));
    const add = Array.from(document.querySelectorAll("button")).find((b) => b.textContent?.trim() === "Add");
    act(() => add!.click());
    await waitFor(() => document.getElementById("vault-password") !== null);
    expect((document.getElementById("vault-password") as HTMLInputElement).type).toBe("password");

    typeInto("vault-label", "Amazon");
    typeInto("vault-origin", "https://www.amazon.com");
    typeInto("vault-identifier", "op@example.com");
    typeInto("vault-password", "hunter2-not-real");
    const form = document.querySelector("form")!;
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(apiMocks.addVaultItem).toHaveBeenCalledWith({
      kind: "login",
      label: "Amazon",
      origin: "https://www.amazon.com",
      secret: { identifier_type: "email", identifier: "op@example.com", password: "hunter2-not-real" },
    });
    await waitFor(() => document.getElementById("vault-password") === null);
  });
});
