"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowUp,
  Bot,
  Check,
  Compass,
  Copy,
  FileText,
  Loader2,
  Paperclip,
  RotateCcw,
  Square,
  TriangleAlert,
  UploadCloud,
  X,
} from "lucide-react";

import { DiagnosticCard } from "@/components/chat/diagnostic-card";
import { UniversityMatchGrid } from "@/components/chat/university-match-grid";
import { SlotChecklist } from "@/components/chat/slot-checklist";
import { Button } from "@/components/ui/button";
import { authHeader } from "@/lib/auth-headers";
import { readEventStream } from "@/lib/sse";
import { cn } from "@/lib/utils";
import type {
  ChatMessage,
  DiagnosticCardPayload,
  ExtractedTranscript,
  OnboardingSlots,
  SlotName,
  SlotUpdatePayload,
  UniversityMatchesPayload,
} from "@/types/chat";
import { SLOT_ORDER } from "@/types/chat";

const ACCEPTED_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
const MAX_FILE_BYTES = 10 * 1024 * 1024;

/**
 * Hero openers. Phrased as a student would actually open, not as prompts -
 * each one lands on a different slot the interview needs anyway, so tapping
 * one is a real head start rather than a demo.
 */
const OPENERS = [
  "I did a BA in English Literature",
  "I want to study in Australia",
  "What can I do with my 3.2 GPA?",
  "Read my transcript for me",
];
const SESSION_KEY = "saa.session_id";

const EMPTY_SLOTS: OnboardingSlots = {
  full_name: null,
  nationality: null,
  cgpa: null,
  field_of_study: null,
  education_level: null,
  target_country: null,
  extra_countries: [],
  language_score: null,
};

const WELCOME: ChatMessage = {
  id: "welcome",
  role: "assistant",
  content:
    "Hi, I am Vera, your study-abroad advisor. Tell me a little about yourself to get started - or drop your transcript straight into this chat and I will read it for you.",
};

let idCounter = 0;
const nextId = () => `m${Date.now().toString(36)}-${idCounter++}`;

interface ChatWindowProps {
  className?: string;
  /** A saved conversation to show, chosen from the history sidebar. */
  threadId?: string | null;
  /** Fired when the backend starts (or resumes) saving to a thread. */
  onThreadChange?: (threadId: string | null) => void;
}

export function ChatWindow({
  className,
  threadId,
  onThreadChange,
}: ChatWindowProps) {
  const [messages, setMessages] = React.useState<ChatMessage[]>([WELCOME]);
  const [input, setInput] = React.useState("");
  const [attachment, setAttachment] = React.useState<File | null>(null);
  const [attachmentError, setAttachmentError] = React.useState<string | null>(null);
  const [isStreaming, setIsStreaming] = React.useState(false);
  const [status, setStatus] = React.useState<string | null>(null);
  // The backend names which step it is on. Kept beside the message so the
  // indicator can show progress through the pipeline, not just that it is busy.
  const [stage, setStage] = React.useState<string | null>(null);
  const [isDragging, setIsDragging] = React.useState(false);
  const [slots, setSlots] = React.useState<OnboardingSlots>(EMPTY_SLOTS);
  const [missing, setMissing] = React.useState<SlotName[]>(SLOT_ORDER);
  const [pendingConfirmation, setPendingConfirmation] = React.useState<SlotName[]>([]);
  const [unlocked, setUnlocked] = React.useState(false);
  const [isRestored, setIsRestored] = React.useState(false);

  const sessionIdRef = React.useRef<string | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  // Nested dragenter/dragleave pairs fire per child element; counting them is
  // what keeps the drop overlay from flickering.
  const dragDepth = React.useRef(0);

  // Restore the stored session on mount. The session id lives in localStorage
  // and is therefore shared by every tab, so without this a reopened tab shows
  // an empty profile while the backend keeps answering from a conversation the
  // student cannot see.
  React.useEffect(() => {
    const stored = window.localStorage.getItem(SESSION_KEY);
    if (!stored) return;
    sessionIdRef.current = stored;

    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`/api/session/${stored}`, { cache: "no-store" });
        if (cancelled) return;
        if (!response.ok) {
          // Expired or unknown (server restart, TTL): start clean rather than
          // continuing against a session that no longer exists.
          window.localStorage.removeItem(SESSION_KEY);
          sessionIdRef.current = null;
          return;
        }
        const snapshot = await response.json();
        if (cancelled) return;

        const restored: ChatMessage[] = (snapshot.messages ?? [])
          .filter((m: { role: string }) => m.role === "user" || m.role === "assistant")
          .map((m: { role: "user" | "assistant"; content: string }, index: number) => ({
            id: `restored-${index}`,
            role: m.role,
            content: m.content,
          }))
          .filter((m: ChatMessage) => m.content.trim().length > 0);

        if (restored.length === 0) return;

        // Re-attach the report, and the matches it unlocked, to the last
        // assistant turn so neither is lost on a reload.
        if (snapshot.last_card) {
          for (let i = restored.length - 1; i >= 0; i -= 1) {
            if (restored[i].role === "assistant") {
              restored[i] = {
                ...restored[i],
                card: snapshot.last_card,
                matches: snapshot.last_matches?.length
                  ? {
                      session_id: snapshot.session_id,
                      query: "",
                      matches: snapshot.last_matches,
                    }
                  : undefined,
              };
              break;
            }
          }
        }

        setMessages([WELCOME, ...restored]);
        setSlots(snapshot.slots ?? EMPTY_SLOTS);
        setMissing(snapshot.missing ?? SLOT_ORDER);
        setPendingConfirmation(snapshot.pending_confirmation ?? []);
        setUnlocked(Boolean(snapshot.diagnostics_unlocked));
        setIsRestored(true);
      } catch {
        // Offline or backend down: the greeting alone is a fine starting point.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const startNewConversation = React.useCallback(async () => {
    const previous = sessionIdRef.current;
    abortRef.current?.abort();
    sessionIdRef.current = null;
    window.localStorage.removeItem(SESSION_KEY);
    setMessages([WELCOME]);
    setSlots(EMPTY_SLOTS);
    setMissing(SLOT_ORDER);
    setPendingConfirmation([]);
    setUnlocked(false);
    setInput("");
    setAttachment(null);
    setAttachmentError(null);
    setIsRestored(false);
    if (previous) {
      // Best effort: the local reset is what matters to the student.
      try {
        await fetch(`/api/session/${previous}`, { method: "DELETE" });
      } catch {
        /* ignore */
      }
    }
  }, []);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, isStreaming, status]);

  React.useEffect(() => () => abortRef.current?.abort(), []);

  const patchMessage = React.useCallback(
    (id: string, patch: Partial<ChatMessage> | ((prev: ChatMessage) => Partial<ChatMessage>)) => {
      setMessages((prev) =>
        prev.map((message) =>
          message.id === id
            ? { ...message, ...(typeof patch === "function" ? patch(message) : patch) }
            : message,
        ),
      );
    },
    [],
  );

  const validateFile = React.useCallback((file: File): string | null => {
    const looksLikeTranscript =
      ACCEPTED_TYPES.includes(file.type) || /\.(pdf|png|jpe?g|webp)$/i.test(file.name);
    if (!looksLikeTranscript) return "Please upload a PDF, PNG or JPG transcript.";
    if (file.size > MAX_FILE_BYTES) return "That file is larger than 10 MB.";
    if (file.size === 0) return "That file appears to be empty.";
    return null;
  }, []);

  const acceptFile = React.useCallback(
    (file: File | null | undefined) => {
      if (!file) return;
      const error = validateFile(file);
      setAttachmentError(error);
      setAttachment(error ? null : file);
    },
    [validateFile],
  );

  // Replay a saved conversation when one is chosen in the sidebar.
  //
  // Read-only by design: this restores what was said, not the slot state
  // behind it, so the composer is still live but the diagnostic card and the
  // profile are not reconstructed. Rebuilding those from message text would
  // mean re-deriving a profile from its own transcript, which is exactly the
  // guesswork the slot barrier exists to avoid.
  React.useEffect(() => {
    if (!threadId) return;
    let cancelled = false;

    (async () => {
      try {
        const headers = await authHeader();
        if (!headers) return;
        const response = await fetch(`/api/history/threads/${threadId}`, {
          headers,
        });
        if (!response.ok || cancelled) return;
        const data = await response.json();

        // Saved rows come back in order. A `system` row carries a rendered
        // artifact - the diagnostic report or the course matches - stored as
        // it was sent, so it is attached to the preceding assistant turn and
        // replayed verbatim rather than rebuilt from the transcript.
        const restored: ChatMessage[] = [];
        for (const row of data.messages ?? []) {
          if (row.sender === "system") {
            const previous = restored[restored.length - 1];
            if (!previous || !row.payload) continue;
            if (row.kind === "diagnostic_card") {
              previous.card = row.payload as DiagnosticCardPayload;
            } else if (row.kind === "university_matches") {
              previous.matches = row.payload as UniversityMatchesPayload;
            }
            continue;
          }
          restored.push({
            id: `saved-${row.id}`,
            role: row.sender === "user" ? "user" : "assistant",
            content: row.content,
          });
        }

        if (restored.length > 0) {
          setMessages([WELCOME, ...restored]);
          // The report is on screen again, so the checklist should not still
          // say the barrier is closed.
          if (restored.some((m) => m.card)) setUnlocked(true);
        }
      } catch (error) {
        console.error("Could not open that conversation:", error);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [threadId]);

  const send = React.useCallback(async () => {
    const text = input.trim();
    const file = attachment;
    if ((!text && !file) || isStreaming) return;

    const userMessage: ChatMessage = {
      id: nextId(),
      role: "user",
      content: text,
      fileName: file?.name,
    };
    const assistantId = nextId();

    setMessages((prev) => [
      ...prev,
      userMessage,
      { id: assistantId, role: "assistant", content: "", pending: true },
    ]);
    setInput("");
    setAttachment(null);
    setAttachmentError(null);
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await postTurn({
        message: text,
        file,
        sessionId: sessionIdRef.current,
        signal: controller.signal,
      });

      // The backend creates the thread on the first message and names it in
      // this header, so the sidebar can highlight it without a second request.
      const startedThread = response.headers.get("X-Thread-Id");
      if (startedThread) onThreadChange?.(startedThread);

      if (!response.ok || !response.body) {
        const detail = await readErrorDetail(response);
        patchMessage(assistantId, { pending: false, error: detail });
        return;
      }

      for await (const event of readEventStream(response.body, controller.signal)) {
        switch (event.event) {
          case "text_delta":
            patchMessage(assistantId, (prev) => ({
              content: prev.content + event.data.text,
              pending: false,
            }));
            setStatus(null);
            setStage(null);
            break;

          case "status":
            setStatus(event.data.message);
            setStage(typeof event.data.stage === "string" ? event.data.stage : null);
            break;

          case "slot_update":
            applySlotUpdate(event.data);
            break;

          case "transcript_parsed":
            patchMessage(assistantId, { transcript: event.data as ExtractedTranscript });
            break;

          case "diagnostic_card":
            patchMessage(assistantId, { card: event.data });
            setUnlocked(true);
            break;

          case "university_matches":
            patchMessage(assistantId, { matches: event.data });
            setStatus(null);
            setStage(null);
            break;

          case "error":
            patchMessage(assistantId, (prev) => ({
              pending: false,
              // A recoverable error (a bad scan) is shown beside the reply that
              // still follows it; a fatal one replaces the bubble.
              error: prev.error ? `${prev.error} ${event.data.message}` : event.data.message,
            }));
            break;

          case "done":
            sessionIdRef.current = event.data.session_id;
            window.localStorage.setItem(SESSION_KEY, event.data.session_id);
            if (event.data.diagnostics_unlocked) setUnlocked(true);
            if (typeof window !== "undefined") {
              window.dispatchEvent(
                new CustomEvent("vera:turn_done", {
                  detail: { sessionId: event.data.session_id },
                }),
              );
            }
            break;
        }
      }

      patchMessage(assistantId, { pending: false });
    } catch (error) {
      if ((error as Error)?.name === "AbortError") {
        patchMessage(assistantId, (prev) => ({
          pending: false,
          content: prev.content || "(stopped)",
        }));
      } else {
        console.error(error);
        patchMessage(assistantId, {
          pending: false,
          error: "I could not reach the server. Please check your connection and try again.",
        });
      }
    } finally {
      setIsStreaming(false);
      setStatus(null);
      setStage(null);
      abortRef.current = null;
      textareaRef.current?.focus();
    }

    function applySlotUpdate(payload: SlotUpdatePayload) {
      setSlots(payload.slots);
      setMissing(payload.missing);
      setPendingConfirmation(payload.pending_confirmation);
      sessionIdRef.current = payload.session_id;
    }
  }, [attachment, input, isStreaming, onThreadChange, patchMessage]);

  const onDrop = React.useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      dragDepth.current = 0;
      setIsDragging(false);
      acceptFile(event.dataTransfer.files?.[0]);
    },
    [acceptFile],
  );

  const onPaste = React.useCallback(
    (event: React.ClipboardEvent) => {
      const file = Array.from(event.clipboardData.files)[0];
      if (file) {
        event.preventDefault();
        acceptFile(file);
      }
    },
    [acceptFile],
  );

  const canSend = (input.trim().length > 0 || attachment !== null) && !isStreaming;

  return (
    <div
      className={cn("relative flex h-full min-h-0 gap-4", className)}
      onDragEnter={(event) => {
        if (!event.dataTransfer.types.includes("Files")) return;
        dragDepth.current += 1;
        setIsDragging(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={() => {
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setIsDragging(false);
      }}
      onDrop={onDrop}
    >
      <div className="glass flex min-w-0 flex-1 flex-col overflow-hidden rounded-[18px]">
        <header className="flex items-center gap-3 border-b border-hairline px-5 py-4">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-cyan text-primary-foreground">
            <Bot className="h-4 w-4" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[16px] font-semibold leading-[1.4] text-ink">
              Vera - Study Abroad Advisor
            </p>
            <p className="caption-upper text-muted-foreground">
              {unlocked
                ? "Diagnostics unlocked"
                : `${SLOT_ORDER.length - missing.length} of ${SLOT_ORDER.length} details collected`}
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => void startNewConversation()}
            disabled={isStreaming}
            title="Clear this conversation and start fresh"
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            New chat
          </Button>
        </header>

        {isRestored ? (
          <p className="border-b border-border bg-muted/40 px-4 py-2 text-xs text-muted-foreground">
            Continuing your earlier conversation. Choose &ldquo;New chat&rdquo; to start over.
          </p>
        ) : null}

        <div
          ref={scrollRef}
          className="flex-1 space-y-4 overflow-y-auto px-4 py-5"
          aria-live="polite"
        >
          {/* Hero state. Only while the conversation is still just the
              greeting - once a student has said anything, the transcript is
              the thing worth the space. */}
          {messages.length <= 1 && !isStreaming ? (
            <div className="relative flex min-h-full flex-col items-center justify-center px-4 py-10 text-center">
              <div aria-hidden className="light-cone" />
              <h2 className="display-lg rise-in relative text-ink">Where shall we begin?</h2>
              <p
                className="rise-in relative mt-4 max-w-md text-[15px] leading-[1.65] text-muted-ink"
                style={{ ["--rise-delay" as string]: "90ms" }}
              >
                Tell me where you studied and what you are aiming for, or drop
                your transcript in and I will read it.
              </p>
              <div
                className="rise-in relative mt-7 flex flex-wrap justify-center gap-2"
                style={{ ["--rise-delay" as string]: "180ms" }}
              >
                {OPENERS.map((opener) => (
                  <button
                    key={opener}
                    type="button"
                    onClick={() => {
                      setInput(opener);
                      textareaRef.current?.focus();
                    }}
                    className="glass cursor-pointer rounded-full px-3.5 py-2 text-[13px] text-muted-ink transition-colors hover:text-ink"
                  >
                    {opener}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))
          )}

          {status ? <ThinkingIndicator status={status} stage={stage} /> : null}
        </div>

        <div className="border-t border-hairline p-3">
          {/* Attached-transcript pill. Emerald, because in this palette
              emerald is the "we have this, it is confirmed" colour. */}
          {attachment ? (
            <div className="mb-2 flex items-center gap-2 rounded-full border border-emerald/30 bg-emerald/10 px-3 py-1.5 text-xs text-ink">
              <FileText className="h-3.5 w-3.5 shrink-0 text-emerald" aria-hidden />
              <span className="truncate font-medium">{attachment.name}</span>
              <span className="metric shrink-0 text-muted-ink">
                {(attachment.size / 1024).toFixed(0)} KB
              </span>
              <button
                type="button"
                onClick={() => setAttachment(null)}
                className="ml-auto cursor-pointer rounded-full p-0.5 text-muted-ink transition-colors hover:text-ink"
                aria-label="Remove attachment"
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          ) : null}

          {attachmentError ? (
            <p className="mb-2 flex items-center gap-1.5 text-xs text-destructive">
              <TriangleAlert className="h-3.5 w-3.5" aria-hidden />
              {attachmentError}
            </p>
          ) : null}

          <div className="flex items-end gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.webp"
              className="hidden"
              onChange={(event) => {
                acceptFile(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming}
              aria-label="Attach transcript"
            >
              <Paperclip className="h-4 w-4" aria-hidden />
            </Button>

            <textarea
              ref={textareaRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onPaste={onPaste}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
              rows={1}
              maxLength={4000}
              placeholder="Tell me about yourself, or drop your transcript here..."
              className="max-h-40 min-h-[44px] flex-1 resize-none rounded-[12px] border border-border bg-card px-4 py-3 text-[16px] leading-[1.5] text-ink outline-none transition-colors placeholder:text-faint focus:border-cyan"
            />

            {isStreaming ? (
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => abortRef.current?.abort()}
                aria-label="Stop generating"
              >
                <Square className="h-3.5 w-3.5" aria-hidden />
              </Button>
            ) : (
              <Button
                type="button"
                size="icon"
                onClick={() => void send()}
                disabled={!canSend}
                aria-label="Send message"
              >
                <ArrowUp className="h-4 w-4" aria-hidden />
              </Button>
            )}
          </div>
        </div>
      </div>

      <SlotChecklist
        slots={slots}
        missing={missing}
        pendingConfirmation={pendingConfirmation}
        unlocked={unlocked}
        className="hidden w-64 shrink-0 lg:flex"
      />

      {isDragging ? (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-primary/5 backdrop-blur-[1px]">
          <div className="flex flex-col items-center gap-2 text-primary">
            <UploadCloud className="h-8 w-8" aria-hidden />
            <p className="text-sm font-medium">Drop your transcript to have it read</p>
            <p className="text-xs opacity-70">PDF, PNG or JPG - up to 10 MB</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Staged thinking indicator.
 *
 * The stages are the pipeline the backend actually runs, and the active one
 * comes from the `stage` field on its own status events - so this reports
 * real progress rather than animating through a script on a timer. An
 * unrecognised stage still shows the message, just without the track.
 */
const STAGES = [
  { key: "parsing", label: "Reading transcript" },
  { key: "understanding", label: "Understanding" },
  { key: "diagnosing", label: "Diagnosing" },
  { key: "matching", label: "Matching programmes" },
] as const;

function ThinkingIndicator({
  status,
  stage,
}: {
  status: string;
  stage: string | null;
}) {
  const active = STAGES.findIndex((s) => s.key === stage);

  return (
    <div className="glass flex w-fit items-center gap-3 rounded-full px-3.5 py-2">
      <span aria-hidden className="flex items-end gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="wave-dot h-1.5 w-1.5 rounded-full bg-cyan"
            style={{ animationDelay: `${i * 160}ms` }}
          />
        ))}
      </span>

      <span className="text-xs text-muted-ink">{status}</span>

      {active >= 0 ? (
        <span aria-hidden className="ml-1 flex items-center gap-1">
          {STAGES.map((s, i) => (
            <span
              key={s.key}
              title={s.label}
              className={cn(
                "h-1 rounded-full transition-all duration-300",
                i < active && "w-3 bg-emerald/60",
                i === active && "w-5 bg-cyan",
                i > active && "w-3 bg-hairline-strong",
              )}
            />
          ))}
        </span>
      ) : null}

      {/* The stage track is decorative; the message above it is what screen
          readers announce, and the scroll region is already aria-live. */}
      <span className="sr-only">
        {active >= 0 ? `Step ${active + 1} of ${STAGES.length}` : ""}
      </span>
    </div>
  );
}

/**
 * Copy and explore, under each of Vera's replies.
 *
 * Both do something real: copy puts the reply on the clipboard, explore opens
 * the catalogue browser. Nothing here is a placeholder.
 */
/**
 * Placeholder for a reply that has been requested but has not started.
 *
 * Three lines of decreasing width, which is roughly the shape of Vera's
 * answers - a short acknowledgement and a question. `aria-hidden` with a
 * `sr-only` label: a screen reader should hear "writing a reply", not three
 * meaningless boxes.
 */
function MessageSkeleton() {
  return (
    <div className="flex w-[min(22rem,60vw)] flex-col gap-2 py-0.5">
      <span className="sr-only">Vera is writing a reply</span>
      <span aria-hidden className="skeleton-line w-full" />
      <span
        aria-hidden
        className="skeleton-line w-[85%]"
        style={{ animationDelay: "120ms" }}
      />
      <span
        aria-hidden
        className="skeleton-line w-[55%]"
        style={{ animationDelay: "240ms" }}
      />
    </div>
  );
}

function MessageActions({ content }: { content: string }) {
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <div className="flex items-center gap-1 pl-1">
      <button
        type="button"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(content);
            setCopied(true);
          } catch {
            // Clipboard access can be refused outright; silently leaving the
            // label alone is honest - it never claims a copy that did not
            // happen.
          }
        }}
        className="flex cursor-pointer items-center gap-1.5 rounded-[8px] px-2 py-1 text-xs text-faint transition-colors hover:text-ink"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-emerald" aria-hidden />
        ) : (
          <Copy className="h-3.5 w-3.5" aria-hidden />
        )}
        {copied ? "Copied" : "Copy"}
      </button>

      <Link
        href="/discovery"
        className="flex items-center gap-1.5 rounded-[8px] px-2 py-1 text-xs text-faint transition-colors hover:text-ink"
      >
        <Compass className="h-3.5 w-3.5" aria-hidden />
        Browse catalogue
      </Link>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex flex-col gap-2", isUser ? "items-end" : "items-start")}>
      {message.content || message.pending ? (
        <div
          className={cn(
            "max-w-[85%] whitespace-pre-wrap rounded-[14px] px-4 py-3 text-[15px] leading-[1.6]",
            isUser
              // The student's own words carry the accent; Vera speaks on glass.
              ? "rounded-br-[4px] bg-cyan/15 text-ink ring-1 ring-cyan/25"
              : "glass rounded-bl-[4px] text-ink",
          )}
        >
          {/* Nothing has arrived yet: show the shape of a reply rather than an
              empty bubble, which reads as a stall. Once the first token lands
              this is replaced by the real text, so the two never show at once. */}
          {message.pending && !message.content ? (
            <MessageSkeleton />
          ) : (
            <>
              {message.content}
              {message.pending ? (
                <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-current align-text-bottom" />
              ) : null}
            </>
          )}
        </div>
      ) : null}

      {message.fileName ? (
        <div className="flex items-center gap-1.5 rounded-[8px] border border-border bg-surface-soft px-2.5 py-1.5 text-xs text-muted-foreground">
          <FileText className="h-3.5 w-3.5" aria-hidden />
          {message.fileName}
        </div>
      ) : null}

      {/* Action footer. Only under a finished reply from Vera - there is
          nothing to copy from a half-streamed bubble, and copying your own
          message back to yourself is not a thing anyone wants. */}
      {!isUser && message.content && !message.pending ? (
        <MessageActions content={message.content} />
      ) : null}

      {message.transcript ? <TranscriptSummary transcript={message.transcript} /> : null}

      {message.card ? (
        <div className="w-full max-w-[95%]">
          <DiagnosticCard payload={message.card} />
        </div>
      ) : null}

      {message.matches ? (
        <div className="w-full max-w-[95%]">
          <UniversityMatchGrid payload={message.matches} />
        </div>
      ) : null}

      {message.error ? (
        <p className="flex max-w-[85%] items-start gap-1.5 rounded-[8px] border border-destructive/40 bg-destructive/[0.06] px-3 py-2 text-xs text-destructive">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {message.error}
        </p>
      ) : null}
    </div>
  );
}

function TranscriptSummary({ transcript }: { transcript: ExtractedTranscript }) {
  const facts = [
    transcript.institution_name,
    transcript.cumulative_gpa !== null
      ? `CGPA ${transcript.cumulative_gpa}${
          transcript.gpa_scale_max ? `/${transcript.gpa_scale_max}` : ""
        }${transcript.cumulative_gpa_computed ? " (averaged)" : ""}`
      : transcript.percentage !== null
        ? `${transcript.percentage}%`
        : null,
    transcript.subjects.length ? `${transcript.subjects.length} subjects` : null,
    transcript.backlogs ? `${transcript.backlogs} backlog(s)` : null,
  ].filter(Boolean) as string[];

  return (
    <div className="flex max-w-[85%] flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5 rounded-[8px] border border-border bg-surface-soft px-3 py-2 text-xs text-muted-foreground">
        <FileText className="h-3.5 w-3.5" aria-hidden />
        <span className="font-medium text-foreground">Transcript read</span>
        {facts.map((fact) => (
          <span key={fact} className="rounded bg-background px-1.5 py-0.5">
            {fact}
          </span>
        ))}
      </div>

      {/* The parser already recorded these - that a grade was averaged rather
          than read, that a page was unreadable - and they were being dropped
          on the floor. A figure the document never printed must not be shown
          as though it had been. */}
      {transcript.warnings.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {transcript.warnings.map((warning) => (
            <li
              key={warning}
              className="flex items-start gap-1.5 rounded-[8px] border border-amber/25 bg-amber/10 px-3 py-2 text-xs leading-[1.5] text-muted-ink"
            >
              <TriangleAlert
                className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber"
                aria-hidden
              />
              {warning}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

async function postTurn({
  message,
  file,
  sessionId,
  signal,
}: {
  message: string;
  file: File | null;
  sessionId: string | null;
  signal: AbortSignal;
}): Promise<Response> {
  // Read per request rather than once: the access token is short-lived, and a
  // header captured at mount would start failing partway through a session.
  const auth = (await authHeader()) ?? {};

  if (file) {
    const form = new FormData();
    form.append("message", message);
    form.append("file", file);
    if (sessionId) form.append("session_id", sessionId);
    // No Content-Type: the browser sets it with the multipart boundary, and
    // overriding it makes the body unparseable.
    return fetch("/api/chat/stream", {
      method: "POST",
      headers: auth,
      body: form,
      signal,
    });
  }

  return fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...auth },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  });
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Non-JSON error bodies fall through to the generic message.
  }
  return `The server responded with ${response.status}. Please try again.`;
}
