"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2, TriangleAlert } from "lucide-react";

import { SideDock } from "@/components/side-dock";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

/**
 * Modified Bavarian grade converter.
 *
 * Calls the same `convert()` the conversation uses, through `/api/convert`.
 * Re-implementing the formula in the browser would give two sets of numbers
 * that have to stay in agreement, and these are numbers a student plans
 * around.
 */

const SCALES = [
  { value: "percentage", label: "Percentage (0-100)", max: 100 },
  { value: "us_4_0", label: "US GPA (0-4.0)", max: 4 },
  { value: "scale_10_0", label: "10-point (India, Spain)", max: 10 },
  { value: "scale_20_0", label: "20-point (France, Portugal)", max: 20 },
  { value: "scale_5_0", label: "5-point (Russia, Nigeria)", max: 5 },
  { value: "german_1_5", label: "German (1.0-5.0, inverted)", max: 5 },
] as const;

interface Conversion {
  normalized_percentage: number;
  us_gpa: number;
  us_letter: string;
  german_grade: number;
  german_label: string;
  german_formula: string;
  uk_classification: string;
  ects_grade: string;
  assumptions: string[];
}

export default function ConverterPage() {
  const [raw, setRaw] = React.useState("84");
  const [scale, setScale] = React.useState<string>("percentage");
  const [country, setCountry] = React.useState("");
  const [result, setResult] = React.useState<Conversion | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const response = await fetch("/api/convert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          raw_value: Number(raw),
          scale,
          scale_max: SCALES.find((s) => s.value === scale)?.max ?? null,
          country: country || null,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        // The backend's 422 explains what is missing, which is more useful
        // than a generic failure.
        setResult(null);
        setError(data.detail ?? "That grade could not be converted.");
        return;
      }
      setResult(data);
    } catch {
      setError("Could not reach the converter. Is the backend running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative flex min-h-dvh flex-col overflow-hidden">
      <div aria-hidden className="aurora" />

      <div className="relative z-10 mx-auto flex w-full max-w-[1400px] gap-3 p-3 sm:gap-4 sm:p-4">
        <SideDock />

        <div className="min-w-0 flex-1 space-y-4">
          <header className="glass relative z-20 flex items-center gap-3 rounded-[18px] px-4 py-3">
            <Link href="/chat" className="display-sm text-ink">
              Vera
            </Link>
            <span aria-hidden className="h-4 w-px bg-hairline" />
            <p className="caption-upper text-muted-ink">Grade converter</p>
            <div className="ml-auto">
              <ThemeToggle />
            </div>
          </header>

          <div className="grid gap-4 lg:grid-cols-5">
            {/* --- Input ------------------------------------------------- */}
            <form onSubmit={run} className="glass rounded-[18px] p-6 lg:col-span-2">
              <h1 className="display-md text-ink">Modified Bavarian Formula</h1>
              <p className="mt-2 text-sm leading-[1.6] text-muted-ink">
                The conversion German universities actually apply, as published
                by the Kultusministerkonferenz.
              </p>
              <p className="metric mt-4 rounded-[12px] bg-white/5 px-3 py-2.5 text-[13px] text-cyan">
                N = 1 + 3 x (Nmax - Nd) / (Nmax - Nmin)
              </p>

              <div className="mt-6 space-y-4">
                <div className="space-y-1.5">
                  <label htmlFor="scale" className="caption-upper block text-muted-ink">
                    Your grading scale
                  </label>
                  <select
                    id="scale"
                    value={scale}
                    onChange={(e) => setScale(e.target.value)}
                    className="h-11 w-full rounded-[12px] border border-border bg-card px-3 text-[15px] text-ink outline-none transition-colors focus:border-cyan"
                  >
                    {SCALES.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="raw" className="caption-upper block text-muted-ink">
                    Your grade
                  </label>
                  <input
                    id="raw"
                    type="number"
                    step="0.01"
                    required
                    value={raw}
                    onChange={(e) => setRaw(e.target.value)}
                    className="metric h-11 w-full rounded-[12px] border border-border bg-card px-3 text-[15px] text-ink outline-none transition-colors focus:border-cyan"
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="country" className="caption-upper block text-muted-ink">
                    Country (optional)
                  </label>
                  <input
                    id="country"
                    value={country}
                    onChange={(e) => setCountry(e.target.value)}
                    placeholder="Pakistan, India, China..."
                    className="h-11 w-full rounded-[12px] border border-border bg-card px-3 text-[15px] text-ink outline-none transition-colors placeholder:text-faint focus:border-cyan"
                  />
                  <p className="text-xs leading-[1.5] text-faint">
                    Only used to pick the minimum passing mark. Pakistan and
                    India pass at 40%, China at 60%; the default assumes 50%.
                  </p>
                </div>
              </div>

              {error ? (
                <p className="mt-4 flex items-start gap-2 text-sm text-destructive">
                  <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  {error}
                </p>
              ) : null}

              <Button type="submit" className="mt-6 w-full" disabled={busy}>
                {busy ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                    Converting...
                  </>
                ) : (
                  "Convert"
                )}
              </Button>
            </form>

            {/* --- Output ------------------------------------------------ */}
            <div className="lg:col-span-3">
              {result ? (
                <div className="space-y-4">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Metric
                      label="German"
                      value={result.german_grade.toFixed(1)}
                      caption={result.german_label}
                      accent="text-cyan"
                    />
                    <Metric
                      label="US GPA"
                      value={result.us_gpa.toFixed(2)}
                      caption={`Letter ${result.us_letter}`}
                      accent="text-violet"
                    />
                    <Metric
                      label="UK honours"
                      value={result.uk_classification}
                      caption="Classification"
                      accent="text-emerald"
                      small
                    />
                    <Metric
                      label="ECTS"
                      value={result.ects_grade}
                      caption={`Normalised ${result.normalized_percentage.toFixed(1)}%`}
                      accent="text-amber"
                    />
                  </div>

                  <div className="glass rounded-[18px] p-5">
                    <h2 className="caption-upper text-muted-ink">How this was computed</h2>
                    <p className="metric mt-3 text-[13px] leading-[1.7] text-ink">
                      {result.german_formula}
                    </p>
                    {result.assumptions.length > 0 ? (
                      <ul className="mt-4 space-y-1.5">
                        {result.assumptions.map((note) => (
                          <li key={note} className="text-sm leading-[1.6] text-muted-ink">
                            {note}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div className="glass flex h-full min-h-[18rem] items-center justify-center rounded-[18px] p-8 text-center">
                  <p className="max-w-sm text-sm leading-[1.6] text-muted-ink">
                    Enter a grade to see it in all four systems at once. Nothing
                    is estimated - every figure comes from the published
                    formula.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

function Metric({
  label,
  value,
  caption,
  accent,
  small,
}: {
  label: string;
  value: string;
  caption: string;
  accent: string;
  small?: boolean;
}) {
  return (
    <div className="glass rounded-[18px] p-5">
      <p className="caption-upper text-muted-ink">{label}</p>
      <p
        className={`metric mt-2 ${small ? "text-[18px]" : "text-[32px]"} leading-tight ${accent}`}
      >
        {value}
      </p>
      <p className="mt-1 text-xs text-faint">{caption}</p>
    </div>
  );
}
