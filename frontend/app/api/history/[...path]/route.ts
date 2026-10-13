import type { NextRequest } from "next/server";

/**
 * Proxy for the FastAPI chat-history endpoints.
 *
 * Same reasoning as the chat proxy: the browser stays same-origin so the
 * backend URL never reaches the client. The Authorization header is forwarded
 * untouched - the backend verifies the Supabase JWT itself, and re-deriving
 * the user here would mean two places that decide who someone is.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

async function forward(request: NextRequest, path: string[]) {
  const search = request.nextUrl.search;
  const target = `${BACKEND_URL}/api/history/${path.join("/")}${search}`;

  const headers: Record<string, string> = { accept: "application/json" };
  const authorization = request.headers.get("authorization");
  if (authorization) headers.authorization = authorization;

  const hasBody = !["GET", "HEAD", "DELETE"].includes(request.method);
  if (hasBody) headers["content-type"] = request.headers.get("content-type") ?? "application/json";

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
    });

    // 204 and friends carry no body; constructing a Response with one throws.
    if (upstream.status === 204 || upstream.status === 304) {
      return new Response(null, { status: upstream.status });
    }
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (error) {
    console.error("History proxy failed:", error);
    return Response.json(
      { detail: "The advisor service is unavailable." },
      { status: 502 },
    );
  }
}

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: Context) {
  return forward(request, (await context.params).path);
}

export async function DELETE(request: NextRequest, context: Context) {
  return forward(request, (await context.params).path);
}
