"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, TriangleAlert } from "lucide-react";

import { ThemeToggle } from "@/components/theme-toggle";
import { createClient, isAuthConfigured } from "@/lib/supabase/client";

type Mode = "login" | "signup";

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const params = useSearchParams();

  const [firstName, setFirstName] = React.useState("");
  const [lastName, setLastName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const requested = params.get("next") ?? "/chat";
  const next =
    requested.startsWith("/") && !requested.startsWith("//") ? requested : "/chat";
  const callbackError = params.get("error");

  const isSignup = mode === "signup";

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);

    if (!isAuthConfigured) {
      setError(
        "Accounts are not configured on this deployment. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.",
      );
      return;
    }

    setBusy(true);
    try {
      const supabase = createClient();

      if (isSignup) {
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
          options: {
            data: {
              first_name: firstName,
              last_name: lastName,
            },
            emailRedirectTo: `${window.location.origin}/api/auth/callback?next=${encodeURIComponent(next)}`,
          },
        });
        if (error) throw error;

        if (!data.session) {
          setNotice(
            `Check ${email} for a confirmation link. You can close this page.`,
          );
          return;
        }
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (error) throw error;
      }

      router.push(next);
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      {/* Left visual column */}
      <section className="auth-visual">
        <div className="auth-visual-grid"></div>
        <div className="auth-orbit orbit-ring-one"></div>
        <div className="auth-orbit orbit-ring-two"></div>
        <span className="auth-node node-one"></span>
        <span className="auth-node node-two"></span>

        <Link className="brand auth-brand" href="/">
          <span className="brand-mark" aria-hidden="true">
            <span></span>
            <span></span>
            <span></span>
          </span>
          <span className="brand-name">ORBITLY</span>
        </Link>

        <div className="auth-visual-copy">
          <span className="eyebrow">
            <span className="eyebrow-dot"></span>{" "}
            {isSignup ? "Start with a signal" : "Your next chapter, mapped"}
          </span>
          {isSignup ? (
            <h1>
              Make the
              <br />
              <em>move yours.</em>
            </h1>
          ) : (
            <h1>
              Good direction
              <br />
              <em>starts here.</em>
            </h1>
          )}
          <p>
            {isSignup
              ? "Build a clearer study-abroad plan with an advisor that understands the person behind the grades."
              : "Pick up where your university search left off. Vera already knows how to ask the right next question."}
          </p>
          <span className="auth-coordinate">
            {isSignup ? "40.7128° N   /   74.0060° W" : "51.5072° N   /   0.1276° W"}
          </span>
        </div>

        <div className="auth-visual-footer">
          <span>{isSignup ? "ORBITLY / ACCESS 002" : "ORBITLY / ACCESS 001"}</span>
          <span>
            {isSignup
              ? "Find the fit behind the ranking."
              : "Human guidance, intelligent signals."}
          </span>
        </div>
      </section>

      {/* Right form column */}
      <main className="auth-form-area">
        <header className="auth-topbar">
          <Link href="/" className="back-link">
            ← Back to Orbitly
          </Link>
          <div className="auth-top-actions">
            <ThemeToggle />
            <span>
              {isSignup ? (
                <>
                  Already a member? <Link href="/login">Log in</Link>
                </>
              ) : (
                <>
                  New here? <Link href="/signup">Create account</Link>
                </>
              )}
            </span>
          </div>
        </header>

        <div className="auth-form-wrap">
          <span className="form-kicker">
            {isSignup ? "CREATE ACCOUNT / 01" : "WELCOME BACK / 01"}
          </span>
          <h2>
            {isSignup ? (
              <>
                Start your
                <br />
                <em>orbit.</em>
              </>
            ) : (
              <>
                Continue your
                <br />
                <em>orbit.</em>
              </>
            )}
          </h2>
          <p className="form-intro">
            {isSignup
              ? "A few details now. A much better shortlist later."
              : "Your shortlist, signals, and next steps are waiting."}
          </p>

          {callbackError ? (
            <div className="mb-6 flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-400">
              <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden />
              <span>
                {callbackError === "missing_code"
                  ? "That confirmation link was incomplete. Try signing in directly."
                  : "That confirmation link could not be used. It may have expired."}
              </span>
            </div>
          ) : null}

          {error ? (
            <div className="mb-6 flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-400">
              <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden />
              <span>{error}</span>
            </div>
          ) : null}

          {notice ? (
            <div className="mb-6 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-xs text-emerald-400">
              {notice}
            </div>
          ) : null}

          <form className="auth-form" onSubmit={onSubmit}>
            {isSignup && (
              <div className="field-pair">
                <label>
                  First name
                  <input
                    type="text"
                    name="firstName"
                    placeholder="Clara"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    required
                  />
                </label>
                <label>
                  Last name
                  <input
                    type="text"
                    name="lastName"
                    placeholder="Green"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    required
                  />
                </label>
              </div>
            )}

            <label>
              Email address
              <input
                type="email"
                name="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </label>

            <label>
              {isSignup ? "Create password" : "Password"}
              {!isSignup && (
                <span className="label-action">
                  <a href="#">Forgot?</a>
                </span>
              )}
              <input
                type="password"
                name="password"
                placeholder={isSignup ? "At least 8 characters" : "Enter your password"}
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>

            {isSignup && (
              <label className="consent-label">
                <input type="checkbox" required />
                <span>
                  I agree to Orbitly’s <a href="#">terms</a> and understand how my profile signals are used.
                </span>
              </label>
            )}

            <button
              className="button button-primary form-submit"
              type="submit"
              disabled={busy}
            >
              {busy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  Working...
                </>
              ) : isSignup ? (
                <>
                  Create my orbit <span className="button-arrow">↗</span>
                </>
              ) : (
                <>
                  Enter workspace <span className="button-arrow">↗</span>
                </>
              )}
            </button>

            <div className="form-divider">
              <span>or continue with</span>
            </div>

            <button
              className="social-button"
              type="button"
              onClick={() => {
                if (isAuthConfigured) {
                  const supabase = createClient();
                  supabase.auth.signInWithOAuth({
                    provider: "google",
                    options: {
                      redirectTo: `${window.location.origin}/api/auth/callback?next=${encodeURIComponent(next)}`,
                    },
                  });
                } else {
                  setError("Google sign-in is not configured on this deployment.");
                }
              }}
            >
              <span className="google-mark">G</span> Google
            </button>

            <p className="form-status" aria-live="polite"></p>
          </form>
        </div>

        <footer className="auth-footer">
          <span>© 2026 Orbitly AI</span>
          {isSignup ? (
            <Link href="/login">Already have an account ↗</Link>
          ) : (
            <Link href="/signup">Create an account ↗</Link>
          )}
        </footer>
      </main>
    </div>
  );
}
