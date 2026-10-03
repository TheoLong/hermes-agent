import { useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import type { StatusResponse } from "@/lib/api";
import { useI18n } from "@/i18n";

/**
 * A multi-profile host whose gateway came up STANDALONE on a boot guard: every other
 * profile's bot is silent until `hermes gateway migrate --multiplex` runs. The backend only
 * sets `multiplex_standalone_reason` when there is something unserved (never for a
 * single-profile install), so presence == show. Dismissal is session-scoped and keyed on the
 * reason text so a different blocker re-surfaces.
 */
const STORAGE_KEY = "multiplexStandaloneBannerDismissed";

export function MultiplexStandaloneBanner({
  status,
}: {
  status: StatusResponse | null;
}) {
  const { t } = useI18n();
  const reason = status?.multiplex_standalone_reason ?? null;
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  });
  if (!reason || dismissed === reason) return null;

  const unserved = (status?.profiles ?? []).filter((p) => p !== "default");
  const template =
    t.app.multiplexStandaloneBanner ??
    "Your gateway serves only one profile. Not served: {profiles}. Why: {reason}. Fix: hermes gateway migrate --multiplex";
  const message = template
    .replace("{profiles}", unserved.length > 0 ? unserved.join(", ") : "—")
    .replace("{reason}", reason);

  const dismiss = () => {
    try {
      sessionStorage.setItem(STORAGE_KEY, reason);
    } catch {
      /* ignore */
    }
    setDismissed(reason);
  };

  return (
    <div
      role="alert"
      data-testid="multiplex-standalone-banner"
      className="flex items-start gap-2 border-b border-amber-500/40 bg-amber-500/10 px-4 py-1.5 text-xs text-amber-300"
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      {/* The reason concatenates one paragraph per unserved profile; unclamped it can
          fill a phone screen and hide the page underneath. */}
      <span
        data-testid="multiplex-standalone-banner-text"
        className={`min-w-0 flex-1 break-words ${expanded ? "max-h-[40vh] overflow-y-auto" : "line-clamp-2"}`}
      >
        {message}
      </span>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="shrink-0 underline opacity-80 hover:opacity-100"
      >
        {expanded ? "Less" : "Details"}
      </button>
      <button
        type="button"
        aria-label={t.app.dismiss ?? "Dismiss"}
        onClick={dismiss}
        className="shrink-0 opacity-70 hover:opacity-100"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
