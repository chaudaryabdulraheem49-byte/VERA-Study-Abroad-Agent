import type { NextRequest } from "next/server";

/**
 * Proxy for the FastAPI transcript-upload endpoint.
 *
 * Same reasoning as the stream proxy: the browser stays same-origin so the
 * backend URL never reaches the client. This one answers with JSON rather than
 * a stream — it parses a transcript and returns the extracted fields, for
 * callers that want the extraction without a conversational turn.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const fetchCache = "force-no-store";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const UPSTREAM_TIMEOUT_MS = 180_000;

export async function POST(request: NextRequest): Promise<Response> {
  const contentType = request.headers.get("content-type") ?? "";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  request.signal.addEventListener("abort", () => controller.abort());

  try {
    const body = await request.arrayBuffer();
    const upstream = await fetch(`${BACKEND_URL}/api/chat/upload`, {
      method: "POST",
      headers: {
        "content-type": contentType,
        accept: "application/json",
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

    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (error) {
    const aborted = (error as Error)?.name === "AbortError";
    if (aborted && request.signal.aborted) return new Response(null, { status: 499 });
    console.error("Upload proxy failed:", error);
    return Response.json(
      {
        detail: aborted
          ? "Reading that transcript took too long. Please try again."
          : "The advisor service is unavailable. Please make sure the backend is running.",
      },
      { status: aborted ? 504 : 502 },
    );
  } finally {
    clearTimeout(timeout);
  }
}
