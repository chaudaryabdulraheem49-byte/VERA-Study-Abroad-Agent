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
        "flex-col gap-5 rounded-[12px] border border-border bg-card p-5",
        className,
      )}
      aria-label="Onboarding progress"
    >
      <div>
        <div className="flex items-center justify-between gap-2">
          <h2 className="caption-upper text-muted-foreground">Your profile</h2>
          <span className="text-xs tabular-nums text-muted-foreground">
            {filledCount}/{SLOT_ORDER.length}
          </span>
        </div>
        <Progress
          value={percent}
          className="mt-2"
          indicatorClassName={unlocked ? "bg-success" : undefined}
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
                    ? "bg-ochre text-on-fill"
                    : isFilled
                      ? "bg-mint text-on-fill"
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
                <span className="caption-upper block text-muted-foreground">{SLOT_LABELS[slot]}</span>
                <span
                  className={cn(
                    "block truncate font-medium",
                    isFilled ? "font-medium text-ink" : "text-muted-foreground/70",
                  )}
                  title={value ?? undefined}
                >
                  {value ?? "Not provided yet"}
                </span>
                {needsConfirmation ? (
                  <span className="text-ink">
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
          "mt-auto flex items-start gap-2 rounded-[8px] border p-3 text-xs",
          unlocked
            ? "border-transparent bg-mint text-on-fill"
            : "border-border bg-surface-soft text-muted-foreground",
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
