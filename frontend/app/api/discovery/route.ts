import type { NextRequest } from "next/server";

import { forwardToBackend } from "@/lib/proxy";

/** Proxy for standalone university discovery. */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return forwardToBackend(request, "/api/discovery");
}
