import { createClient, isAuthConfigured } from "@/lib/supabase/client";

export { isAuthConfigured };

/**
 * `Authorization: Bearer <access token>` for the signed-in user, or null.
 *
 * Read fresh on every call rather than cached: the token is short-lived, and
 * `getSession()` returns the refreshed one once the Supabase client has
 * rotated it. A cached header would start failing an hour in, intermittently,
 * which is the worst way for this to break.
 *
 * Returns null when nobody is signed in or accounts are not configured, which
 * callers treat as "send the request without auth" rather than as an error -
 * the backend still serves anonymous sessions.
 */
export async function authHeader(): Promise<Record<string, string> | null> {
  if (!isAuthConfigured) return null;
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session?.access_token) return null;
    return { Authorization: `Bearer ${session.access_token}` };
  } catch (error) {
    console.error("Could not read the Supabase session:", error);
    return null;
  }
}
