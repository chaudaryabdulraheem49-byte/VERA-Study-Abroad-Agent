# Study Abroad Agent

Conversational study-abroad advisor. It collects seven mandatory details
through chat, reads uploaded transcripts with vision OCR, converts the grade
into US, German and UK/ECTS equivalents with deterministic arithmetic, and then
matches the student against an index of real course pages — all streamed to a
Next.js 15 client over SSE.

Three phases, each usable on its own:

| | What it does | Lives in |
| --- | --- | --- |
| **1 — Smart Diagnostics** | Slot-filling interview, transcript OCR, grade conversion, report card | `backend/app/*.py` |
| **2 — Extraction & search** | Crawl course pages → Postgres + Qdrant → hybrid search | `backend/app/services/phase2/` |
| **3 — Integration** | Card unlocks the search; matches stream into the chat | `course_matching.py`, `university-match-grid.tsx` |

A student's turn runs the whole length of that table: answer the last open
question → card is built → the card's converted percentage becomes the entry
filter for the search → matching programmes render under the report.

## Running it

Three things to start. Phases 1 and 3 need the backend and frontend; the course
matches additionally need the two databases.

```bash
# 0. Databases — detached, so no terminal is tied up (once per reboot)
docker compose up -d                 # Postgres on host :5433, Qdrant on :6333

# 1. Backend — http://127.0.0.1:8000
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows; use bin/activate elsewhere
pip install -r requirements.txt
python -m playwright install chromium             # only needed to crawl pages
cp -n .env.example .env                           # -n: never clobber an existing .env
#   then put your API key in backend/.env (see below)
uvicorn app.main:app --reload

# 2. Frontend — http://localhost:3000
cd frontend
npm install
cp -n .env.local.example .env.local               # BACKEND_URL
npm run dev
```

Open http://localhost:3000 — the frontend proxies to the backend, so port 3000
is the only one you visit.

Before chatting, `curl http://127.0.0.1:8000/api/health` is worth a glance:
`"llm_configured": true` is the field that matters. `false` means the key is
missing from `backend/.env`, and the only other symptom is the assistant
quietly falling back to scripted replies.

### If the databases are not running

Everything up to and including the diagnostic report still works. The course
grid is replaced by one line saying the index could not be reached — the
matching failure is contained to its own SSE frame and never interrupts the
conversation.

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

> The key lives in `backend/.env`. That path is anchored to the package
> rather than to the working directory: a bare `.env` resolves against
> wherever the process was started, so `uvicorn` launched from `backend/`
> found the key while a script run from the repo root silently did not, and
> the only symptom was every call behaving as though no provider were
> configured. It is gitignored and is the one
> file not reproducible from the repo. Copying `.env.example` over it
> wipes the key, and the only symptom is the assistant quietly falling
> back to scripted replies — `GET /api/health` reports
> `"llm_configured": false` when that has happened.

| | chat + vision | extraction | crawler | embedding | max tokens |
| --- | --- | --- | --- | --- | --- |
| `gemini` | `gemini-3.5-flash-lite` | `gemini-3.1-flash-lite` | `gemini-3.5-flash-lite` | `gemini-embedding-001` | 1500 |
| `openai` | `gpt-4o` | `gpt-4o-mini` | `gpt-4o-mini` | `text-embedding-3-small` | 400 |

Leave `CHAT_MODEL` / `VISION_MODEL` / `EXTRACTION_MODEL` / `CRAWLER_MODEL` /
`EMBEDDING_MODEL` blank to take these defaults; set one to pin it.

The Gemini row is **lite models on purpose**. The free tier caps the
full-size flash models at 20 requests per *day*, which a single afternoon of
testing exhausts; the lite tier handles streaming, JSON mode and transcript
OCR just as well here.

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

## Phase 1 - the onboarding barrier

`full_name`, `nationality`, `cgpa`, `field_of_study`, `education_level`,
`target_country`, `language_score`. Diagnostics stay locked until all seven
are filled.

A level can be named in two quite different senses, and the app keeps them
apart. "I want to study masters in business" states a **preference**; "I have
done my masters" states a **qualification**. Reading the first as the second
flipped a Bachelor's holder to Master's, after which the search inferred they
were shopping for a PhD and put two doctorates at the top of a shortlist they
had asked to be Master's. A completion marker beats an intent marker, so "I
want to apply now that I have finished my bachelors" still records the
Bachelor's. A stated preference (`SessionState.desired_level`) overrides the
level inferred from what the student holds, and changing it re-runs the
shortlist without re-sending the report.

`desired_level` is deliberately **not** a slot - it does not gate the barrier -
which is also how it went missing twice: `_merge_patches` walks `SlotName`, so
the heuristic found the preference and the merge dropped it on every turn the
model ran. Both places now carry it explicitly.

The level parser reads the extraction model's output as well as a student's
typing, so it accepts the schema's **own enum values** before it tries the
prose patterns. `high_school` is the only value containing an underscore; it
matched none of the prose patterns, so a *correct* model answer was silently
turned back into "not provided". The other four levels never showed the bug
because their values happen to be single words — which is exactly why it went
unnoticed. "Intermediate" is also matched loosely, because it is the level
students most often type out in full and most often mistype.

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
- **More than one destination** — "Australia, UK" names two places, and
  recording the first while discarding the second is the silent kind of wrong:
  the dropped country is never mentioned again, so there is nothing for the
  student to notice. Both are held unassigned until they confirm, then
  `target_country` keeps the primary — the report's advice is country-specific,
  so one has to lead — and `extra_countries` holds the rest. The search spans
  all of them equally, each expanded to its spellings.

  Both the student's message and the *model's* output are checked. A model
  answering "Australia , UK" files `target_country="Australia and UK"`, and
  stored verbatim that is a country nothing in the index is in — the filter
  then matches nothing, with no visible reason. When the countries come from
  that field no turn-context test is applied: the model has already decided
  they are destinations by putting them there.

  From the raw message the rule is stricter. Two countries only count as
  destinations when the turn is actually about where they want to go: "I am
  from India and want to study in Australia" names two countries and one
  destination, and citizenship is filtered out before the count.
- **Bare answers** — `SessionState.awaiting` records which slots the last turn
  asked about, so a reply carrying no give-away phrasing ("Usama khan",
  "pakistan", "3.4") still lands in the right slot.

### Grade conversion

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

## HTTP surface

| endpoint | shape | purpose |
| --- | --- | --- |
| `POST /api/chat/stream` | JSON or multipart → SSE | one conversational turn |
| `POST /api/chat/upload` | multipart → JSON | parse a transcript, no turn |
| `GET /api/session/{id}` | JSON | restore a reloaded page |
| `DELETE /api/session/{id}` | 204 | "New chat" |
| `GET /api/health` | JSON | is the key configured |

### SSE event contract

`POST /api/chat/stream` accepts JSON (`{session_id, message}`) or multipart
(same fields plus `file`) and streams:

| event | payload |
| --- | --- |
| `status` | transient progress, e.g. "Reading transcript.pdf..." |
| `text_delta` | `{text}` — assistant reply, streamed |
| `slot_update` | slots, `filled`, `missing`, `pending_confirmation`, `is_complete` |
| `transcript_parsed` | full `ExtractedTranscript` |
| `diagnostic_card` | `DiagnosticCardPayload` — renders `<DiagnosticCard />` |
| `university_matches` | `{query, matches[], note}` — renders `<UniversityMatchGrid />` |
| `error` | `{message, recoverable}` — user-safe text |
| `done` | `{session_id, diagnostics_unlocked}` |

A `recoverable` error is rendered beside the reply that still follows it rather
than replacing it; that is how a bad scan, an exhausted quota and an
unreachable course index all report themselves without tearing down the
stream.

The Next.js routes at `app/api/chat/stream/route.ts` and
`app/api/chat/upload/route.ts` proxy these so the backend URL never reaches the
browser; `lib/sse.ts` parses the frames.

### Why there are two upload paths

The chat UI attaches transcripts to `/api/chat/stream`, because that returns
the parsed values *and* the confirmation question in the same turn — the review
step exists precisely so OCR output is never silently trusted.
`/api/chat/upload` does the same extraction and returns it as JSON, for callers
that want the structured fields without a conversation. Both mark the session
`transcript_parsed` and both leave the values `pending_confirmation`.

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
  course_matching.py Phase 1 profile -> Phase 2 SearchConstraints (the seam)
  main.py            FastAPI app, the SSE endpoint and the upload endpoint
  services/phase2/
    schemas.py             CourseExtractionSchema + search/result contracts
    crawler_service.py     Crawl4AI + LLMExtractionStrategy -> validated course
    dataset_import.py      CSV/JSON -> validated course, no web requests
    db.py                  courses + universities tables, async engine
    ingestion_service.py   Postgres upsert + Qdrant vector upsert
    hybrid_search_service.py  SQL hard filter -> vector ranking
    embeddings.py          Provider-aware embeddings, retried on 429
    embedding_cache.py     Query vectors cached on disk, so repeats are free
    pipeline.py            CLI: init / status / import / ingest / search
scripts/
  ingest_cricos.py       Bulk-load the Australian CRICOS register
  sync_cricos.py         Check data.gov.au and sync a new release
  backfill_embeddings.py Give every Postgres course a Qdrant vector
  daily_maintenance.ps1  Sync + backfill, run unattended by Task Scheduler
frontend/
  components/chat/chat-window.tsx     Streaming chat, drag-and-drop, paste upload
  components/chat/diagnostic-card.tsx Converted GPAs with progress indicators
  components/chat/university-match-grid.tsx  Ranked programmes under the card
  components/chat/slot-checklist.tsx  Onboarding barrier progress
  lib/sse.ts                          Frame parser for the POST event stream
  app/api/chat/stream/route.ts        SSE proxy
  app/api/chat/upload/route.ts        Transcript-upload proxy
```

## Phase 2 - hybrid extraction and search

```
[University page]  or  [CSV / JSON dataset]
      |                      |
      | crawler_service      | dataset_import   column mapping + coercion,
      |   Crawl4AI renders   v                  no network calls at all
      v   JS, LLM extracts
[Validated course]  <- both paths produce a CourseExtractionSchema
      | ingestion_service    Postgres row (numeric/categorical) assigns the id
      v                      Qdrant point (syllabus vector) keyed by that id
[Two stores, one id]
      | hybrid_search_service
      v  Step 1  Postgres hard filter  -> <=500 candidate course_ids
         Step 2  Qdrant MatchAny over those ids -> cosine ranking -> top 10
```

### Filling the index

The chat can only match against courses that are in the index. There are two
ways in, and **`import` is the one to reach for first**:

```bash
cd backend
python -m app.services.phase2.pipeline init                      # tables + collection

python -m app.services.phase2.pipeline import courses.csv --dry-run   # from a file
python -m app.services.phase2.pipeline import courses.csv

python -m app.services.phase2.pipeline ingest https://example.edu/msc-data-science
```

| | `import` | `ingest` |
| --- | --- | --- |
| Source | a file you already have | a live university page |
| Network | embeddings only | fetches the page, sends its text to the LLM |
| Speed | a whole dataset in one pass | seconds per page, often blocked |
| Use it when | you have a dataset or an API export | nobody has structured that page yet |

`init` is idempotent; `init --recreate` drops and rebuilds the collection,
which is what a changed embedding width calls for. Both `import` and `ingest`
upsert, so re-running either updates a course in place rather than duplicating
it.

#### Importing a dataset

`import` reads `.csv`, `.tsv`, `.json`, `.jsonl` and `.ndjson`. A JSON file may
be a bare list or an object wrapping one under `data`, `results`, `courses`,
`items`, `records` or `rows` — which is how most APIs return a page of results,
so a saved API response imports unedited.

**Columns are matched by name**, case- and separator-insensitively, against a
table of spellings real datasets use — `Programme Name`, `Institution`,
`Tuition Fees`, `IELTS Requirement`, `Work Rights` and so on all resolve on
their own. The values are coerced the same way crawled pages are: `£24,500`
becomes `24500`, `Master's` / `MA` / `postgraduate` become `Masters`, `yes` /
`TRUE` / `1` become `true`, and `n/a` / `TBC` / `-` become absent rather than
being parsed as text.

Anything the table cannot guess goes in a mapping file, written in the
direction a person thinks in — schema field first:

```json
{ "course_title": "Internal Course Ref", "syllabus_description": "Blurb" }
```
```bash
python -m app.services.phase2.pipeline import courses.csv --mapping map.json
```

`--dry-run` prints the mapping it worked out, the per-row rejections and a
preview, and writes nothing. It is worth running once on any new dataset,
because the mapping is where a file silently imports as the wrong thing.

Three reporting rules, all because **a dataset that half-imports without
saying so is worse than one that refuses**:

- Every rejected row is listed with its **row number and which fields failed**
  (capped at 20 lines, then counted).
- Out-of-range values are **rejected, not clamped** — an IELTS of 99 is a
  misread of the source, not a very strict university.
- Columns that were ignored are **named**, so a misspelled header is visible
  rather than silently absent.

A row with no description column still imports, with one composed from the
title and university, and the count is reported — those courses are findable
but match less accurately, because a real syllabus is what the subject search
actually compares against.

[`data/sample_courses.csv`](data/sample_courses.csv) is a small deliberately
messy example: different header names, currency symbols, mixed degree
spellings, an `n/a` deadline and one unsalvageable row.

#### Importing an official register

A national register is too large and too particular for the generic importer,
so it gets its own script. [`scripts/ingest_cricos.py`](scripts/ingest_cricos.py)
loads the Australian CRICOS export — the government list of providers and
courses that may enrol international students:

```bash
python scripts/ingest_cricos.py --dry-run
python scripts/ingest_cricos.py            # --fx 0.67 --zip <path>
```

It unzips the archive, cleans it with pandas and bulk-upserts with async
SQLAlchemy. No network request beyond the database. It fills three tables:

| Table | Rows | What it holds |
| --- | ---: | --- |
| `universities` | 1,543 | providers, keyed on the CRICOS provider code |
| `courses` | 9,845 | the higher-education awards the advisor can match on |
| `courses_raw` | 25,978 | every register row, so nothing is discarded |

Four decisions worth knowing, because the register does not fit the schema
cleanly:

- **The provider code is the primary key**, not a surrogate. It is the join
  key in the source data and stable across releases, so a row is traceable
  back to the register without a lookup.
- **CRICOS has twenty AQF levels; the advisor matches on three.** Only the
  higher-education awards map, and the register's own wording is kept in
  `course_level_raw` regardless. Graduate Certificates and Graduate Diplomas
  are deliberately *not* mapped to `Masters`: they are postgraduate, but
  calling them a Master's misdescribes the award a student would graduate
  with. They stay in `courses_raw`.
- **Expired registrations are dropped** (85 of them) and duplicate
  `(provider, course)` pairings are collapsed cheapest-first where they can be
  counted (758 of them — the same award registered at several campuses), so
  the upsert is never left to silently overwrite.
- **The ASCED classification is carried onto `courses`, not just the staging
  table.** `field_broad`, `field_narrow` and `field_detailed` are stored
  verbatim as the register writes them — `02 - Information Technology`, code
  and label together. Splitting them on import would throw away the code,
  which is the part a facet groups on, and a caller wanting only the label can
  split on `" - "`. `field_broad` is indexed, because 9,845 rows without one
  turns every facet into a sequential scan.

  Rows loaded before those columns existed are repaired by `backfill_asced()`,
  which joins `courses` to `courses_raw` on `external_course_code` — the
  register's own identifier, unique in both tables. Joining on title and
  university instead would collapse the same award offered at several campuses
  onto one classification. It compares with `IS DISTINCT FROM` rather than
  looking for NULLs, so it also repairs a row whose classification changed in a
  later release and touches nothing already correct.

  Only CRICOS rows carry it. A crawled course page states no ASCED code, so
  those stay NULL rather than being guessed.
- **Entry requirements are stored as zero, meaning unstated.** The register
  states none, and inventing a GPA or IELTS band would filter real students
  out of real courses.

#### Keeping it current

The register is reissued periodically.
[`scripts/sync_cricos.py`](scripts/sync_cricos.py) decides whether the archive
on disk is still the published one and acts only if it is not:

```bash
python scripts/sync_cricos.py --dry-run   # check only, downloads nothing
python scripts/sync_cricos.py
python scripts/sync_cricos.py --force     # re-sync regardless
```

The only host contacted is `data.gov.au`, via the CKAN API for package
`cricos` (`e5ae7059-bfa8-4fa4-a5c0-c13cf3520193`). A run that finds nothing
new transfers a few kilobytes of metadata, not the 1.5 MB archive.

Three things are compared against `data/cricos_sync_state.json`, because any
one alone misses a case:

| | Catches |
| --- | --- |
| `last_modified` | the ordinary case: a new release |
| `size` | a re-upload that kept the timestamp |
| SHA-256 of the bytes | checked after download — a reissue with identical content skips the ingest entirely |

The ZIP resource is resolved **by format on every run** rather than pinned by
id: republishing can mint a new resource id for the same logical file, and a
pinned id would quietly keep serving the superseded release.

Afterwards it hands anything still missing a vector to the same backfill, so a
sync never leaves courses eligible-but-unrankable. The free-tier budget still
applies, so a large update becomes searchable over several days and the run
says how many are outstanding rather than implying it finished.

Two caveats that matter more than the row counts:

- **`Estimated Total Course Cost` is whole-of-course, not annual** (median
  A$110,228 — a multi-year Bachelor's total), while a crawled page states an
  annual fee. The two are not comparable in a budget filter. `duration_weeks`
  is stored beside it, so annualising is
  `tuition_fee_aud / (duration_weeks / 52)` whenever that is wanted.
- **Postgres rows alone are not searchable.** The hybrid search ranks by
  vector, so a course with no Qdrant point is eligible but never ranked. A
  bulk import therefore needs an embedding pass before the chat can surface
  any of it — see below.

The register carries no prose — it is a legal listing, not a prospectus — so
`syllabus_description` is composed from the course name, level, provider and
its Field of Education classification. That is what makes these rows findable
by subject at all, and it is thinner than a real course page.

### Why the two steps are in this order

Budget, IELTS and country are facts a student either meets or does not, and a
vector store cannot enforce them - a semantic search alone will happily return
a course they cannot afford or qualify for. So Postgres decides *eligibility*
and Qdrant decides *relevance* over the survivors. The candidate list is capped
(`MAX_SQL_CANDIDATES`, default 500) because it is handed to Qdrant as a
`MatchAny` filter, and an unbounded list would bloat both the SQL plan and the
filter payload; it is ordered cheapest-first so a truncated set is the
affordable end of it rather than an arbitrary slice.

### Things worth knowing

- **Postgres is published on host port 5433, not 5432.** A native PostgreSQL
  service often already owns 5432; when both bind it, connections reach
  whichever won the race, and the symptom is
  `password authentication failed for user "postgres"` - an auth error for a
  port conflict. Publishing one port over avoids touching an existing install.
- **`gemini-embedding-001` is the Gemini embedding model**, not
  `text-embedding-004` (not served to newer keys). It honours an explicit
  `dimensions`, so both providers are pinned to 1536 and the collection width
  matches either way. A width change is detected on startup with an
  instruction, rather than surfacing as an opaque Qdrant rejection:
  `pipeline init --recreate` drops and rebuilds the collection.

- **Embedding width must match the collection.** A Qdrant collection created at
  one width rejects vectors of another, so changing `EMBEDDING_MODEL` means
  `pipeline init --recreate`. Both providers default to 1536
  (`EMBEDDING_DIMENSIONS`), so the collection is interchangeable between them.
- **Gemini numbers embeddings oddly.** It returns `index=None` on the first
  item while numbering the rest, which crashed a plain sort with
  `'<' not supported between int and NoneType`; the response is only sorted
  when every index is an integer.
- **Postgres is written before Qdrant.** It assigns `course_id`; writing the
  vector first can leave a point referencing a row that was never committed.
- **Re-crawling updates in place.** The upsert conflicts on
  `(university_name, course_title)` and preserves the original `course_id`, so
  the Qdrant point keeps pointing at the right course.
- **Vague deadlines become NULL, never a guess** - "rolling" and "late January"
  are common on these pages, and a NULL deadline stays eligible in the filter
  rather than being read as already passed.
- **Unstated is stored as NULL, never as zero and never as a default.**
  The register publishes no entry requirements and no intake dates for any of
  its courses. Zero said "this course asks for nothing" and rendered on the
  card as `0% · IELTS 0`; a plausible default would say something the register
  does not.

  Defaults are the worse of the two. Measured on this index, filling unstated
  requirements with 60% / IELTS 6.5 takes a student with IELTS 6.0 from
  **3,795 eligible Australian Master's programmes to none at all** — invented
  requirements do not merely mislead, they filter real students out of real
  courses. The hard filter therefore treats NULL as no barrier, exactly as it
  already does for an unstated deadline, and the card renders it as
  "Not published".

  `deadline_type` distinguishes three answers rather than two: `published`
  (a real date), `rolling` (the source says applications never close) and
  `not_published` (the source is silent). A student books flights and pays
  deposits against this field, so nothing in it is inferred.
- **Tuition is normalised to USD** from a static table in `schemas.py`. Static
  on purpose: a drifting rate would make two ingests of the same page disagree.
  Refresh it deliberately.

### Keeping the two stores in step

Postgres and Qdrant can disagree without anything raising an error, and the
failure is invisible from the outside: a course with a row but no vector
passes the eligibility filter and is then dropped at the ranking step, so it
is silently unreachable. That is exactly what a bulk import produces, because
it writes rows directly rather than going through the ingest path that embeds.

```bash
python -m app.services.phase2.pipeline status   # rows vs vectors, per country
python scripts/backfill_embeddings.py --dry-run
python scripts/backfill_embeddings.py           # embed everything missing one
```

[`scripts/backfill_embeddings.py`](scripts/backfill_embeddings.py) asks Qdrant
which ids it already holds and embeds only the difference, committing each
batch before requesting the next — so a run stopped by a quota limit, a
dropped connection or Ctrl-C loses nothing and re-running continues from
where it left off. A batch that fails is logged and skipped rather than ending
the run, because the rest of the index is still worth building.

#### Living inside the free tier

**The free tier bills per *text*, not per call**, against **1,000 per day** and
**100 per minute**. That one fact governs the whole design, and it is not
obvious: batching 64 courses into one HTTP request spends 64 of the allowance,
not one. An early version paced itself at 55 *calls* a minute carrying 64
texts each — around 3,500 texts a minute against a ceiling of 100 — and spent
the entire run being refused.

So both limits are counted in texts:

| | Flag | Default | Ceiling |
| --- | --- | ---: | ---: |
| Per minute | `--rpm` | 80 | 100 |
| Per UTC day | `--daily-limit` | 900 | 1,000 |
| Rows per call | `--batch` | 50 | — |

**The daily default is 900, not 1,000, on purpose.** Every chat search embeds
the student's query, so an allowance spent entirely on backfilling does not
merely pause the backfill — it takes search offline for everyone until UTC
midnight. That happened once; the reserve is the fix.

The other half of that fix is
[`embedding_cache.py`](backend/app/services/phase2/embedding_cache.py): query
vectors are cached on disk, keyed by the text *and* the model and width that
produced it, so repeating a search costs nothing. Students repeat subjects
heavily while every course is embedded exactly once, which is why caching is
worth it on the search side and pointless on the ingest side. It is on disk
rather than in memory because the allowance is reckoned per day while a
process lives for minutes — an in-memory cache would be empty again exactly
when it is most needed. A corrupt or missing file is a cold cache, never an
error.

When the allowance does run out, the chat says so specifically: "programme
matching is paused until tomorrow" rather than "could not reach the course
index", which was actively misleading — the index was reachable, it was the
query that could not be embedded.

The day's spend is kept in the checkpoint, so a second run on the same day
knows what the first one used rather than starting out believing it has a
fresh thousand. When the budget is gone the script exits **without making a
request at all** and says when it resets — a refused request still costs a
round trip and its backoff, so counting is strictly cheaper than discovering.

At 1,000 a day a 9,857-course index takes about ten daily runs. Which thousand
goes first is then a real decision, so the run can be narrowed:

```bash
python scripts/backfill_embeddings.py --match mechanical      # 58 courses
python scripts/backfill_embeddings.py --level Masters --country Australia
```

```bash
python scripts/backfill_embeddings.py --status              # coverage + per-day counts
python scripts/backfill_embeddings.py --report              # what today added
python scripts/backfill_embeddings.py --report 2026-10-05   # what that day added
```

The checkpoint keeps two separate records, because they answer different
questions. `completed` is one merged set — "is this course done" — which is
all the resume logic needs and all it should need. `embedded_by_date` logs
which courses arrived on which UTC day, which is the question actually asked
after every run and which a merged set cannot answer. A re-run only logs ids
it had not already recorded, so covering old ground never inflates a day's
tally. Days predating this log show in the spend ledger alone, and `--status`
says so rather than implying nothing happened on them.

The checkpoint lives at `data/embedding_checkpoint.json`. It is written after
every batch but only once Qdrant has acknowledged the upsert, so it can never
claim a course that was not stored, and it is written to a sibling file and
moved into place so a kill mid-write cannot truncate it. It records the model,
collection and width it was written under and ignores its own course list if
any of them changed — but keeps the spend ledger, because the allowance was
consumed whatever it was spent on.

It mirrors `CourseExtractionSchema.embedding_text` deliberately: a backfilled
vector must be built from the same text as an ingested one, or the same course
would score differently depending on how it entered the index and nothing
would report the discrepancy.

### Unattended upkeep

Two chores recur: the register is reissued periodically, and the embedding
allowance resets every UTC midnight and is lost if unspent. Both are wrapped
in [`scripts/daily_maintenance.ps1`](scripts/daily_maintenance.ps1) and run by
a Windows scheduled task.

```powershell
# what the task runs
powershell -ExecutionPolicy Bypass -File scripts\daily_maintenance.ps1
powershell -ExecutionPolicy Bypass -File scripts\daily_maintenance.ps1 -SkipSync

# managing the task
schtasks /Query  /TN "StudyAbroadAgent\DailyMaintenance" /FO LIST /V
schtasks /Run    /TN "StudyAbroadAgent\DailyMaintenance"
schtasks /Change /TN "StudyAbroadAgent\DailyMaintenance" /DISABLE
schtasks /Delete /TN "StudyAbroadAgent\DailyMaintenance" /F
```

It runs **daily at 12:30 local (07:30 UTC)**, which is inside the same UTC day
as the allowance reset, so a full day's allowance is available to spend. The
task runs under the interactive session, so it fires only while you are logged
on; `StartWhenAvailable` is set, so a run missed because the machine was off
or asleep is caught up at the next logon rather than skipped. A missed day
costs a day, never the progress already made.

Change the time with `schtasks /Change /TN "StudyAbroadAgent\DailyMaintenance"
/ST HH:MM`. Check afterwards that `StartWhenAvailable` survived — `/Change`
can reset settings it was not asked about:

```powershell
([xml](schtasks /Query /TN "StudyAbroadAgent\DailyMaintenance" /XML ONE)).Task.Settings
```

Three decisions in the wrapper worth knowing:

- **Docker is checked first and named plainly.** Without Postgres and Qdrant
  every step fails with a connection error that reads like a bug.
- **The backfill runs even if the sync failed.** They are independent, and the
  allowance is the perishable one: it is gone at midnight either way, while a
  missed catalogue check simply waits for tomorrow.
- **Logs are pruned by the same script**, not a second scheduled task — one
  moving part is easier to reason about than two. They land in `logs/`, one
  file per day, kept for 30 days (`-KeepLogDays`).

Both steps are safe to repeat: the sync downloads nothing when the published
release is unchanged, and the backfill embeds only what Qdrant does not
already hold. A failed day costs a day, never the progress already made.

## Accounts and saved conversations

Optional. With no Supabase project configured the app runs exactly as it did
before accounts existed — that is deliberate, because a missing environment
variable turning a working app into a wall of 401s is a worse failure than not
having accounts at all. Fill the variables in and chat routes require a
signed-in user and conversations are saved.

```bash
# backend/.env
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...   # server only - bypasses RLS
SUPABASE_JWT_SECRET=...         # legacy HS256 projects only

# frontend/.env.local
NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
```

Then run [`backend/migrations/001_chat_history_rls.sql`](backend/migrations/001_chat_history_rls.sql)
against the project.

### How a request is authenticated

The browser holds a Supabase session in cookies. `middleware.ts` refreshes it
on every request and redirects anonymous visitors away from `/chat`, keeping
the `next` path so they land where they were going. Each API call carries
`Authorization: Bearer <access token>`, read fresh per request rather than
cached — the token is short-lived, and a header captured at mount starts
failing an hour in, intermittently.

The backend verifies that token **locally**: it is a signed JWT, so the
signature, audience and expiry are all the proof needed, and a call to
Supabase per request would put their availability in the path of every chat
message. Both signing schemes are supported — the legacy HS256 shared secret
and the asymmetric keys Supabase is moving to, verified against the cached
JWKS — because a project migrating between them would otherwise reject every
token mid-flight.

### Two layers, because the service role bypasses one

The SQL migration enables Row Level Security with `auth.uid() = user_id` on
both tables. That is the guarantee for the **browser** client, which holds
only the user's own token.

It is *not* what protects the backend, which uses the service-role key and so
bypasses RLS entirely. Every function in `chat_history.py` therefore filters by
`user_id` itself, taken from the verified token and never from anything the
client sent, and `owns_thread` is checked before a thread is read or appended
to. A thread that is not yours answers 404 rather than 403 — saying "that is
not yours" confirms it exists and belongs to someone.

`chat_messages` has no update policy at all. A transcript is a record of what
was said, and the absence of a policy is what enforces that.

### What is saved, and when

A thread is created on the first message of a signed-in session and titled
from it — a student typing into a chat box has not agreed to also name the
conversation. Each turn is written once, after the reply has finished
streaming, rather than per token: a hundred inserts per turn would cost more
than the conversation.

Nothing here can break a turn. Every history call reports failure by returning
nothing and logging it, and the conversation carries on — persistence is an
addition, never a precondition.

Opening a saved conversation replays the diagnostic report and the course
matches as well as the text. They are stored **exactly as they were sent**, as
`system` rows carrying a `payload` (migration 002), and replayed verbatim.

That distinction matters: rebuilding the card from the transcript would mean
re-deriving a student's profile from its own message history, which is the
guesswork the slot barrier exists to prevent. Keeping the artifact costs a row
and is exact. The column lives on `chat_messages` rather than `chat_threads`
so the card appears where it was produced, and a corrected grade leaves both
cards in order rather than overwriting the first.

If 002 has not been run, history still reads - the query falls back to the
original columns and the artifacts simply do not appear, rather than the whole
view failing over a missing feature.

## Phase 3 - end to end

The two phases meet in `backend/app/course_matching.py`, which is deliberately
small: it is a translation layer, not a second search implementation.

```
[Seven slots filled]
      | diagnostics.build_card     grade -> US / German / UK, eligibility notes
      v
[DiagnosticCardPayload]  --------> SSE: diagnostic_card
      | course_matching            card.conversion.normalized_percentage
      v                            becomes SearchConstraints.student_gpa_percent
[SearchConstraints + query text]
      | hybrid_search_service      (Phase 2, unchanged)
      v
[Top 6 CourseMatch]      --------> SSE: university_matches
```

### The three translations it makes

- **Level held -> level applied for.** A student *with* a Bachelor's is
  shopping for a Master's. Filtering on `degree_level = Bachelors` would return
  the course they just finished, so `_NEXT_DEGREE` maps each qualification to
  the next one up (Master's holders get PhD *and* Master's, because a second
  Master's is a real choice).
- **Region -> countries.** "Europe" is not a value in the country column;
  filtering on it literally returns nothing. `_REGIONS` expands it to the
  countries actually indexed.
- **One grade, one number.** The card's `normalized_percentage` is what the
  entry-requirement filter compares against, rather than each phase deriving
  its own figure from the raw CGPA. If the two ever disagreed, the symptom
  would be courses the student does not actually qualify for.

### Eligible is not the same as relevant

The SQL filter decides what a student *qualifies* for and the vector search
orders those by subject. Neither decides whether the last result is worth
showing, so the grid used to pad itself to `top_k`: an English Literature
graduate was shown a literature MA followed by three data-science degrees,
which passed the grade and country filters and ranked second to fourth only
because nothing else was left to rank.

`filter_by_relevance` applies two cuts, because either alone is wrong in a
different direction:

- **An absolute floor** (`MATCH_MIN_SIMILARITY`, 0.60) for a subject the index
  does not cover. Every score is then mediocre, so there is no cliff for a
  relative rule to find.
- **A margin below the best score** (`MATCH_SIMILARITY_MARGIN`, 0.06) for a
  subject it does cover. What counts as relevant depends on how good the best
  answer was, and a fixed floor either admits the tail or rejects a whole
  decent set.

Both were measured against this index rather than guessed — a subject with a
real match scores ~0.65 followed by a visible cliff, a subject with none
produces a flat band in the low 0.5s. **They are calibrated for the current
embedding model**; changing `EMBEDDING_MODEL` shifts the whole distribution,
so re-measure rather than assuming they carry over.

#### The query has to carry the subject

A student typing `Ai` was shown nothing. Measured against this index,
`Ai UK Masters` peaked at **0.592** and was rejected by the floor, while
`Artificial Intelligence UK Masters` reached **0.639** on the very same
courses. Two characters carry almost no signal, and the gap — 0.047 — is
larger than the margin the floor allows.

So `expand_field` writes an abbreviated subject out in full before it is
embedded. A whole-field match expands outright; otherwise each token is
expanded individually, so `AI and robotics` keeps its shape while the part
that matters still reaches the vector. Only unambiguous entries are in the
table: **`BA` and `CE` are deliberately absent**, because `BA` is a degree as
often as business administration and `CE` is claimed by both civil and
computer engineering — expanding either would put a student in the wrong
discipline, which is worse than not expanding at all.

The expanded form is used in the empty-grid note too, so it reads "close
enough to Artificial Intelligence" and names the subject actually searched
for.

#### The reply frames the shortlist; it does not compete with it

The model was writing its own university shortlist — named institutions,
invented entry percentages, league-table groups — directly above the grid of
real indexed courses. Two shortlists on one page, one of them unverifiable,
disagreeing with each other.

`SHORTLIST_DIRECTIVE` is appended to every turn that can produce matches. It
is phrased as a hard rule that names the specific thing the model kept doing,
because a polite version was simply ignored: never name a university or a
programme, never state an entry requirement, tuition figure or ranking, never
write a list of institutions. It also says *why* — there is no university
database behind the prose, so any institution named there is invented, while
the grid beneath is drawn from the real index.

The reply is capped at three sentences: acknowledge the ask, say in general
terms whether the move is realistic and how the converted grade sits against
it, then hand over to the grid.

#### The card is a grade report, so only a grade reprints it

`_same_report` compares **only the conversion**, not the whole payload.
Saying "I want to study business instead" changes no converted number, yet
comparing whole cards treated it as a new report — so the card was reprinted
in full on exactly the turn where the student wanted the shortlist rather than
the arithmetic again. A corrected CGPA does move the numbers and does warrant
a fresh card.

When the report stays put but the ask has changed — a different level,
destination or subject — the shortlist re-runs on its own.

#### Two passes, not one broad one

A search runs precisely first and widens only if it has to. If the first pass
returns fewer than `MATCH_MIN_RESULTS` (5), it is retried once with
neighbouring disciplines added and a lower floor
(`MATCH_FALLBACK_SIMILARITY`, 0.55), and those results are labelled in the
grid as coming from related fields.

Widening is a fallback rather than the default because mixing parent terms
into every query blurs the boundary the floor exists to keep. Measured here,
`Artificial Intelligence Australia Masters` scored the real AI degree at
**0.784** with the next course 0.172 behind; appending *Computer Science,
Information Technology, Software Engineering, Data Science* dropped the true
match to **0.743** and lifted the runner-up to **0.658**. Widening a search
that already found almost nothing costs nothing, because there was nothing
left to blur.

A subject with no known neighbours is not widened at all — inventing an
adjacency puts a student in the wrong discipline, which is the failure this
whole section exists to prevent. If the retry itself fails, the first pass's
results are kept: a thin shortlist beats an error.

#### An empty grid has three causes, not one

They ask for completely different actions, so the note names which one it is:

| Shortfall | Means | What fixes it |
| --- | --- | --- |
| `catalogue` | nothing indexed in that country at that level | ingest courses, or widen the destination |
| `requirements` | courses are there; the student does not clear their bar | raise the IELTS or the grade |
| `subject` | plenty they qualify for, none in their field | ingest courses in that discipline |

The middle one was missing, and its absence produced a flatly false message: a
student with IELTS 6.0 targeting Canada was told "nothing in the course index
is in Canada at Masters level yet ... a gap in the catalogue rather than
anything about your grades". Both Canadian courses were indexed, both ask for
IELTS 7.0, and the diagnostic report two boxes above had already named the
IELTS as the thing to fix. The page contradicted itself.

So when the hard filter returns nothing, `_probe_catalogue` re-counts the same
country and level **without** the student's grade and language score, and
takes the gentlest entry requirements among them. The note then reads:

> There are 2 programmes in Canada at Masters level in the index, but you do
> not yet meet the entry requirements. The least demanding asks for IELTS 7
> (you have 6). This is about the bar, not the catalogue — closing that gap
> puts them in reach.

The probe runs only when the search came back empty, so the ordinary path pays
nothing for it, and a failure in it is logged rather than raised — it is a
nicety on top of an already-empty result, never a reason to lose the report.

When the floor empties the grid, the note says so and says why — "nothing
close enough to English Literature" reads differently from "nothing in the UK
yet", and only one of them is fixed by widening the destination.

Two constraints are deliberately *not* applied. There is no budget slot in the
interview, so tuition is shown on each card rather than filtered on - guessing
an affordability ceiling would silently hide options. And IELTS constrains only
when the student actually holds a band; "planned" means unknown, and filtering
on an unknown would drop every course that states any language requirement.

### Failure is contained

`find_matches` raises `MatchingUnavailable` for anything that goes wrong -
Postgres down, Qdrant down, embedding provider refusing, Phase 2 dependencies
absent - and `_emit_matches` turns that into a single recoverable `error`
frame. The report above it is already delivered and useful on its own, so an
unreachable index is a degraded turn, never a failed one.

An index that is *reachable but has nothing matching* is a different case and
is not an error: the `university_matches` event carries an empty list plus a
`note` naming the destination and level that nothing was found for, and the
grid renders it as a neutral line. The common cause early on is simply that
the course page has not been crawled yet.

## Tests

504 tests, all offline - no Postgres, Qdrant or API key needed.

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe -m pytest tests --cov --cov-report=html -q && start htmlcov/index.html
```

They also appear in VS Code's Testing panel. What each file covers, the
coverage table and the known gaps are documented in
[backend/tests/README.md](backend/tests/README.md). The most significant gap is
that `main.py` - the SSE endpoint, the confirmation gate and the turn planner -
sits at 0%.

Alongside them are `live_*.py` scripts, which pytest ignores because they hit
the real databases and the live API. Run one directly for an end-to-end check:

```bash
.venv/Scripts/python.exe -m tests.live_phase2    # crawl -> ingest -> search
.venv/Scripts/python.exe -m tests.live_phase3    # profile -> card -> matches
```

## Notes for production

- The in-memory session store is process-local. Set `REDIS_URL` before running
  more than one worker.
- PDFs are rasterised at ~144 DPI, first 6 pages only (`MAX_PDF_PAGES`).
- Uploads are capped at 10 MB and restricted to PDF/PNG/JPG/WebP.
