import type { NextRequest } from "next/server";

import { forwardToBackend } from "@/lib/proxy";

/**
 * Proxy for the grade converter.
 *
 * Same reasoning as the other proxies: the browser stays same-origin so the
 * backend URL never reaches the client.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return forwardToBackend(request, "/api/convert");
}
