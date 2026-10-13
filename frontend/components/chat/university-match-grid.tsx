"use client";

import * as React from "react";
import {
  BadgeCheck,
  CalendarClock,
  Coins,
  GraduationCap,
  Info,
  MapPin,
  SearchX,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { UniversityMatch, UniversityMatchesPayload } from "@/types/chat";

interface UniversityMatchGridProps {
  payload: UniversityMatchesPayload;
  className?: string;
}

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

/** Tuition in the currency the university actually charges, plus USD. */
function formatTuition(match: UniversityMatch): string {
  const usd = USD.format(match.tuition_fee_usd);
  if (match.currency === "USD") return usd;
  const local = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
  }).format(match.tuition_fee_amount);
  return `${local} ${match.currency} · ~${usd}`;
}

/**
 * A deadline is only useful if we know it, and "we don't know" is a different
 * answer from "applications never close". Both are stated plainly rather than
 * filled in with a plausible date, because a student books flights and pays
 * deposits against this field.
 */
function formatDeadline(match: UniversityMatch): string {
  if (match.deadline_date) {
    const isoMatch = match.deadline_date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (isoMatch) {
      const [, y, m, d] = isoMatch;
      const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      const month = months[parseInt(m, 10) - 1] ?? m;
      return `${parseInt(d, 10)} ${month} ${y}`;
    }
    const parsed = new Date(match.deadline_date);
    if (!Number.isNaN(parsed.getTime())) {
      const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      return `${parsed.getUTCDate()} ${months[parsed.getUTCMonth()]} ${parsed.getUTCFullYear()}`;
    }
    return match.deadline_date;
  }
  if (match.intakes) return match.intakes;
  if (match.deadline_type === "rolling") return "Rolling intake";
  return "Ask the university";
}

/**
 * An unstated entry requirement renders as unstated. It previously showed as
 * "0% · IELTS 0", which reads as a course that asks for nothing - the
 * opposite of "we have no figure for this one".
 */
function formatRequirement(match: UniversityMatch): string {
  const parts: string[] = [];
  if (match.min_gpa_percent !== null && match.min_gpa_percent !== undefined) {
    parts.push(`${match.min_gpa_percent}%`);
  }
  if (match.min_ielts_score !== null && match.min_ielts_score !== undefined) {
    parts.push(`IELTS ${match.min_ielts_score}`);
  }
  return parts.length > 0 ? parts.join(" · ") : "Not published";
}

export function UniversityMatchGrid({
  payload,
  className,
}: UniversityMatchGridProps) {
  const {
    matches,
    query,
    note,
    from_related_fields: fromRelated,
    guidance,
  } = payload;

  // An empty index is a gap in the catalogue, not a verdict on the student, so
  // it reads as a neutral note rather than an error.
  if (matches.length === 0) {
    if (!note) return null;
    return (
      <section
        className={cn("mt-4", className)}
        aria-label="Matching programmes"
      >
        <p className="flex items-start gap-2 rounded-lg border border-dashed px-3 py-2.5 text-xs leading-relaxed text-muted-foreground">
          <SearchX className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {note}
        </p>
      </section>
    );
  }

  return (
    <section
      className={cn("mt-4 space-y-3", className)}
      aria-label="Matching programmes"
    >
      <header className="space-y-1">
        <h3 className="display-sm text-ink">
          {matches.length} programme{matches.length === 1 ? "" : "s"} you qualify for
        </h3>
        <p className="text-xs text-muted-foreground">
          Filtered on your converted grade and language score, then ranked by how
          closely the syllabus matches{query ? ` “${query}”` : " your profile"}.
        </p>
        {guidance ? (
          // Deliberately one line for the whole grid rather than a figure on
          // each card: repeated per course it would read as that course's
          // requirement, which is the one thing it is not.
          <p className="flex items-start gap-2 rounded-md border border-border/60 bg-muted/40 px-2.5 py-2 text-xs leading-relaxed text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              <span className="font-medium text-foreground">
                Typical for {guidance.country}:
              </span>{" "}
              around {guidance.typical_gpa_percent}% and IELTS{" "}
              {guidance.typical_ielts}.{" "}
              {guidance.student_clears === true ? (
                <span className="font-semibold text-success">
                  Your converted grade clears that.
                </span>
              ) : guidance.student_clears === false ? (
                <span className="font-semibold text-warning">
                  Your converted grade is below that.
                </span>
              ) : null}{" "}
              {guidance.unstated_count === matches.length
                ? "None of the programmes below publishes its own requirements"
                : `${guidance.unstated_count} of the programmes below publish no requirements of their own`}
              , so this is a country-level guide, not their stated bar.
            </span>
          </p>
        ) : null}

        {fromRelated ? (
          // Said plainly rather than implied by the scores: a student comparing
          // these needs to know they are not in the subject they asked for.
          <p className="text-xs font-medium text-warning">
            Nothing in the index matched your subject closely enough, so these
            are from neighbouring disciplines.
          </p>
        ) : null}
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        {matches.map((match) => (
          <Card key={match.course_id} className="flex flex-col">
            <CardHeader className="space-y-1 pb-3">
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="display-sm text-ink">
                  {match.course_title}
                </CardTitle>
                <Badge variant="secondary" className="shrink-0 border-transparent bg-teal text-white tabular-nums">
                  {Math.round(match.similarity_score * 100)}% fit
                </Badge>
              </div>
              <CardDescription className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="inline-flex items-center gap-1">
                  <GraduationCap className="h-3.5 w-3.5" aria-hidden />
                  {match.university_name}
                </span>
                <span className="inline-flex items-center gap-1">
                  <MapPin className="h-3.5 w-3.5" aria-hidden />
                  {match.country}
                </span>
              </CardDescription>
            </CardHeader>

            <CardContent className="flex flex-1 flex-col gap-3 pt-0">
              <p className="line-clamp-3 text-xs leading-relaxed text-muted-foreground">
                {match.syllabus_description}
              </p>

              <dl className="mt-auto grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                <div>
                  <dt className="inline-flex items-center gap-1 text-muted-foreground">
                    <Coins className="h-3.5 w-3.5" aria-hidden />
                    Tuition
                  </dt>
                  <dd className="text-[13px] tabular-nums text-ink" suppressHydrationWarning>
                    {formatTuition(match)}
                  </dd>
                </div>
                <div>
                  <dt className="inline-flex items-center gap-1 text-muted-foreground">
                    <CalendarClock className="h-3.5 w-3.5" aria-hidden />
                    Apply by
                  </dt>
                  <dd className="text-[13px] text-ink" suppressHydrationWarning>
                    {formatDeadline(match)}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Entry requirement</dt>
                  <dd className="text-[13px] tabular-nums text-ink">
                    {formatRequirement(match)}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Level</dt>
                  <dd className="text-[13px] text-ink">{match.degree_level}</dd>
                </div>
              </dl>

              {match.post_study_work_eligible ? (
                <p className="inline-flex items-center gap-1 text-xs font-medium text-success">
                  <BadgeCheck className="h-3.5 w-3.5" aria-hidden />
                  Post-study work visa available
                </p>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
