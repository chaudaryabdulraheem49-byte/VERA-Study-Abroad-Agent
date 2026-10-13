import { createBrowserClient } from "@supabase/ssr";

/**
 * Supabase client for browser code.
 *
 * The anon key is public by design: it carries no privileges of its own, and
 * what a signed-in person may read or write is decided entirely by the Row
 * Level Security policies in backend/migrations/001_chat_history_rls.sql. The
 * service-role key must never appear in this file or any other the browser
 * downloads.
 */
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}

/** Whether Supabase is configured at all, so the UI can degrade rather than crash. */
export const isAuthConfigured = Boolean(
  process.env.NEXT_PUBLIC_SUPABASE_URL &&
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
);
