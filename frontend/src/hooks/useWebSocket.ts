import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getAccessToken, SESSION_EXPIRED_EVENT } from "@/api/tokenStore";

export type WebSocketStatus = "idle" | "connecting" | "open" | "closed";

export interface WebSocketEvent {
  type: "event";
  topic: string;
  event: string;
  data: Record<string, unknown>;
  ts: string;
}

type Envelope =
  | WebSocketEvent
  | { type: "ready"; topics: string[]; available_topics: string[]; server_time: string }
  | { type: "subscribed"; topics: string[] }
  | { type: "pong"; ts: string }
  | { type: "error"; code: string; message: string };

const MAX_BACKOFF_MS = 30_000;
const PING_INTERVAL_MS = 25_000;

function wsBaseUrl(): string {
  const configured = (import.meta.env.VITE_WS_BASE_URL ?? "").trim();
  if (configured) return configured.replace(/\/$/, "");
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
}

export interface UseWebSocketOptions {
  enabled?: boolean;
  onEvent?: (event: WebSocketEvent) => void;
  onStatusChange?: (status: WebSocketStatus) => void;
}

export interface UseWebSocketResult {
  status: WebSocketStatus;
  connected: boolean;
  subscribe: (topics: string[]) => void;
  unsubscribe: (topics: string[]) => void;
}

/**
 * Maintains one authenticated WebSocket with exponential-backoff reconnection.
 *
 * The server accepts `?token=` as either a JWT or an API key and pushes
 * `{"type":"event",...}` frames for every subscribed topic.
 */
export function useWebSocket(topics: string[], options: UseWebSocketOptions = {}): UseWebSocketResult {
  const { enabled = true, onEvent, onStatusChange } = options;
  const [status, setStatus] = useState<WebSocketStatus>("idle");

  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const pingTimerRef = useRef<number | null>(null);
  const closedByUserRef = useRef(false);
  const topicKey = useMemo(() => [...new Set(topics)].sort().join(","), [topics]);
  const topicsRef = useRef<string[]>(topics);
  const onEventRef = useRef(onEvent);
  const onStatusRef = useRef(onStatusChange);

  topicsRef.current = topics;
  onEventRef.current = onEvent;
  onStatusRef.current = onStatusChange;

  const updateStatus = useCallback((next: WebSocketStatus) => {
    setStatus(next);
    onStatusRef.current?.(next);
  }, []);

  const send = useCallback((payload: unknown) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }
  }, []);

  const subscribe = useCallback(
    (next: string[]) => send({ action: "subscribe", topics: next }),
    [send],
  );
  const unsubscribe = useCallback(
    (next: string[]) => send({ action: "unsubscribe", topics: next }),
    [send],
  );

  useEffect(() => {
    if (!enabled) {
      updateStatus("idle");
      return undefined;
    }

    closedByUserRef.current = false;

    const clearTimers = () => {
      if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
      if (pingTimerRef.current) window.clearInterval(pingTimerRef.current);
      reconnectTimerRef.current = null;
      pingTimerRef.current = null;
    };

    const connect = () => {
      const token = getAccessToken();
      if (!token) {
        updateStatus("closed");
        return;
      }
      clearTimers();
      updateStatus("connecting");

      const url = `${wsBaseUrl()}/ws?token=${encodeURIComponent(token)}`;
      let socket: WebSocket;
      try {
        socket = new WebSocket(url);
      } catch {
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        retryRef.current = 0;
        updateStatus("open");
        if (topicsRef.current.length) send({ action: "subscribe", topics: topicsRef.current });
        pingTimerRef.current = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) send({ action: "ping" });
        }, PING_INTERVAL_MS);
      };

      socket.onmessage = (message) => {
        let frame: Envelope;
        try {
          frame = JSON.parse(String(message.data)) as Envelope;
        } catch {
          return;
        }
        if (frame.type === "event") {
          onEventRef.current?.(frame);
        } else if (frame.type === "error" && frame.code === "unauthenticated") {
          closedByUserRef.current = true;
          socket.close(4401, "unauthenticated");
        }
      };

      socket.onerror = () => {
        /* the close handler owns reconnection */
      };

      socket.onclose = (event) => {
        if (socketRef.current === socket) socketRef.current = null;
        if (pingTimerRef.current) window.clearInterval(pingTimerRef.current);
        pingTimerRef.current = null;
        if (closedByUserRef.current || event.code === 4401) {
          updateStatus("closed");
          return;
        }
        updateStatus("closed");
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (closedByUserRef.current) return;
      const attempt = retryRef.current;
      retryRef.current = Math.min(attempt + 1, 8);
      const delay = Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS);
      reconnectTimerRef.current = window.setTimeout(connect, delay);
    };

    connect();

    const handleExpiry = () => {
      closedByUserRef.current = true;
      socketRef.current?.close(4401, "session expired");
      updateStatus("closed");
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, handleExpiry);

    return () => {
      closedByUserRef.current = true;
      window.removeEventListener(SESSION_EXPIRED_EVENT, handleExpiry);
      clearTimers();
      socketRef.current?.close(1000, "component unmounted");
      socketRef.current = null;
    };
  }, [enabled, updateStatus, send, topicKey]);

  // Re-subscribe when the topic list changes while connected.
  useEffect(() => {
    if (status === "open" && topicsRef.current.length) {
      send({ action: "subscribe", topics: topicsRef.current });
    }
  }, [status, topicKey, send]);

  return { status, connected: status === "open", subscribe, unsubscribe };
}
