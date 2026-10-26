"use client";

import * as React from "react";
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

export function SlotChecklist({
  slots,
  missing,
  pendingConfirmation,
  unlocked,
  className,
}: SlotChecklistProps) {
  const filledCount = SLOT_ORDER.length - missing.length;
  const percent = Math.round((filledCount / SLOT_ORDER.length) * 100);

  return (
    <aside
      className={cn("profile-panel", className)}
      aria-label="Your profile progress"
    >
      <div className="profile-heading">
        <div>
          <span className="panel-kicker">YOUR PROFILE</span>
          <h2>Signals</h2>
        </div>
        <span className="profile-count">
          {filledCount}/{SLOT_ORDER.length}
        </span>
      </div>

      <div className="profile-progress" aria-label={`Progress: ${percent}%`}>
        <span
          style={{
            width: `${percent}%`,
            background: unlocked ? "var(--signal)" : "var(--accent)",
          }}
        />
      </div>

      <ul className="profile-list">
        {SLOT_ORDER.map((slot) => {
          const value = describeSlot(slot, slots);
          const needsConfirmation = pendingConfirmation.includes(slot);
          const isFilled = !missing.includes(slot);

          return (
            <li key={slot}>
              <span
                className={cn(
                  "check-ring",
                  isFilled && "is-filled",
                  needsConfirmation && "is-pending",
                )}
                aria-hidden
              />
              <div>
                <b>{SLOT_LABELS[slot]}</b>
                <small
                  className={cn(
                    isFilled ? "!text-[var(--white)]" : "!text-[var(--muted)]",
                  )}
                  title={value ?? undefined}
                >
                  {value ?? "Not provided yet"}
                  {needsConfirmation && " (confirm in chat)"}
                </small>
              </div>
            </li>
          );
        })}
      </ul>

      <div className="profile-lock">
        <span style={{ color: unlocked ? "var(--signal)" : "var(--muted)" }}>
          {unlocked ? "✦" : "⌑"}
        </span>
        <p>
          {unlocked
            ? "Diagnostics unlocked — your calculated grade conversions are in the conversation."
            : `All ${SLOT_ORDER.length} details are needed before I can run your diagnostic report.`}
        </p>
      </div>
    </aside>
  );
}
