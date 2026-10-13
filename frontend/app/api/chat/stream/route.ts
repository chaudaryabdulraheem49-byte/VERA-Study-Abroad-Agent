import type { NextRequest } from "next/server";

/**
 * Proxy for the FastAPI SSE endpoint.
 *
 * Keeping the browser on a same-origin route means the backend URL and any
 * future auth header never reach the client. The upstream body is piped
 * through untouched so tokens still arrive incrementally.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// The upstream stream must not be buffered or revalidated by the Next cache.
export const fetchCache = "force-no-store";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const UPSTREAM_TIMEOUT_MS = 180_000;

export async function POST(request: NextRequest): Promise<Response> {
  const contentType = request.headers.get("content-type") ?? "application/json";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);

  // Abort upstream as soon as the browser disconnects, so a closed tab does not
  // leave an OCR call running.
  request.signal.addEventListener("abort", () => controller.abort());

  try {
    // The body is read into memory rather than streamed: uploads are capped at
    // 10 MB and this avoids the half-duplex streaming caveats in undici.
    const body = await request.arrayBuffer();

    const upstream = await fetch(`${BACKEND_URL}/api/chat/stream`, {
      method: "POST",
      headers: {
        "content-type": contentType,
        accept: "text/event-stream",
        // Forwarded untouched: the backend verifies the Supabase JWT itself.
        // Re-deriving the user here would mean two places deciding who
        // someone is, which is one too many.
        ...(request.headers.get("authorization")
          ? { authorization: request.headers.get("authorization")! }
          : {}),
      },
      body,
      signal: controller.signal,
      cache: "no-store",
    });

    if (!upstream.ok || !upstream.body) {
      const detail = await upstream.text();
      return new Response(detail || JSON.stringify({ detail: "Upstream error." }), {
        status: upstream.status,
        headers: {
          "content-type": upstream.headers.get("content-type") ?? "application/json",
        },
      });
    }

    return new Response(upstream.body, {
      status: 200,
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
        "x-accel-buffering": "no",
      },
    });
  } catch (error) {
    const aborted = (error as Error)?.name === "AbortError";
    if (aborted && request.signal.aborted) {
      // The client went away; nothing left to respond to.
      return new Response(null, { status: 499 });
    }
    console.error("Chat proxy failed:", error);
    return Response.json(
      {
        detail: aborted
          ? "The advisor took too long to respond. Please try again."
          : "The advisor service is unavailable. Please make sure the backend is running.",
      },
      { status: aborted ? 504 : 502 },
    );
  } finally {
    clearTimeout(timeout);
  }
}
