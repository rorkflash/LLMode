// ---------------------------------------------------------------------------
// useMetrics — React hook that subscribes to the daemon's live metrics WS.
//
// Opens a WebSocket to /api/events, keeps the latest snapshot in state, and
// auto-reconnects on disconnect. Cleans up on unmount.
// ---------------------------------------------------------------------------
import { useEffect, useRef, useState } from "react";
import { eventsWsUrl } from "../api/client";
import type { MetricsSnapshot } from "../api/types";

/**
 * Subscribe to live metrics.
 * @returns the most recent {@link MetricsSnapshot}, or null before the first frame.
 */
export function useMetrics(): MetricsSnapshot | null {
  const [snapshot, setSnapshot] = useState<MetricsSnapshot | null>(null);
  // Hold the socket across renders so cleanup can close the right instance.
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false; // guards against reconnecting after unmount

    /** Open the socket and wire up handlers; reconnect on close. */
    function connect() {
      const ws = new WebSocket(eventsWsUrl());
      wsRef.current = ws;

      // Each message is a JSON metrics snapshot — parse and store it.
      ws.onmessage = (ev) => {
        try {
          setSnapshot(JSON.parse(ev.data) as MetricsSnapshot);
        } catch {
          // Ignore malformed frames rather than crashing the dashboard.
        }
      };

      // On unexpected close, retry after a short delay (unless unmounted).
      ws.onclose = () => {
        if (!closed) setTimeout(connect, 2000);
      };
    }

    connect();

    // Cleanup: stop reconnecting and close the live socket.
    return () => {
      closed = true;
      wsRef.current?.close();
    };
  }, []);

  return snapshot;
}
