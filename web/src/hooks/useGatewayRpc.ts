import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GatewayClient, type ConnectionState } from "@/lib/gatewayClient";

/**
 * A JSON-RPC client on the dashboard's `/api/ws` sidecar for management pages that drive the same
 * `tui_gateway` methods the Desktop's Settings panels use — one backend contract, no REST copy.
 *
 * The client lives for the component; `request` waits for the socket to open, and every call carries
 * the page's profile so the handler binds that profile's home and secret scope (`_profile_scoped`).
 */
export function useGatewayRpc(profile: string) {
  const gw = useMemo(() => new GatewayClient(), []);
  const [state, setState] = useState<ConnectionState>(gw.connectionState);
  const opening = useRef<Promise<void> | null>(null);

  useEffect(() => {
    const off = gw.onState(setState);
    return () => {
      off();
      gw.close();
    };
  }, [gw]);

  const ensureOpen = useCallback(() => {
    if (gw.connectionState === "open") return Promise.resolve();
    if (!opening.current) {
      opening.current = gw.connect().finally(() => {
        opening.current = null;
      });
    }
    return opening.current;
  }, [gw]);

  const request = useCallback(
    async <T,>(method: string, params: Record<string, unknown> = {}): Promise<T> => {
      await ensureOpen();
      return gw.request<T>(method, profile ? { ...params, profile } : params);
    },
    [ensureOpen, gw, profile],
  );

  return { request, state };
}
