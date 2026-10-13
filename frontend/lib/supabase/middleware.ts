import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/** Routes that require a signed-in user. */
const PROTECTED = ["/chat"];

/** Routes a signed-in user has no reason to see. */
const AUTH_PAGES = ["/login", "/signup"];

/**
 * Refresh the Supabase session and decide whether the request may proceed.
 *
 * Two things happen here and the order matters. `getUser()` is what refreshes
 * an expiring access token, and the refreshed cookies are written onto the
 * response object created *before* the call - so the response must be built
 * first, mutated by the cookie writers, and then returned or copied onto a
 * redirect. Returning a fresh NextResponse at the end would discard the new
 * tokens and sign the person out every hour.
 *
 * `getUser()` rather than `getSession()`: the former revalidates the token
 * with Supabase, the latter trusts whatever is in the cookie, which a client
 * can set.
 */
export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // Not configured: the app runs without accounts, exactly as it did before
  // they existed. Gating every route behind a half-configured auth system
  // would turn a missing env var into a dead application.
  if (!url || !key) return response;

  const supabase = createServerClient(url, key, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) =>
          request.cookies.set(name, value),
        );
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options),
        );
      },
    },
  });

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;

  if (!user && PROTECTED.some((p) => pathname.startsWith(p))) {
    const redirect = request.nextUrl.clone();
    redirect.pathname = "/login";
    // Remembered so the student lands back where they were going, rather than
    // on a generic page having forgotten why they signed in.
    redirect.searchParams.set("next", pathname);
    return copyCookies(response, NextResponse.redirect(redirect));
  }

  if (user && AUTH_PAGES.some((p) => pathname.startsWith(p))) {
    const redirect = request.nextUrl.clone();
    redirect.pathname = "/chat";
    redirect.search = "";
    return copyCookies(response, NextResponse.redirect(redirect));
  }

  return response;
}

/** Carry refreshed auth cookies onto a redirect, which would otherwise lose them. */
function copyCookies(from: NextResponse, to: NextResponse) {
  from.cookies.getAll().forEach((cookie) => to.cookies.set(cookie));
  return to;
}
