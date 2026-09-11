"use client";

import * as React from "react";
import {
  ArrowUp,
  Bot,
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
import { SlotChecklist } from "@/components/chat/slot-checklist";
import { Button } from "@/components/ui/button";
import { readEventStream } from "@/lib/sse";
import { cn } from "@/lib/utils";
import type {
  ChatMessage,
  ExtractedTranscript,
  OnboardingSlots,
  SlotName,
  SlotUpdatePayload,
} from "@/types/chat";
import { SLOT_ORDER } from "@/types/chat";

const ACCEPTED_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const SESSION_KEY = "saa.session_id";

const EMPTY_SLOTS: OnboardingSlots = {
  full_name: null,
  nationality: null,
  cgpa: null,
  field_of_study: null,
  education_level: null,
  target_country: null,
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

export function ChatWindow({ className }: { className?: string }) {
  const [messages, setMessages] = React.useState<ChatMessage[]>([WELCOME]);
  const [input, setInput] = React.useState("");
  const [attachment, setAttachment] = React.useState<File | null>(null);
  const [attachmentError, setAttachmentError] = React.useState<string | null>(null);
  const [isStreaming, setIsStreaming] = React.useState(false);
  const [status, setStatus] = React.useState<string | null>(null);
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

        // Re-attach the report to the last assistant turn so it is not lost.
        if (snapshot.last_card) {
          for (let i = restored.length - 1; i >= 0; i -= 1) {
            if (restored[i].role === "assistant") {
              restored[i] = { ...restored[i], card: snapshot.last_card };
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

      if (!response.ok || !response.body) {
        const detail = await readErrorDetail(response);
        patchMessage(assistantId, { pending: false, error: detail });
        return;
      }

      for await (const event of readEventStream(response.body, controller.signal)) {
        switch (event.event) {
          case "token":
            patchMessage(assistantId, (prev) => ({
              content: prev.content + event.data.text,
              pending: false,
            }));
            setStatus(null);
            break;

          case "status":
            setStatus(event.data.message);
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
      abortRef.current = null;
      textareaRef.current?.focus();
    }

    function applySlotUpdate(payload: SlotUpdatePayload) {
      setSlots(payload.slots);
      setMissing(payload.missing);
      setPendingConfirmation(payload.pending_confirmation);
      sessionIdRef.current = payload.session_id;
    }
  }, [attachment, input, isStreaming, patchMessage]);

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
      <div className="flex min-w-0 flex-1 flex-col rounded-xl border border-border bg-card">
        <header className="flex items-center gap-2 border-b border-border px-4 py-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Bot className="h-4 w-4" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">Vera - Study Abroad Advisor</p>
            <p className="text-xs text-muted-foreground">
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
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}

          {status ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              {status}
            </div>
          ) : null}
        </div>

        <div className="border-t border-border p-3">
          {attachment ? (
            <div className="mb-2 flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 text-xs">
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate font-medium">{attachment.name}</span>
              <span className="shrink-0 text-muted-foreground">
                {(attachment.size / 1024).toFixed(0)} KB
              </span>
              <button
                type="button"
                onClick={() => setAttachment(null)}
                className="ml-auto rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground"
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
              className="max-h-40 min-h-10 flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2.5 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-ring"
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

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex flex-col gap-2", isUser ? "items-end" : "items-start")}>
      {message.content || message.pending ? (
        <div
          className={cn(
            "max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
            isUser
              ? "rounded-br-sm bg-primary text-primary-foreground"
              : "rounded-bl-sm bg-muted text-foreground",
          )}
        >
          {message.content}
          {message.pending ? (
            <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-current align-text-bottom" />
          ) : null}
        </div>
      ) : null}

      {message.fileName ? (
        <div className="flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs text-muted-foreground">
          <FileText className="h-3.5 w-3.5" aria-hidden />
          {message.fileName}
        </div>
      ) : null}

      {message.transcript ? <TranscriptSummary transcript={message.transcript} /> : null}

      {message.card ? (
        <div className="w-full max-w-[95%]">
          <DiagnosticCard payload={message.card} />
        </div>
      ) : null}

      {message.error ? (
        <p className="flex max-w-[85%] items-start gap-1.5 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
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
        }`
      : transcript.percentage !== null
        ? `${transcript.percentage}%`
        : null,
    transcript.subjects.length ? `${transcript.subjects.length} subjects` : null,
    transcript.backlogs ? `${transcript.backlogs} backlog(s)` : null,
  ].filter(Boolean) as string[];

  return (
    <div className="flex max-w-[85%] flex-wrap items-center gap-1.5 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
      <FileText className="h-3.5 w-3.5" aria-hidden />
      <span className="font-medium text-foreground">Transcript read</span>
      {facts.map((fact) => (
        <span key={fact} className="rounded bg-background px-1.5 py-0.5">
          {fact}
        </span>
      ))}
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
  if (file) {
    const form = new FormData();
    form.append("message", message);
    form.append("file", file);
    if (sessionId) form.append("session_id", sessionId);
    return fetch("/api/chat/stream", { method: "POST", body: form, signal });
  }

  return fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
