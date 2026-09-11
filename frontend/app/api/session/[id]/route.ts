import type { NextRequest } from "next/server";

/**
 * Session proxy: lets a reopened tab restore the conversation it is about to
 * continue, and lets the user abandon it outright.
 *
 * Without this, a new tab starts with an empty UI but keeps the stored session
 * id, so the backend answers from a conversation the student cannot see.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

async function forward(id: string, method: "GET" | "DELETE"): Promise<Response> {
  const target = `${BACKEND_URL}/api/session/${encodeURIComponent(id)}`;
  try {
    const upstream = await fetch(target, { method, cache: "no-store" });
    if (method === "DELETE" || upstream.status === 204) {
      return new Response(null, { status: upstream.status });
    }
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": "application/json" },
    });
  } catch (error) {
    console.error(`Session ${method} proxy failed:`, error);
    return Response.json({ detail: "The advisor service is unavailable." }, { status: 502 });
  }
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return forward(id, "GET");
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return forward(id, "DELETE");
}
