"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 0-100. Values outside the range are clamped. */
  value: number;
  indicatorClassName?: string;
  /** Optional reference marks (0-100) drawn across the track. */
  markers?: number[];
}

/**
 * Dependency-free progress bar with the shadcn look, plus threshold markers so
 * a grade can be shown against admission cut-offs rather than in isolation.
 */
const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value, indicatorClassName, markers, ...props }, ref) => {
    const clamped = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
    return (
      <div
        ref={ref}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clamped)}
        className={cn(
          "relative h-2 w-full overflow-hidden rounded-full bg-secondary",
          className,
        )}
        {...props}
      >
        <div
          className={cn(
            "h-full rounded-full bg-primary transition-[width] duration-700 ease-out",
            indicatorClassName,
          )}
          style={{ width: `${clamped}%` }}
        />
        {markers?.map((mark) => (
          <span
            key={mark}
            aria-hidden
            className="absolute top-0 h-full w-px bg-background/70"
            style={{ left: `${Math.max(0, Math.min(100, mark))}%` }}
          />
        ))}
      </div>
    );
  },
);
Progress.displayName = "Progress";

export { Progress };
