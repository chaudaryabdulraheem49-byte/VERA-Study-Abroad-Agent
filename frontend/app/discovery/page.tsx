"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2, MapPin, Search } from "lucide-react";

import { SideDock } from "@/components/side-dock";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

/**
 * Standalone university discovery.
 *
 * Browses the same indexed catalogue the consultation searches, without
 * needing a diagnostic first. Every row is a real indexed course - when a
 * field is not in the source data it says "Not published" rather than
 * inventing a plausible number.
 */

/** Mirrors exactly what GET /api/discovery returns - no invented fields. */
interface Programme {
  course_id: string;
  course_title: string;
  university_name: string | null;
  country: string | null;
  degree_level: string | null;
  field_broad: string | null;
  tuition_fee_usd: number | null;
  tuition_fee_amount: number | null;
  currency: string | null;
  min_gpa_percent: number | null;
  min_ielts_score: number | null;
  duration_weeks: number | null;
  post_study_work_eligible: boolean | null;
  deadline_type: string | null;
}

const COUNTRIES = [
  "Australia",
  "Austria",
  "Belgium",
  "Canada",
  "Denmark",
  "Finland",
  "France",
  "Germany",
  "Ireland",
  "Italy",
  "Netherlands",
  "Norway",
  "Poland",
  "Sweden",
  "Switzerland",
  "United Kingdom",
  "United States",
  "Europe (All)",
];
const LEVELS = ["Bachelors", "Masters", "PhD", "Diploma"];

export default function DiscoveryPage() {
  const [country, setCountry] = React.useState("Australia");
  const [level, setLevel] = React.useState("Masters");
  const [field, setField] = React.useState("");
  const [rows, setRows] = React.useState<Programme[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const params = new URLSearchParams({ country, degree_level: level, limit: "100" });
      if (field.trim()) params.set("field_broad", field.trim());
      const response = await fetch(`/api/discovery?${params.toString()}`);
      if (!response.ok) {
        setError("The catalogue could not be searched just now.");
        setRows(null);
        return;
      }
      const data = await response.json();
      setRows(data.courses ?? []);
    } catch {
      setError("Could not reach the catalogue. Is the backend running?");
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
          <header className="app-topbar">
            <Link className="brand" href="/" aria-label="Orbitly home">
              <span className="brand-mark" aria-hidden="true">
                <span></span>
                <span></span>
                <span></span>
              </span>
              <span className="brand-name">ORBITLY</span>
            </Link>
            <span className="app-separator"></span>
            <span className="app-context">
              <i></i> UNIVERSITY DISCOVERY
            </span>
            <div className="ml-auto">
              <ThemeToggle showLabel={false} />
            </div>
          </header>

          <form onSubmit={run} className="glass rounded-[18px] p-5">
            <div className="grid gap-4 md:grid-cols-[1fr_1fr_1.4fr_auto] md:items-end">
              <div className="space-y-1.5">
                <label htmlFor="country" className="caption-upper block text-muted-ink">
                  Destination
                </label>
                <select
                  id="country"
                  value={country}
                  onChange={(e) => setCountry(e.target.value)}
                  className="h-11 w-full rounded-[12px] border border-border bg-card px-3 text-[15px] text-ink outline-none focus:border-cyan"
                >
                  {COUNTRIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="level" className="caption-upper block text-muted-ink">
                  Level
                </label>
                <select
                  id="level"
                  value={level}
                  onChange={(e) => setLevel(e.target.value)}
                  className="h-11 w-full rounded-[12px] border border-border bg-card px-3 text-[15px] text-ink outline-none focus:border-cyan"
                >
                  {LEVELS.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="field" className="caption-upper block text-muted-ink">
                  Field of study
                </label>
                <input
                  id="field"
                  value={field}
                  onChange={(e) => setField(e.target.value)}
                  placeholder="e.g. Electrical Engineering, Business, Nursing..."
                  className="h-11 w-full rounded-[12px] border border-border bg-card px-3 text-[15px] text-ink outline-none placeholder:text-faint focus:border-cyan"
                />
              </div>

              <Button type="submit" disabled={busy} className="h-11">
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Search className="h-4 w-4" aria-hidden />
                )}
                Search
              </Button>
            </div>
          </form>

          {error ? (
            <p className="glass rounded-[18px] px-5 py-4 text-sm text-destructive">{error}</p>
          ) : null}

          {rows === null ? (
            <div className="glass flex min-h-[16rem] items-center justify-center rounded-[18px] p-8 text-center">
              <p className="max-w-md text-sm leading-[1.6] text-muted-ink">
                Browse the indexed catalogue directly. For advice shaped around
                your own grades and English scores,{" "}
                <Link href="/chat" className="text-cyan underline-offset-4 hover:underline">
                  start a consultation
                </Link>{" "}
                instead.
              </p>
            </div>
          ) : rows.length === 0 ? (
            <div className="glass rounded-[18px] p-8 text-center">
              <p className="text-sm leading-[1.6] text-muted-ink">
                Nothing in the index matches that combination yet. The
                catalogue is still being embedded, so a narrower field is more
                likely to come back empty than a broad one.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between px-1">
                <p className="caption-upper text-muted-ink">
                  Found {rows.length} {rows.length === 1 ? "programme" : "programmes"}
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {rows.map((row, index) => (
                  <ProgrammeCard key={row.course_id} row={row} index={index} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

function ProgrammeCard({ row, index }: { row: Programme; index: number }) {
  // Tuition is shown in its own currency when the source gives one; the USD
  // figure is a conversion, so it is only the fallback.
  const tuition =
    row.tuition_fee_amount !== null && row.currency
      ? row.tuition_fee_amount === 0
        ? "Free (0 EUR)"
        : `${row.currency} ${row.tuition_fee_amount.toLocaleString()}`
      : row.tuition_fee_usd
        ? row.tuition_fee_usd === 0
          ? "Free (0 EUR)"
          : `US$${row.tuition_fee_usd.toLocaleString()}`
        : null;

  return (
    <article
      className="glass rise-in flex flex-col rounded-[18px] p-5"
      style={{ ["--rise-delay" as string]: `${Math.min(index, 8) * 40}ms` }}
    >
      {row.field_broad ? (
        <p className="caption-upper text-cyan">{row.field_broad}</p>
      ) : null}

      <h3 className="programme-card-title mt-2 font-sans text-[16px] font-semibold leading-[1.35] tracking-tight text-ink break-words">
        {row.course_title}
      </h3>

      {row.university_name ? (
        <p className="mt-1 text-sm text-muted-ink">{row.university_name}</p>
      ) : null}

      {row.country ? (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-faint">
          <MapPin className="h-3.5 w-3.5" aria-hidden />
          {row.country}
          {row.degree_level ? ` - ${row.degree_level}` : ""}
        </p>
      ) : null}

      <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-2.5 border-t border-hairline pt-4">
        <Fact label="Duration" value={row.duration_weeks ? `${row.duration_weeks} wks` : null} />
        <Fact label="Tuition" value={tuition} />
        <Fact label="Min GPA" value={row.min_gpa_percent ? `${row.min_gpa_percent}%` : null} />
        <Fact label="IELTS" value={row.min_ielts_score ? row.min_ielts_score.toFixed(1) : null} />
      </dl>

      {row.post_study_work_eligible ? (
        <p className="mt-4 text-xs text-emerald">Post-study work eligible</p>
      ) : null}
    </article>
  );
}

/**
 * A missing value prints "Not published", never a guess. These are the
 * numbers a student decides where to apply on - an invented entry
 * requirement is worse than an absent one.
 */
function Fact({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="caption-upper text-faint">{label}</dt>
      <dd className={value ? "metric mt-0.5 text-[13px] text-ink" : "mt-0.5 text-[12px] text-faint"}>
        {value ?? "Not published"}
      </dd>
    </div>
  );
}
