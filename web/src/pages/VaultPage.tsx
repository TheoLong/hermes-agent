import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { CreditCard, KeyRound, Lock, MapPin, Plus, ShieldCheck, Trash2, X } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Switch } from "@nous-research/ui/ui/components/switch";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { H2 } from "@nous-research/ui/ui/components/typography/h2";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useProfileScope } from "@/contexts/useProfileScope";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { useModalBehavior } from "@/hooks/useModalBehavior";
import { cn, themedBody } from "@/lib/utils";

/**
 * Passwords & Logins — the dashboard twin of the Desktop's Settings → Passwords & Logins panel
 * (apps/desktop/src/app/settings/vault-settings.tsx). Both drive the same `vault.*` JSON-RPC
 * methods (tui_gateway/methods_vault.py), so listing, validation, storage and the secret
 * contract are one implementation:
 *
 * - responses are metadata only; a saved secret is never read back into the page;
 * - typed secrets never enter React Query/state that outlives the dialog: the payload is built
 *   into a ref at submit, consumed by the request, and wiped; the form is reset on close;
 * - the master password for a password manager is handed to `vault.unlock` and dropped.
 */

const VAULT_KINDS = ["login", "payment", "address"] as const;
type VaultKind = (typeof VAULT_KINDS)[number];
type IdentifierType = "email" | "phone" | "username";
type VaultSourceName = "bitwarden" | "local" | "onepassword";

interface VaultSource {
  name: VaultSourceName;
  display_name: string;
  enabled: boolean;
  needs_unlock: boolean;
  unlocked: boolean;
  installed: boolean;
}

interface VaultItem {
  id: string;
  kind: string;
  label: string;
  origin: null | string;
  created_at: string;
  identifier?: null | string;
  identifier_type?: null | string;
  backend?: VaultSourceName;
  has_otp?: boolean;
}

const KIND_LABEL: Record<VaultKind, string> = {
  login: "Login",
  payment: "Payment card",
  address: "Address",
};
const KIND_ICON = { login: KeyRound, payment: CreditCard, address: MapPin } as const;

const EMPTY_FORM = {
  kind: "login" as VaultKind,
  label: "",
  origin: "",
  identifierType: "email" as IdentifierType,
  identifier: "",
  password: "",
  otpSecret: "",
  cardNumber: "",
  cardName: "",
  expMonth: "",
  expYear: "",
  cvc: "",
  postal: "",
  line1: "",
  line2: "",
  city: "",
  state: "",
  country: "",
};
type VaultForm = typeof EMPTY_FORM;

function isValidOrigin(value: string): boolean {
  try {
    const url = new URL(value);
    return (url.protocol === "https:" || url.protocol === "http:") && !!url.hostname;
  } catch {
    return false;
  }
}

function buildSecret(form: VaultForm): Record<string, string> {
  if (form.kind === "login") {
    // identifier_type/identifier are stored as agent-visible metadata by the vault store; only the
    // password (and authenticator key) stay in the encrypted secret payload.
    return {
      identifier_type: form.identifierType,
      identifier: form.identifier.trim(),
      password: form.password,
      ...(form.otpSecret.trim() ? { otp_secret: form.otpSecret.trim() } : {}),
    };
  }
  if (form.kind === "payment") {
    return {
      card_number: form.cardNumber.replace(/\s+/g, ""),
      cardholder_name: form.cardName.trim(),
      exp_month: form.expMonth.trim(),
      exp_year: form.expYear.trim(),
      cvc: form.cvc,
      billing_postal_code: form.postal.trim(),
    };
  }
  const secret: Record<string, string> = {
    address_line1: form.line1.trim(),
    city: form.city.trim(),
    postal_code: form.postal.trim(),
    country: form.country.trim(),
  };
  if (form.line2.trim()) secret.address_line2 = form.line2.trim();
  if (form.state.trim()) secret.state = form.state.trim();
  return secret;
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function formatCreated(iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleDateString();
}

function Field({
  id,
  label,
  optional,
  hint,
  children,
}: {
  id: string;
  label: string;
  optional?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>
        {label}
        {optional && <span className="ml-1 normal-case text-muted-foreground">(optional)</span>}
      </Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

// Keyed by profile: a profile switch remounts the panel, so open dialogs and any typed secret are
// gone by construction rather than by cleanup code (the Desktop keys its panel the same way).
export default function VaultPage() {
  const { profile } = useProfileScope();
  return <VaultPanel key={profile || "\u0000current"} />;
}

function VaultPanel() {
  const { profile, currentProfile } = useProfileScope();
  const { request } = useGatewayRpc(profile);
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();

  const [items, setItems] = useState<VaultItem[]>([]);
  const [sources, setSources] = useState<VaultSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState<VaultForm>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [unlockTarget, setUnlockTarget] = useState<VaultSource | null>(null);
  const [masterPassword, setMasterPassword] = useState("");
  const [unlockError, setUnlockError] = useState<string | null>(null);
  const [unlocking, setUnlocking] = useState(false);
  const [busySource, setBusySource] = useState<string | null>(null);
  // Secrets never become request state that outlives the call: refs the request consumes and wipes.
  const pendingSecret = useRef<Record<string, string> | null>(null);
  const pendingMasterPassword = useRef("");

  const load = useCallback(async () => {
    try {
      const [list, src] = await Promise.all([
        request<{ items: VaultItem[] }>("vault.list"),
        request<{ sources: VaultSource[] }>("vault.sources"),
      ]);
      setItems(list.items);
      setSources(src.sources);
    } catch (err) {
      showToast(`Could not load vault items: ${errorText(err)}`, "error");
    }
  }, [request, showToast]);

  useEffect(() => {
    let live = true;
    Promise.all([
      request<{ items: VaultItem[] }>("vault.list"),
      request<{ sources: VaultSource[] }>("vault.sources"),
    ])
      .then(([list, src]) => {
        if (!live) return;
        setItems(list.items);
        setSources(src.sources);
      })
      .catch((err) => live && showToast(`Could not load vault items: ${errorText(err)}`, "error"))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [request, showToast]);

  const closeAdd = useCallback(() => {
    setAddOpen(false);
    setForm(EMPTY_FORM);
    setFormError(null);
  }, []);
  const addRef = useModalBehavior({ open: addOpen, onClose: closeAdd });

  const openAdd = useCallback((kind: VaultKind = "login") => {
    setForm({ ...EMPTY_FORM, kind });
    setFormError(null);
    setAddOpen(true);
  }, []);

  const closeUnlock = useCallback(() => {
    setUnlockTarget(null);
    setMasterPassword("");
    setUnlockError(null);
  }, []);
  const unlockRef = useModalBehavior({ open: unlockTarget !== null, onClose: closeUnlock });

  useLayoutEffect(() => {
    setEnd(
      <Button className="uppercase" size="sm" onClick={() => openAdd()} prefix={<Plus className="h-4 w-4" />}>
        Add
      </Button>,
    );
    return () => setEnd(null);
  }, [openAdd, setEnd]);

  const submitAdd = async () => {
    setFormError(null);
    if (!form.label.trim()) {
      setFormError("A label is required.");
      return;
    }
    // Every kind is filled only on the origin it was saved for; a card without an origin is unfillable.
    const origin = form.origin.trim();
    if (!isValidOrigin(origin)) {
      setFormError("Enter a valid URL like https://example.com.");
      return;
    }
    if (form.kind === "login" && (!form.identifier.trim() || !form.password)) {
      setFormError("Identifier and password are required.");
      return;
    }
    pendingSecret.current = buildSecret(form);
    setSaving(true);
    try {
      const secret = pendingSecret.current;
      pendingSecret.current = null;
      await request<{ id: string }>("vault.add", {
        kind: form.kind,
        label: form.label.trim(),
        origin,
        secret,
      });
      showToast("Saved.", "success");
      closeAdd();
      await load();
    } catch (err) {
      setFormError(errorText(err));
    } finally {
      pendingSecret.current = null;
      setSaving(false);
    }
  };

  const itemDelete = useConfirmDelete({
    onDelete: useCallback(
      async (id: string) => {
        try {
          await request<{ removed: boolean }>("vault.remove", { id });
          await load();
        } catch (err) {
          showToast(`Could not delete: ${errorText(err)}`, "error");
          throw err;
        }
      },
      [load, request, showToast],
    ),
  });

  const setSourceEnabled = async (source: VaultSource, enabled: boolean) => {
    setBusySource(source.name);
    try {
      await request("vault.source.set", { name: source.name, enabled });
      await load();
    } catch (err) {
      showToast(`Could not update password manager: ${errorText(err)}`, "error");
    } finally {
      setBusySource(null);
    }
  };

  const lockSource = async (source: VaultSource) => {
    setBusySource(source.name);
    try {
      await request("vault.lock", { name: source.name });
      await load();
    } catch (err) {
      showToast(errorText(err), "error");
    } finally {
      setBusySource(null);
    }
  };

  const submitUnlock = async () => {
    if (!unlockTarget || !masterPassword) return;
    pendingMasterPassword.current = masterPassword;
    setMasterPassword("");
    setUnlockError(null);
    setUnlocking(true);
    try {
      const password = pendingMasterPassword.current;
      pendingMasterPassword.current = "";
      await request("vault.unlock", { name: unlockTarget.name, password });
      showToast(`${unlockTarget.display_name} unlocked for this session.`, "success");
      closeUnlock();
      await load();
    } catch (err) {
      setUnlockError(errorText(err));
    } finally {
      pendingMasterPassword.current = "";
      setUnlocking(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner className="text-2xl text-primary" />
      </div>
    );
  }

  const pendingItem = items.find((i) => i.id === itemDelete.pendingId);
  const externalSources = sources.filter((s) => s.needs_unlock);
  const sourceLabel = (name: string) => externalSources.find((s) => s.name === name)?.display_name ?? name;
  const set = (patch: Partial<VaultForm>) => setForm((f) => ({ ...f, ...patch }));
  const scopeName = profile || currentProfile;

  const input = (id: string, key: keyof VaultForm, opts: { secret?: boolean; placeholder?: string } = {}) => (
    <Input
      id={id}
      autoComplete={opts.secret && key === "password" ? "new-password" : "off"}
      type={opts.secret ? "password" : "text"}
      placeholder={opts.placeholder}
      value={form[key] as string}
      onChange={(e) => set({ [key]: e.target.value } as Partial<VaultForm>)}
    />
  );

  return (
    <div className="flex flex-col gap-6">
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={itemDelete.isOpen}
        onCancel={itemDelete.cancel}
        onConfirm={itemDelete.confirm}
        title="Delete this item?"
        description={`"${pendingItem?.label ?? ""}" will be removed. This cannot be undone.`}
        confirmLabel="Delete"
        loading={itemDelete.isDeleting}
      />

      {addOpen && (
        <div
          ref={addRef}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
          onClick={(e) => e.target === e.currentTarget && closeAdd()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="vault-add-title"
        >
          <div className={cn(themedBody, "relative flex max-h-[90vh] w-full max-w-lg flex-col overflow-y-auto border border-border bg-card shadow-2xl")}>
            <Button ghost size="icon" onClick={closeAdd} className="absolute right-2 top-2 text-muted-foreground hover:text-foreground" aria-label="Close">
              <X />
            </Button>
            <header className="border-b border-border p-5 pb-3">
              <h2 id="vault-add-title" className="font-mondwest text-display text-base tracking-wider">
                Add a login, card or address
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Stored encrypted on this machine. The agent never sees the password.
              </p>
            </header>
            <form
              className="grid gap-4 p-5"
              autoComplete="off"
              onSubmit={(e) => {
                e.preventDefault();
                void submitAdd();
              }}
            >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field id="vault-kind" label="Kind">
                  <Select id="vault-kind" value={form.kind} onValueChange={(v) => set({ kind: v as VaultKind })}>
                    {VAULT_KINDS.map((k) => (
                      <SelectOption key={k} value={k}>
                        {KIND_LABEL[k]}
                      </SelectOption>
                    ))}
                  </Select>
                </Field>
                <Field id="vault-label" label="Label">
                  <Input
                    id="vault-label"
                    autoFocus
                    placeholder="e.g. GitHub work account"
                    value={form.label}
                    onChange={(e) => set({ label: e.target.value })}
                  />
                </Field>
              </div>

              <Field id="vault-origin" label="Site origin">
                {input("vault-origin", "origin", {
                  placeholder: form.kind === "login" ? "https://github.com" : "https://shop.example.com",
                })}
              </Field>

              {form.kind === "login" && (
                <>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-[9rem_1fr]">
                    <Field id="vault-id-type" label="Identifier type">
                      <Select
                        id="vault-id-type"
                        value={form.identifierType}
                        onValueChange={(v) => set({ identifierType: v as IdentifierType })}
                      >
                        <SelectOption value="email">Email</SelectOption>
                        <SelectOption value="phone">Phone</SelectOption>
                        <SelectOption value="username">Username</SelectOption>
                      </Select>
                    </Field>
                    <Field id="vault-identifier" label="Identifier">
                      {input("vault-identifier", "identifier")}
                    </Field>
                  </div>
                  <Field id="vault-password" label="Password">
                    {input("vault-password", "password", { secret: true })}
                  </Field>
                  <Field
                    id="vault-otp"
                    label="Authenticator key"
                    optional
                    hint='The "setup key" the site shows when you enable 2FA. With it saved, Hermes generates the codes itself.'
                  >
                    {input("vault-otp", "otpSecret", { secret: true, placeholder: "Base32 secret or otpauth:// link" })}
                  </Field>
                </>
              )}

              {form.kind === "payment" && (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Field id="vault-card-number" label="Card number">
                    {input("vault-card-number", "cardNumber", { secret: true })}
                  </Field>
                  <Field id="vault-card-name" label="Name on card">
                    {input("vault-card-name", "cardName")}
                  </Field>
                  <Field id="vault-exp-month" label="Exp. month">
                    {input("vault-exp-month", "expMonth", { placeholder: "MM" })}
                  </Field>
                  <Field id="vault-exp-year" label="Exp. year">
                    {input("vault-exp-year", "expYear", { placeholder: "YYYY" })}
                  </Field>
                  <Field id="vault-cvc" label="CVC">
                    {input("vault-cvc", "cvc", { secret: true })}
                  </Field>
                  <Field id="vault-postal" label="Postal code">
                    {input("vault-postal", "postal")}
                  </Field>
                </div>
              )}

              {form.kind === "address" && (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <Field id="vault-line1" label="Address line 1">
                      {input("vault-line1", "line1")}
                    </Field>
                  </div>
                  <div className="sm:col-span-2">
                    <Field id="vault-line2" label="Address line 2" optional>
                      {input("vault-line2", "line2")}
                    </Field>
                  </div>
                  <Field id="vault-city" label="City">
                    {input("vault-city", "city")}
                  </Field>
                  <Field id="vault-state" label="State / region" optional>
                    {input("vault-state", "state")}
                  </Field>
                  <Field id="vault-postal" label="Postal code">
                    {input("vault-postal", "postal")}
                  </Field>
                  <Field id="vault-country" label="Country">
                    {input("vault-country", "country")}
                  </Field>
                </div>
              )}

              {formError && (
                <p role="alert" className="text-xs text-destructive">
                  {formError}
                </p>
              )}

              <div className="flex justify-end">
                <Button type="submit" className="uppercase" size="sm" disabled={saving} prefix={saving ? <Spinner /> : undefined}>
                  {saving ? "Saving…" : "Save"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {unlockTarget && (
        <div
          ref={unlockRef}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
          onClick={(e) => e.target === e.currentTarget && closeUnlock()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="vault-unlock-title"
        >
          <div className={cn(themedBody, "relative w-full max-w-md border border-border bg-card p-5 shadow-2xl")}>
            <h2 id="vault-unlock-title" className="font-mondwest text-display text-base tracking-wider">
              Unlock {unlockTarget.display_name}
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Enter your master password. It is handed to the password manager on this machine and discarded — it is
              never stored, logged, or shown to the agent.
            </p>
            <form
              className="mt-4 grid gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                void submitUnlock();
              }}
            >
              <Input
                id="vault-master-password"
                autoFocus
                autoComplete="current-password"
                disabled={unlocking}
                placeholder="Master password"
                type="password"
                value={masterPassword}
                onChange={(e) => setMasterPassword(e.target.value)}
              />
              {unlockError && (
                <p role="alert" className="text-xs text-destructive">
                  {unlockError}
                </p>
              )}
              <div className="flex justify-end gap-2">
                <Button type="button" ghost size="sm" onClick={closeUnlock}>
                  Cancel
                </Button>
                <Button type="submit" size="sm" disabled={unlocking || !masterPassword}>
                  {unlocking ? "Unlocking…" : "Unlock"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <H2 variant="sm" className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" />
            Passwords &amp; Logins
          </H2>
          {items.length > 0 && <span className="text-xs text-muted-foreground">{items.length} saved</span>}
          <Badge tone="outline" data-testid="vault-profile-scope">
            Profile: {scopeName}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          Say "log into GitHub" and the agent signs in for you. The first time it meets a sign-in page it asks you for
          the login right there; after that it just works. Passwords are encrypted on this machine and filled straight
          into the page — the model never sees them.
        </p>
        <div className="flex flex-wrap gap-2">
          {VAULT_KINDS.map((k) => {
            const Icon = KIND_ICON[k];
            return (
              <Button key={k} ghost size="sm" onClick={() => openAdd(k)} prefix={<Icon className="h-4 w-4" />}>
                Add {KIND_LABEL[k].toLowerCase()}
              </Button>
            );
          })}
        </div>
      </div>

      {items.length === 0 && (
        <Card>
          <CardContent className="py-6 text-center text-sm">
            <div className="font-medium">Nothing saved yet</div>
            <div className="mt-1 text-xs text-muted-foreground">
              You don't have to add anything here. Ask the agent to sign into a site and it will ask you for the login
              once, on the spot. Use Add if you prefer to enter one ahead of time.
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <Card key={item.id}>
            <CardContent className="flex items-center gap-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{item.label}</span>
                  <Badge tone={item.kind === "login" ? "default" : "outline"}>
                    {KIND_LABEL[item.kind as VaultKind] ?? item.kind}
                  </Badge>
                  {item.has_otp && <Badge tone="outline">2FA auto</Badge>}
                </div>
                <div className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                  {item.identifier && <span className="truncate">{item.identifier}</span>}
                  {item.origin && item.origin.replace(/^https?:\/\//, "") !== item.label && (
                    <>
                      {item.identifier && <span aria-hidden>·</span>}
                      <span className="truncate">{item.origin}</span>
                    </>
                  )}
                  <span aria-hidden>·</span>
                  <span>Added {formatCreated(item.created_at)}</span>
                </div>
              </div>
              {item.backend && item.backend !== "local" ? (
                <Badge tone="outline">{sourceLabel(item.backend)}</Badge>
              ) : (
                <Button
                  ghost
                  size="icon"
                  title="Remove saved item"
                  aria-label={`Remove saved item ${item.label}`}
                  onClick={() => itemDelete.requestDelete(item.id)}
                  className="text-muted-foreground hover:text-destructive"
                >
                  <Trash2 />
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex flex-col gap-2">
        <H2 variant="sm" className="flex items-center gap-2">
          <KeyRound className="h-4 w-4" />
          Password managers
        </H2>
        <p className="text-xs text-muted-foreground">
          Installed password managers are picked up automatically. The agent asks you to unlock one the first time it
          needs a login from it (once per session); only a session token stays in memory, and the agent never sees your
          master password or any login.
        </p>
        {externalSources.map((source) => {
          const status = !source.installed
            ? "Not detected"
            : !source.enabled
              ? "Off"
              : source.unlocked
                ? "Unlocked"
                : "Locked";
          const description = !source.installed
            ? `Not detected. Install the ${source.display_name} command-line tool and sign in to it; Hermes picks it up automatically.`
            : !source.enabled
              ? "Detected but turned off for Hermes."
              : source.unlocked
                ? "Unlocked for this session. Locks automatically after 30 minutes idle or when Hermes closes."
                : "Detected. The agent will ask you to unlock it when it needs a login, or unlock now.";
          const busy = busySource === source.name;
          return (
            <Card key={source.name} data-testid={`vault-source-${source.name}`}>
              <CardContent className="flex items-center gap-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center gap-2 text-sm">
                    <span className="font-medium">{source.display_name}</span>
                    <Badge tone={source.enabled && source.unlocked ? "default" : "outline"}>{status}</Badge>
                  </div>
                  <div className="text-xs text-muted-foreground">{description}</div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {source.enabled &&
                    source.installed &&
                    (source.unlocked ? (
                      <Button ghost size="sm" disabled={busy} onClick={() => void lockSource(source)} prefix={<Lock className="h-4 w-4" />}>
                        Lock
                      </Button>
                    ) : (
                      <Button size="sm" onClick={() => setUnlockTarget(source)} prefix={<KeyRound className="h-4 w-4" />}>
                        Unlock
                      </Button>
                    ))}
                  {source.installed &&
                    (busy ? (
                      <Spinner className="text-sm" />
                    ) : (
                      <Switch
                        aria-label={source.display_name}
                        checked={source.enabled}
                        onCheckedChange={(enabled) => void setSourceEnabled(source, enabled)}
                      />
                    ))}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
