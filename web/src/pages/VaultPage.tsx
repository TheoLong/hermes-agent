import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { CreditCard, KeyRound, MapPin, Plus, Trash2, X } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@nous-research/ui/ui/components/typography/h2";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { api } from "@/lib/api";
import type { VaultItem, VaultKind, VaultSource } from "@/lib/api";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { useModalBehavior } from "@/hooks/useModalBehavior";
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn, themedBody } from "@/lib/utils";
import { errorMessage } from "@/lib/api-error";

interface FieldSpec {
  key: string;
  label: string;
  placeholder?: string;
  secret?: boolean;
  required?: boolean;
  autoComplete?: string;
}

// Mirrors agent/vault_store.py: PAYMENT_FIELDS / ADDRESS_FIELDS / REQUIRED_FIELDS.
const FIELDS: Record<Exclude<VaultKind, "login">, FieldSpec[]> = {
  payment: [
    { key: "card_number", label: "Card number", secret: true, required: true, autoComplete: "off" },
    { key: "cardholder_name", label: "Name on card" },
    { key: "exp_month", label: "Expiry month", placeholder: "MM", required: true },
    { key: "exp_year", label: "Expiry year", placeholder: "YYYY", required: true },
    { key: "cvc", label: "CVC", secret: true, required: true, autoComplete: "off" },
    { key: "billing_postal_code", label: "Billing postal code" },
  ],
  address: [
    { key: "address_line1", label: "Address line 1", required: true },
    { key: "address_line2", label: "Address line 2" },
    { key: "city", label: "City", required: true },
    { key: "state", label: "State / region" },
    { key: "postal_code", label: "Postal code", required: true },
    { key: "country", label: "Country", required: true },
  ],
};

const KIND_ICON = { login: KeyRound, payment: CreditCard, address: MapPin } as const;
const KIND_TITLE = { login: "Logins", payment: "Cards", address: "Addresses" } as const;

function emptyForm() {
  return {
    kind: "login" as VaultKind,
    label: "",
    origin: "",
    identifierType: "email",
    identifier: "",
    password: "",
    otp: "",
    fields: {} as Record<string, string>,
  };
}

function itemSubtitle(item: VaultItem): string {
  if (item.kind === "login") {
    return [item.identifier, item.origin].filter(Boolean).join(" · ");
  }
  return item.origin ?? "";
}

export default function VaultPage() {
  const [items, setItems] = useState<VaultItem[]>([]);
  const [sources, setSources] = useState<VaultSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();

  const load = useCallback(() => {
    return Promise.all([api.getVaultItems(), api.getVaultSources()])
      .then(([i, s]) => {
        setItems(i.items);
        setSources(s.sources);
      })
      .catch((e) => showToast(`Failed to load the vault: ${errorMessage(e)}`, "error"))
      .finally(() => setLoading(false));
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  // Secrets live in component state only while the dialog is open.
  const closeModal = useCallback(() => {
    setModalOpen(false);
    setForm(emptyForm());
  }, []);
  const modalRef = useModalBehavior({ open: modalOpen, onClose: closeModal });

  useLayoutEffect(() => {
    setEnd(
      <Button
        className="uppercase"
        size="sm"
        onClick={() => setModalOpen(true)}
        prefix={<Plus className="h-4 w-4" />}
      >
        Add
      </Button>,
    );
    return () => setEnd(null);
  }, [setEnd]);

  const handleSave = async () => {
    const secret: Record<string, string> =
      form.kind === "login"
        ? {
            identifier_type: form.identifierType,
            identifier: form.identifier.trim(),
            password: form.password,
            ...(form.otp.trim() ? { otp_secret: form.otp.trim() } : {}),
          }
        : Object.fromEntries(
            Object.entries(form.fields).filter(([, v]) => v.trim() !== ""),
          );
    setSaving(true);
    try {
      await api.addVaultItem({
        kind: form.kind,
        label: form.label.trim(),
        origin: form.origin.trim() || undefined,
        secret,
      });
      showToast(`Saved: "${form.label.trim()}"`, "success");
      closeModal();
      await load();
    } catch (e) {
      showToast(`Could not save: ${errorMessage(e)}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const itemDelete = useConfirmDelete({
    onDelete: useCallback(
      async (id: string) => {
        try {
          await api.removeVaultItem(id);
          showToast("Removed", "success");
          await load();
        } catch (e) {
          showToast(`Could not remove: ${errorMessage(e)}`, "error");
          throw e;
        }
      },
      [load, showToast],
    ),
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner className="text-2xl text-primary" />
      </div>
    );
  }

  const pendingItem = items.find((i) => i.id === itemDelete.pendingId);
  const managers = sources.filter((s) => s.name !== "local" && s.installed);
  const set = (patch: Partial<ReturnType<typeof emptyForm>>) =>
    setForm((f) => ({ ...f, ...patch }));

  return (
    <div className="flex flex-col gap-6">
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={itemDelete.isOpen}
        onCancel={itemDelete.cancel}
        onConfirm={itemDelete.confirm}
        title="Remove from vault"
        description={
          pendingItem
            ? `"${pendingItem.label}" will be deleted from the vault. This cannot be undone.`
            : "This item will be deleted from the vault. This cannot be undone."
        }
        confirmLabel="Remove"
        loading={itemDelete.isDeleting}
      />

      {modalOpen && (
        <div
          ref={modalRef}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
          onClick={(e) => e.target === e.currentTarget && closeModal()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="vault-add-title"
        >
          <div className={cn(themedBody, "relative w-full max-w-lg border border-border bg-card shadow-2xl flex flex-col max-h-[90vh] overflow-y-auto")}>
            <Button
              ghost
              size="icon"
              onClick={closeModal}
              className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <X />
            </Button>
            <header className="p-5 pb-3 border-b border-border">
              <h2 id="vault-add-title" className="font-mondwest text-display text-base tracking-wider">
                Add to vault
              </h2>
            </header>

            <form
              className="p-5 grid gap-4"
              autoComplete="off"
              onSubmit={(e) => {
                e.preventDefault();
                void handleSave();
              }}
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="vault-kind">Type</Label>
                  <Select
                    id="vault-kind"
                    value={form.kind}
                    onValueChange={(v) => set({ kind: v as VaultKind, fields: {} })}
                  >
                    <SelectOption value="login">Login</SelectOption>
                    <SelectOption value="payment">Card</SelectOption>
                    <SelectOption value="address">Address</SelectOption>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="vault-label">Name</Label>
                  <Input
                    id="vault-label"
                    autoFocus
                    placeholder="e.g. Amazon"
                    value={form.label}
                    onChange={(e) => set({ label: e.target.value })}
                  />
                </div>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="vault-origin">
                  Website{form.kind === "login" ? "" : " (optional)"}
                </Label>
                <Input
                  id="vault-origin"
                  placeholder="https://www.example.com"
                  value={form.origin}
                  onChange={(e) => set({ origin: e.target.value })}
                />
              </div>

              {form.kind === "login" ? (
                <>
                  <div className="grid grid-cols-1 sm:grid-cols-[8rem_1fr] gap-4">
                    <div className="grid gap-2">
                      <Label htmlFor="vault-id-type">Sign in with</Label>
                      <Select
                        id="vault-id-type"
                        value={form.identifierType}
                        onValueChange={(v) => set({ identifierType: v })}
                      >
                        <SelectOption value="email">Email</SelectOption>
                        <SelectOption value="username">Username</SelectOption>
                        <SelectOption value="phone">Phone</SelectOption>
                      </Select>
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="vault-identifier">Account</Label>
                      <Input
                        id="vault-identifier"
                        autoComplete="off"
                        value={form.identifier}
                        onChange={(e) => set({ identifier: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="vault-password">Password</Label>
                    <Input
                      id="vault-password"
                      type="password"
                      autoComplete="new-password"
                      value={form.password}
                      onChange={(e) => set({ password: e.target.value })}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="vault-otp">Authenticator key (optional)</Label>
                    <Input
                      id="vault-otp"
                      type="password"
                      autoComplete="off"
                      placeholder="base32 secret or otpauth:// link"
                      value={form.otp}
                      onChange={(e) => set({ otp: e.target.value })}
                    />
                  </div>
                </>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {FIELDS[form.kind].map((f) => (
                    <div key={f.key} className="grid gap-2">
                      <Label htmlFor={`vault-${f.key}`}>
                        {f.label}
                        {f.required ? "" : " (optional)"}
                      </Label>
                      <Input
                        id={`vault-${f.key}`}
                        type={f.secret ? "password" : "text"}
                        autoComplete={f.autoComplete ?? "off"}
                        placeholder={f.placeholder}
                        value={form.fields[f.key] ?? ""}
                        onChange={(e) =>
                          set({ fields: { ...form.fields, [f.key]: e.target.value } })
                        }
                      />
                    </div>
                  ))}
                </div>
              )}

              <p className="text-xs text-muted-foreground">
                Saved encrypted on this machine. Hermes can fill it into a matching page,
                but nothing here ever shows the secret again.
              </p>

              <div className="flex justify-end">
                <Button
                  type="submit"
                  className="uppercase"
                  size="sm"
                  disabled={saving}
                  prefix={saving ? <Spinner /> : undefined}
                >
                  {saving ? "Saving…" : "Save"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {(["login", "payment", "address"] as const).map((kind) => {
        const rows = items.filter((i) => i.kind === kind);
        const Icon = KIND_ICON[kind];
        return (
          <div key={kind} className="flex flex-col gap-3">
            <H2 variant="sm" className="flex items-center gap-2 text-muted-foreground">
              <Icon className="h-4 w-4" />
              {KIND_TITLE[kind]} ({rows.length})
            </H2>
            {rows.length === 0 && (
              <Card>
                <CardContent className="py-6 text-center text-sm text-muted-foreground">
                  Nothing saved
                </CardContent>
              </Card>
            )}
            {rows.map((item) => (
              <Card key={item.id}>
                <CardContent className="flex items-center gap-4 py-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-sm truncate">{item.label}</span>
                      {item.backend !== "local" && <Badge tone="outline">{item.backend}</Badge>}
                      {item.has_otp && <Badge tone="outline">2FA</Badge>}
                      {item.generated && <Badge tone="outline">generated</Badge>}
                    </div>
                    <div className="text-xs text-muted-foreground truncate">
                      {itemSubtitle(item)}
                    </div>
                  </div>
                  {item.backend === "local" && (
                    <Button
                      ghost
                      size="icon"
                      title="Remove"
                      aria-label={`Remove ${item.label}`}
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
        );
      })}

      {managers.length > 0 && (
        <div className="flex flex-col gap-2">
          <H2 variant="sm" className="text-muted-foreground">Password managers</H2>
          {managers.map((s) => (
            <Card key={s.name}>
              <CardContent className="flex items-center justify-between py-3 text-sm">
                <span>{s.display_name}</span>
                <Badge tone="outline">
                  {!s.enabled ? "off" : s.unlocked ? "unlocked" : "locked"}
                </Badge>
              </CardContent>
            </Card>
          ))}
          <p className="text-xs text-muted-foreground">
            Password-manager items are listed while unlocked; edit them in the manager itself.
          </p>
        </div>
      )}
    </div>
  );
}
