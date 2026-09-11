"use client";

import { Check, CircleDashed, HelpCircle, Lock, LockOpen } from "lucide-react";

import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { OnboardingSlots, SlotName } from "@/types/chat";
import { SLOT_LABELS, SLOT_ORDER, describeSlot } from "@/types/chat";

interface SlotChecklistProps {
  slots: OnboardingSlots;
  missing: SlotName[];
  pendingConfirmation: SlotName[];
  unlocked: boolean;
  className?: string;
}

/**
 * Makes the six-field barrier visible: what has been captured, what came from
 * the transcript and still needs confirming, and what is left to unlock the
 * diagnostic report.
 */
export function SlotChecklist({
  slots,
  missing,
  pendingConfirmation,
  unlocked,
  className,
}: SlotChecklistProps) {
  const filledCount = SLOT_ORDER.length - missing.length;
  const percent = (filledCount / SLOT_ORDER.length) * 100;

  return (
    <aside
      className={cn(
        "flex-col gap-4 rounded-xl border border-border bg-card p-4",
        className,
      )}
      aria-label="Onboarding progress"
    >
      <div>
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Your profile</h2>
          <span className="text-xs tabular-nums text-muted-foreground">
            {filledCount}/{SLOT_ORDER.length}
          </span>
        </div>
        <Progress
          value={percent}
          className="mt-2"
          indicatorClassName={unlocked ? "bg-emerald-500" : undefined}
          aria-label="Onboarding completion"
        />
      </div>

      <ul className="space-y-2.5">
        {SLOT_ORDER.map((slot) => {
          const value = describeSlot(slot, slots);
          const needsConfirmation = pendingConfirmation.includes(slot);
          const isFilled = !missing.includes(slot);

          return (
            <li key={slot} className="flex items-start gap-2 text-xs">
              <span
                className={cn(
                  "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full",
                  needsConfirmation
                    ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400"
                    : isFilled
                      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400"
                      : "text-muted-foreground",
                )}
                aria-hidden
              >
                {needsConfirmation ? (
                  <HelpCircle className="h-3 w-3" />
                ) : isFilled ? (
                  <Check className="h-3 w-3" />
                ) : (
                  <CircleDashed className="h-3 w-3" />
                )}
              </span>
              <span className="min-w-0">
                <span className="block text-muted-foreground">{SLOT_LABELS[slot]}</span>
                <span
                  className={cn(
                    "block truncate font-medium",
                    isFilled ? "text-foreground" : "text-muted-foreground/60",
                  )}
                  title={value ?? undefined}
                >
                  {value ?? "Not provided yet"}
                </span>
                {needsConfirmation ? (
                  <span className="text-amber-600 dark:text-amber-400">
                    From your transcript - please confirm
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>

      <div
        className={cn(
          "mt-auto flex items-start gap-2 rounded-lg p-2.5 text-xs",
          unlocked
            ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300"
            : "bg-muted text-muted-foreground",
        )}
      >
        {unlocked ? (
          <LockOpen className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        ) : (
          <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        )}
        <span>
          {unlocked
            ? "Smart diagnostics unlocked - your grade conversions are in the chat."
            : `All ${SLOT_ORDER.length} details are needed before I can run your diagnostic report.`}
        </span>
      </div>
    </aside>
  );
}
