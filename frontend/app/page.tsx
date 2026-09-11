import { ChatWindow } from "@/components/chat/chat-window";

export default function Home() {
  return (
    <main className="mx-auto flex h-dvh max-w-6xl flex-col gap-4 p-4">
      <header className="shrink-0">
        <h1 className="text-lg font-semibold tracking-tight">
          Study Abroad Agent
        </h1>
        <p className="text-sm text-muted-foreground">
          Phase 1 - Smart Diagnostics: share your details or drop a transcript to
          see your grades converted to US, German and UK scales.
        </p>
      </header>
      <ChatWindow className="min-h-0 flex-1" />
    </main>
  );
}
