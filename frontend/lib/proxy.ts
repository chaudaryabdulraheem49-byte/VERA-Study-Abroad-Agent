import type { NextRequest } from "next/server";

/**
 * Shared backend forwarder for the simple JSON proxy routes.
 *
 * The Authorization header is forwarded untouched - the backend verifies the
 * Supabase JWT itself, and re-deriving the user here would mean two places
 * that decide who someone is.
 */
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export async function forwardToBackend(request: NextRequest, path: string) {
  const target = `${BACKEND_URL}${path}${request.nextUrl.search}`;

  const headers: Record<string, string> = { accept: "application/json" };
  const authorization = request.headers.get("authorization");
  if (authorization) headers.authorization = authorization;

  const hasBody = !["GET", "HEAD", "DELETE"].includes(request.method);
  if (hasBody) {
    headers["content-type"] =
      request.headers.get("content-type") ?? "application/json";
  }

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
    });

    if (upstream.status === 204 || upstream.status === 304) {
      return new Response(null, { status: upstream.status });
    }
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (error) {
    console.error(`Proxy to ${path} failed:`, error);
    return Response.json(
      { detail: "The advisor service is unavailable." },
      { status: 502 },
    );
  }
}
