# Study Abroad Agent — Phase 1: Smart Diagnostics

Conversational study-abroad advisor. It collects six mandatory details through
chat, reads uploaded transcripts with GPT-4o Vision or LlamaParse, and converts
the student's grade into US, German and UK/ECTS equivalents with deterministic
arithmetic — streamed to a Next.js 15 client over SSE.

## Running it

```bash
# Backend (http://127.0.0.1:8000)
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows; use bin/activate elsewhere
pip install -r requirements.txt
cp -n .env.example .env                           # -n: never clobber an existing .env
#   then put your API key in backend/.env (see below)
uvicorn app.main:app --reload

# Frontend (http://localhost:3000)
cd frontend
npm install
cp .env.local.example .env.local                  # BACKEND_URL
npm run dev
```

Open http://localhost:3000 — the frontend proxies to the backend, so port 3000
is the only one you visit.

## LLM providers

Either provider works; Gemini is reached through Google's OpenAI-compatible
endpoint, so one client and one set of call sites serve both. Switching is a
one-line change, because the model names default per provider:

```ini
LLM_PROVIDER=gemini
GEMINI_API_KEY=...        # https://aistudio.google.com/apikey
```
```ini
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...     # https://platform.openai.com/api-keys
```

> The key lives in `backend/.env`, which is gitignored and is the one
> file not reproducible from the repo. Copying `.env.example` over it
> wipes the key, and the only symptom is the assistant quietly falling
> back to scripted replies — `GET /api/health` reports
> `"llm_configured": false` when that has happened.

| | chat + vision | extraction | max tokens |
| --- | --- | --- | --- |
| `gemini` | `gemini-3.6-flash` | `gemini-3.1-flash-lite` | 1500 |
| `openai` | `gpt-4o` | `gpt-4o-mini` | 400 |

Leave `CHAT_MODEL` / `VISION_MODEL` / `EXTRACTION_MODEL` blank to take these
defaults; set one to pin it.

Two Gemini-specific details are worth knowing, because both look like bugs:

- **Chat and extraction sit on different models on purpose.** The free tier
  meters requests per minute *per model* (5 RPM), and every turn makes two
  calls. Splitting them keeps a normal conversation under the cap. When the cap
  is hit anyway the turn degrades to the deterministic fallback and the client
  is told why, via an `error` event.
- **`chat_max_tokens` is much higher for Gemini.** Gemini 3 spends part of the
  output budget on internal reasoning before emitting any text, so a cap sized
  for OpenAI truncates the reply or returns an empty one. Reply length is
  governed by the system prompt, not this number.

Model replies are passed through a streaming markdown sanitiser: the chat
window renders raw text, and asking a model not to emit `**bold**` is not
reliable, so the markers are stripped on the way out.

Without any API key the app still runs end to end: replies come from
deterministic templates and slot-filling falls back to regex extraction
(case-insensitive, and context-aware for bare answers like "Usama khan"). Only
transcript OCR genuinely requires a key.

## The onboarding barrier

`full_name`, `nationality`, `cgpa`, `field_of_study`, `education_level`,
`target_country`, `language_score`. Diagnostics stay locked until all seven
are filled.

`education_level` (intermediate / diploma / bachelors / masters / doctorate)
is collected separately from the subject, because naming a subject does not
establish a level: "graphic design, 3.2/4.0" means very different things at
intermediate and at Master's level, and the advice differs accordingly. It is
read from phrasing like "BS", "MSc", "FSc", "A-levels" or "PhD", from the
programme name on a parsed transcript, or asked for outright when a student
names only the subject.

- **Multi-field extraction** — "I am Sarah from Pakistan studying BFA" fills
  three slots in one turn.
- **Transcript shortcut** — an upload fills name, CGPA and field of study via
  OCR. Those slots are marked `ocr_derived` and held in
  `pending_confirmation` until the student confirms them; a value the student
  typed is never overwritten by OCR (`OnboardingSlots.merge`). A model-reported
  confirmation is re-checked against `_CONFIRMATION_RE` before it counts —
  models will happily call "here is my transcript" an affirmation, which would
  skip the review step the OCR values exist to get.
- **Bare answers** — `SessionState.awaiting` records which slots the last turn
  asked about, so a reply carrying no give-away phrasing ("Usama khan",
  "pakistan", "3.4") still lands in the right slot.

## Grade conversion

`backend/app/gpa_converter.py` is pure, side-effect-free and the single source
of every number shown to a student. Percentage is the pivot representation.

- **German — Modified Bavarian Formula**: `V = 1 + 3 * ((Nmax - Nd) / (Nmax - Nmin))`,
  clamped to [1.0, 5.0]. `Nmin` is the *minimum passing mark*, which varies by
  country (Pakistan/India 40%, China 60%) — see `COUNTRY_MIN_PASS`.
- **US 4.0**: piecewise-linear interpolation over `US_GPA_ANCHORS`, monotonic
  and invertible in both directions. A source already on the 4.0 scale passes
  through unchanged rather than round-tripping.
- **UK / ECTS**: 1st ≥ 70%, 2:1 ≥ 60%, 2:2 ≥ 50%, Third ≥ 40%.

Every assumption the converter makes is returned in `GradeConversion.assumptions`
and surfaced on the card.

## SSE event contract

`POST /api/chat/stream` accepts JSON (`{session_id, message}`) or multipart
(same fields plus `file`) and streams:

| event | payload |
| --- | --- |
| `status` | transient progress, e.g. "Reading transcript.pdf..." |
| `token` | `{text}` — assistant reply, streamed |
| `slot_update` | slots, `filled`, `missing`, `pending_confirmation`, `is_complete` |
| `transcript_parsed` | full `ExtractedTranscript` |
| `diagnostic_card` | `DiagnosticCardPayload` — renders `<DiagnosticCard />` |
| `error` | `{message, recoverable}` — user-safe text |
| `done` | `{session_id, diagnostics_unlocked}` |

The Next.js route at `app/api/chat/stream/route.ts` proxies this so the backend
URL never reaches the browser; `lib/sse.ts` parses the frames.

## Layout

```
backend/app/
  schemas.py         Pydantic V2: SessionState, OnboardingSlots, ExtractedTranscript
  gpa_converter.py   Bavarian / US / UK conversions (pure functions)
  ocr_service.py     Vision OCR (GPT-4o / Gemini) + LlamaParse, upload validation
  llm_service.py     Streaming chat, structured extraction, offline heuristics
  config.py          Provider selection and per-provider model defaults
  diagnostics.py     Card assembly + country eligibility rules
  session_store.py   In-memory or Redis (set REDIS_URL)
  main.py            FastAPI app and the SSE endpoint
frontend/
  components/chat/chat-window.tsx     Streaming chat, drag-and-drop, paste upload
  components/chat/diagnostic-card.tsx Converted GPAs with progress indicators
  components/chat/slot-checklist.tsx  Onboarding barrier progress
```

## Notes for production

- The in-memory session store is process-local. Set `REDIS_URL` before running
  more than one worker.
- PDFs are rasterised at ~144 DPI, first 6 pages only (`MAX_PDF_PAGES`).
- Uploads are capped at 10 MB and restricted to PDF/PNG/JPG/WebP.
