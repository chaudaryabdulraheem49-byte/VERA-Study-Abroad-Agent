import type { ServerEvent } from "@/types/chat";

/**
 * Parse a `text/event-stream` body into typed events.
 *
 * `EventSource` cannot be used here: the chat endpoint is a POST that may carry
 * a multipart file, so we read the fetch body ourselves. Frames are separated
 * by a blank line and may arrive split across chunk boundaries, which is what
 * the carry-over buffer handles.
 */
export async function* readEventStream(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<ServerEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const abort = () => void reader.cancel().catch(() => {});
  signal?.addEventListener("abort", abort);

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Tolerate CRLF from proxies that rewrite line endings.
      for (
        let boundary = findBoundary(buffer);
        boundary !== -1;
        boundary = findBoundary(buffer)
      ) {
        const frame = buffer.slice(0, boundary);
        const separatorLength = buffer.startsWith("\r\n\r\n", boundary) ? 4 : 2;
        buffer = buffer.slice(boundary + separatorLength);
        const parsed = parseFrame(frame);
        if (parsed) yield parsed;
      }
    }

    const tail = parseFrame(buffer);
    if (tail) yield tail;
  } finally {
    signal?.removeEventListener("abort", abort);
    reader.releaseLock();
  }
}

function findBoundary(buffer: string): number {
  const lf = buffer.indexOf("\n\n");
  const crlf = buffer.indexOf("\r\n\r\n");
  if (lf === -1) return crlf;
  if (crlf === -1) return lf;
  return Math.min(lf, crlf);
}

function parseFrame(frame: string): ServerEvent | null {
  const trimmed = frame.trim();
  if (!trimmed) return null;

  let name: string | null = null;
  const dataLines: string[] = [];

  for (const rawLine of trimmed.split(/\r?\n/)) {
    const line = rawLine.trimEnd();
    if (line.startsWith(":")) continue; // keep-alive comment
    if (line.startsWith("event:")) {
      name = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (!name || dataLines.length === 0) return null;

  try {
    return { event: name, data: JSON.parse(dataLines.join("\n")) } as ServerEvent;
  } catch {
    // A malformed frame must not tear down the whole stream.
    console.warn("Discarding unparseable SSE frame", { name });
    return null;
  }
}
