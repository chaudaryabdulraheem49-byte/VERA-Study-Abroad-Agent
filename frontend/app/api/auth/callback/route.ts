import { NextResponse, type NextRequest } from "next/server";

import { createClient } from "@/lib/supabase/server";

/**
 * Exchange an auth code for a session.
 *
 * Where Supabase sends people back after confirming an email address or
 * completing an OAuth flow. The code is single-use and exchanged server-side,
 * so the resulting refresh token is written to an httpOnly cookie rather than
 * passing through client JavaScript.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");

  // Only a path, never an absolute URL: `?next=https://elsewhere` would make
  // this an open redirect, and the parameter is attacker-controlled.
  const requested = searchParams.get("next") ?? "/chat";
  const next = requested.startsWith("/") && !requested.startsWith("//")
    ? requested
    : "/chat";

  if (!code) {
    return NextResponse.redirect(`${origin}/login?error=missing_code`);
  }

  const supabase = await createClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    // The message is Supabase's and may name the account; only a code is
    // reflected back into the URL.
    console.error("Auth callback failed:", error.message);
    return NextResponse.redirect(`${origin}/login?error=exchange_failed`);
  }

  return NextResponse.redirect(`${origin}${next}`);
}
