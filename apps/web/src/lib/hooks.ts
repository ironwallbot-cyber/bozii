"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, get } from "./api";

interface UseApiResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refetch: () => void;
  setData: (value: T | null) => void;
}

/** Polling GET hook. `path === null` disables fetching. */
export function useApi<T>(path: string | null, refreshMs = 0): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [nonce, setNonce] = useState(0);

  const refetch = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    get<T>(path)
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          const status = caught instanceof ApiError ? caught.status : 0;
          if (status !== 401) {
            setError(caught instanceof Error ? caught.message : String(caught));
          } else {
            setError("unauthenticated");
          }
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path, nonce]);

  useEffect(() => {
    if (!refreshMs || !path) return;
    const timer = setInterval(refetch, refreshMs);
    return () => clearInterval(timer);
  }, [refreshMs, path, refetch]);

  return { data, error, loading, refetch, setData };
}

export interface LiveEvent {
  type?: string;
  task_id?: string;
  seq?: number;
  event_type?: string;
  message?: string;
  payload?: Record<string, unknown>;
  ts?: string;
  channels?: string[];
}

/**
 * Subscribe to the SSE stream. Falls back silently when EventSource is
 * unavailable; callers also poll, so live updates are an enhancement.
 */
export function useSSE(channels: string[], onEvent: (event: LiveEvent) => void, enabled = true) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const [connected, setConnected] = useState(false);
  const key = channels.join(",");

  useEffect(() => {
    if (!enabled || !key) return;
    const source = new EventSource(`/api/stream?channels=${encodeURIComponent(key)}`, {
      withCredentials: true,
    });
    const emit = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as LiveEvent;
        handler.current({ ...data, type: event.type || data.type });
      } catch {
        /* ignore malformed frames */
      }
    };
    const names = ["hello", "task_event", "activity"];
    names.forEach((name) => source.addEventListener(name, emit as EventListener));
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    return () => {
      names.forEach((name) => source.removeEventListener(name, emit as EventListener));
      source.close();
      setConnected(false);
    };
  }, [key, enabled]);

  return { connected };
}

/** Auth gate: verifies the session and redirects to /auth when missing. */
export function useSession(redirect: boolean) {
  const [user, setUser] = useState<{ id: string; email: string; name: string; role: string } | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;
    get<{ id: string; email: string; name: string; role: string }>("/api/auth/me")
      .then((value) => {
        if (!cancelled) {
          setUser(value);
          setChecking(false);
        }
      })
      .catch(() => {
        if (cancelled) return;
        setChecking(false);
        if (redirect && typeof window !== "undefined") {
          const returnTo = `${window.location.pathname}${window.location.search}`;
          window.location.href = `/auth?returnTo=${encodeURIComponent(returnTo)}`;
        }
      });
    return () => {
      cancelled = true;
    };
  }, [redirect]);

  return { user, checking };
}
