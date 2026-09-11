"use client";

import * as React from "react";
import {
  AlertTriangle,
  GraduationCap,
  Info,
  Landmark,
  Sigma,
  Target,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { DiagnosticCardPayload, GradeConversion } from "@/types/chat";

interface DiagnosticCardProps {
  payload: DiagnosticCardPayload;
  className?: string;
}

/** One converted grade: value, caption and a bar scaled to its own system. */
interface Metric {
  key: string;
  system: string;
  icon: React.ReactNode;
  value: string;
  caption: string;
  /** Bar fill 0-100, already oriented so "more is better". */
  percent: number;
  scaleHint: string;
  markers?: number[];
  tone: string;
}

function buildMetrics(conversion: GradeConversion): Metric[] {
  return [
    {
      key: "us",
      system: "United States",
      icon: <GraduationCap className="h-4 w-4" aria-hidden />,
      value: conversion.us_gpa.toFixed(2),
      caption: `Letter grade ${conversion.us_letter}`,
      percent: (conversion.us_gpa / 4) * 100,
      scaleHint: "out of 4.00",
      // 3.0 is the common graduate-admission floor.
      markers: [75],
      tone: "bg-sky-500",
    },
    {
      key: "de",
      system: "Germany",
      icon: <Landmark className="h-4 w-4" aria-hidden />,
      value: conversion.german_grade.toFixed(1),
      caption: conversion.german_label,
      // German grades invert: 1.0 is best, so fill the bar from the good end.
      percent: ((5 - conversion.german_grade) / 4) * 100,
      scaleHint: "1.0 best - 5.0 fail",
      // 2.5 is the usual competitive Master's cut-off.
      markers: [62.5],
      tone: "bg-amber-500",
    },
    {
      key: "uk",
      system: "UK / ECTS",
      icon: <Sigma className="h-4 w-4" aria-hidden />,
      value: shortUkClass(conversion.uk_classification),
      caption: `${conversion.normalized_percentage.toFixed(1)}% - ECTS ${conversion.ects_grade}`,
      percent: conversion.normalized_percentage,
      scaleHint: "2:2 50 - 2:1 60 - 1st 70",
      markers: [50, 60, 70],
      tone: "bg-violet-500",
    },
  ];
}

function shortUkClass(classification: string): string {
  if (classification.startsWith("First")) return "First";
  if (classification.includes("2:1")) return "2:1";
  if (classification.includes("2:2")) return "2:2";
  if (classification.startsWith("Third")) return "Third";
  return "Below";
}

export function DiagnosticCard({ payload, className }: DiagnosticCardProps) {
  const { conversion } = payload;
  const metrics = React.useMemo(() => buildMetrics(conversion), [conversion]);

  return (
    <Card className={cn("w-full overflow-hidden", className)}>
      <CardHeader className="gap-2 border-b border-border bg-muted/40">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">
              Academic diagnostic{payload.student_name ? ` - ${payload.student_name}` : ""}
            </CardTitle>
            <CardDescription>
              {[payload.institution_name, payload.education_level, payload.field_of_study]
                .filter(Boolean)
                .join(" - ") || "Grade conversion summary"}
            </CardDescription>
          </div>
          {payload.target_country ? (
            <Badge variant="secondary" className="gap-1">
              <Target className="h-3 w-3" aria-hidden />
              {payload.target_country}
            </Badge>
          ) : null}
        </div>
      </CardHeader>

      <CardContent className="space-y-5 pt-5">
        <div className="grid gap-4 sm:grid-cols-3">
          {metrics.map((metric) => (
            <div
              key={metric.key}
              className="rounded-lg border border-border bg-background p-3"
            >
              <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                {metric.icon}
                {metric.system}
              </div>
              <div className="mt-2 flex items-baseline gap-1.5">
                <span className="text-2xl font-semibold tabular-nums">{metric.value}</span>
                <span className="text-xs text-muted-foreground">{metric.scaleHint}</span>
              </div>
              <Progress
                value={metric.percent}
                markers={metric.markers}
                indicatorClassName={metric.tone}
                className="mt-2.5"
                aria-label={`${metric.system} standing`}
              />
              <p className="mt-2 text-xs text-muted-foreground">{metric.caption}</p>
            </div>
          ))}
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg bg-muted/50 p-3 text-xs sm:grid-cols-4">
          <Stat label="Normalised" value={`${conversion.normalized_percentage.toFixed(1)}%`} />
          <Stat
            label="Reported"
            value={`${conversion.source_value}${sourceSuffix(conversion.source_scale)}`}
          />
          <Stat
            label="Backlogs"
            value={String(payload.backlogs)}
            tone={payload.backlogs > 0 ? "text-amber-600 dark:text-amber-400" : undefined}
          />
          <Stat
            label="Subjects"
            value={payload.subject_count ? String(payload.subject_count) : "-"}
          />
        </dl>

        {payload.eligibility_notes.length > 0 ? (
          <ul className="space-y-2">
            {payload.eligibility_notes.map((note, index) => (
              <li key={index} className="flex gap-2 text-sm leading-relaxed">
                <Info
                  className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
                  aria-hidden
                />
                <span>{note}</span>
              </li>
            ))}
          </ul>
        ) : null}

        <details className="group rounded-lg border border-border p-3 text-xs">
          <summary className="cursor-pointer select-none font-medium text-muted-foreground transition-colors hover:text-foreground">
            How this was calculated
          </summary>
          <div className="mt-3 space-y-2 text-muted-foreground">
            <p>
              <span className="font-medium text-foreground">
                Modified Bavarian Formula
              </span>{" "}
              - V = 1 + 3 x ((Nmax - Nd) / (Nmax - Nmin))
            </p>
            <code className="block rounded bg-muted px-2 py-1.5 font-mono text-[11px] text-foreground">
              {conversion.german_formula}
            </code>
            {conversion.assumptions.length > 0 ? (
              <ul className="space-y-1">
                {conversion.assumptions.map((assumption, index) => (
                  <li key={index} className="flex gap-1.5">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                    <span>{assumption}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn("font-semibold tabular-nums", tone)}>{value}</dd>
    </div>
  );
}

function sourceSuffix(scale: GradeConversion["source_scale"]): string {
  switch (scale) {
    case "percentage":
      return "%";
    case "us_4_0":
      return "/4.0";
    case "scale_5_0":
      return "/5.0";
    case "scale_10_0":
      return "/10.0";
    case "scale_20_0":
      return "/20.0";
    default:
      return "";
  }
}
