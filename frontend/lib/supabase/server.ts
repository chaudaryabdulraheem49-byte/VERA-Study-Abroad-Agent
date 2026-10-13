import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";

/**
 * Supabase client for server components, route handlers and server actions.
 *
 * `cookies()` is async in Next 15, so this is too. The `setAll` writer is
 * wrapped because a Server Component is not allowed to set cookies: the
 * middleware refreshes the session on every request, so a failure to write
 * here is recoverable rather than a lost session.
 */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Called from a Server Component, which cannot write cookies.
            // Harmless: the middleware has already refreshed the session.
          }
        },
      },
    },
  );
}
