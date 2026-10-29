import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND = process.env.BOZII_API_URL ?? "http://127.0.0.1:8000";

/**
 * SSE proxy.
 *
 * Next.js route handlers stream response bodies, so live task events pass
 * through unchanged (a plain rewrite can buffer them). The session cookie is
 * forwarded to the API for authentication.
 */
export async function GET(request: NextRequest) {
  const { search } = new URL(request.url);
  try {
    const upstream = await fetch(`${BACKEND}/api/stream${search}`, {
      headers: {
        cookie: request.headers.get("cookie") ?? "",
        accept: "text/event-stream",
      },
      cache: "no-store",
    });

    if (!upstream.ok || !upstream.body) {
      const body = await upstream.text().catch(() => "");
      return new Response(body || "stream unavailable", {
        status: upstream.status,
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }

    return new Response(upstream.body, {
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
        "x-accel-buffering": "no",
      },
    });
  } catch {
    return new Response("event: error\ndata: {\"message\":\"backend unreachable\"}\n\n", {
      status: 200,
      headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
    });
  }
}