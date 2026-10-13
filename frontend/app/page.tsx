import Link from "next/link";
import {
  ArrowRight,
  Compass,
  FileText,
  GraduationCap,
  Scale,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";

/**
 * Welcome page, Aurora Dark Luxury.
 *
 * The spec's hero is a cone of volumetric light falling onto the headline
 * over an obsidian canvas - which CSS can produce honestly with a radial
 * gradient and two drifting glows, so no illustrated asset is faked here.
 * Every moving element is decorative and stops under
 * `prefers-reduced-motion`.
 */

const CAPABILITIES = [
  {
    accent: "text-cyan",
    ring: "ring-cyan/25",
    glow: "bg-cyan/10",
    icon: <FileText className="h-5 w-5" aria-hidden />,
    title: "Reads your transcript",
    body: "Drop in a scan and Vera pulls out your name, subjects, credits and cumulative grade.",
  },
  {
    accent: "text-violet",
    ring: "ring-violet/25",
    glow: "bg-violet/10",
    icon: <Scale className="h-5 w-5" aria-hidden />,
    title: "Converts your grade",
    body: "US GPA, the German Modified Bavarian Formula, UK honours and ECTS - computed, never estimated.",
  },
  {
    accent: "text-emerald",
    ring: "ring-emerald/25",
    glow: "bg-emerald/10",
    icon: <GraduationCap className="h-5 w-5" aria-hidden />,
    title: "Finds real programmes",
    body: "Matched against an index of registered courses, filtered on what you actually qualify for.",
  },
] as const;

const STEPS = [
  "Tell Vera about yourself, or drop your transcript in",
  "Get your grade converted into four systems at once",
  "See the programmes you qualify for, ranked by subject",
] as const;

export default function Home() {
  return (
    <main className="relative min-h-dvh overflow-hidden">
      <div aria-hidden className="aurora" />

      <div className="relative z-10 mx-auto max-w-[1280px] px-4 py-10 sm:px-8 sm:py-14">
        <nav className="flex items-center gap-3">
          <span className="display-sm text-ink">Vera</span>
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
          </div>
        </nav>

        {/* --- Hero ------------------------------------------------------ */}
        <section className="relative mt-16 text-center sm:mt-24">
          <div aria-hidden className="light-cone" />

          <span className="caption-upper rise-in glass relative inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-muted-ink">
            <Sparkles className="h-3.5 w-3.5 text-cyan" aria-hidden />
            Study abroad, worked out properly
          </span>

          <h1
            className="display-xl rise-in relative mx-auto mt-7 max-w-3xl text-ink"
            style={{ ["--rise-delay" as string]: "80ms" }}
          >
            Know exactly where
            <br />
            you stand
          </h1>

          <p
            className="rise-in relative mx-auto mt-6 max-w-xl text-[18px] leading-[1.6] text-body"
            style={{ ["--rise-delay" as string]: "160ms" }}
          >
            Vera reads your transcript, converts your grade into the systems
            universities actually use, and shows you the programmes you qualify
            for. No guesswork, no invented numbers.
          </p>

          <div
            className="rise-in relative mt-10 flex flex-wrap items-center justify-center gap-3"
            style={{ ["--rise-delay" as string]: "240ms" }}
          >
            <Button asChild size="lg">
              <Link href="/chat">
                Start a consultation
                <ArrowRight className="h-4 w-4" aria-hidden />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/discovery">
                <Compass className="h-4 w-4" aria-hidden />
                Browse universities
              </Link>
            </Button>
          </div>
        </section>

        {/* --- Capabilities --------------------------------------------- */}
        <section className="mt-28 sm:mt-36">
          <h2 className="display-md max-w-2xl text-ink">
            Three things Vera does before you ask
          </h2>

          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {CAPABILITIES.map((card, index) => (
              <article
                key={card.title}
                className="glass rise-in rounded-[18px] p-7"
                style={{ ["--rise-delay" as string]: `${index * 90}ms` }}
              >
                <span
                  className={`inline-flex h-11 w-11 items-center justify-center rounded-[14px] ring-1 ${card.glow} ${card.ring} ${card.accent}`}
                >
                  {card.icon}
                </span>
                <h3 className="mt-5 text-[18px] font-semibold leading-[1.4] text-ink">
                  {card.title}
                </h3>
                <p className="mt-2 text-[15px] leading-[1.6] text-muted-ink">
                  {card.body}
                </p>
              </article>
            ))}
          </div>
        </section>

        {/* --- How it works --------------------------------------------- */}
        <section className="mt-24 sm:mt-32">
          <div className="glass rounded-[18px] p-8 sm:p-12">
            <h2 className="display-sm text-ink">How it works</h2>
            <ol className="mt-8 grid gap-6 md:grid-cols-3">
              {STEPS.map((step, index) => (
                <li key={step} className="flex gap-4">
                  {/* Cyan fill with the fixed on-fill ink. Neither side of
                      this pairing follows the theme, so it cannot invert into
                      the white-on-white it used to. */}
                  <span className="metric flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-cyan text-sm font-semibold text-on-fill">
                    {index + 1}
                  </span>
                  <p className="text-[16px] leading-[1.6] text-body">{step}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* --- Closing CTA ---------------------------------------------- */}
        <section className="mt-24 sm:mt-32">
          <div className="glass relative overflow-hidden rounded-[18px] px-8 py-16 text-center sm:px-12 sm:py-20">
            <div aria-hidden className="light-cone" />
            <div className="relative">
              <h2 className="display-md mx-auto max-w-2xl text-ink">
                Find out where you actually stand
              </h2>
              <p className="mx-auto mt-4 max-w-lg text-[16px] leading-[1.6] text-muted-ink">
                It takes a few minutes, and you can start with nothing more
                than your grade.
              </p>
              <Button asChild size="lg" className="mt-8">
                <Link href="/chat">
                  Start a consultation
                  <ArrowRight className="h-4 w-4" aria-hidden />
                </Link>
              </Button>
            </div>
          </div>
        </section>

        <footer className="mt-20 border-t border-hairline pt-8 text-sm leading-[1.6] text-faint">
          Vera converts grades with published formulas and matches against a
          real course register. Figures a source does not publish are shown as
          unpublished, never filled in.
        </footer>
      </div>
    </main>
  );
}
