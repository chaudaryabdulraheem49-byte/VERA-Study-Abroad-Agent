# Test suite

504 tests across twelve files. Every one runs offline — no Postgres, no Qdrant
server, no API key — so the suite is safe to run on every save.

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests -q                  # run
.venv/Scripts/python.exe -m pytest tests --cov --cov-report=html -q
start htmlcov/index.html                                     # line-by-line report
```

In VS Code they appear in the **Testing** panel (configured in
`.vscode/settings.json`: pytest, working directory `backend/`).

---

## What each file covers

| File | Tests | Subject |
| --- | --- | --- |
| `test_extraction.py` | 186 | Slot extraction: names, countries, levels, gibberish |
| `test_gpa_converter.py` | 43 | Grade conversion arithmetic |
| `test_scope.py` | 39 | Topic guardrail |
| `test_phase2.py` | 58 | Crawl/ingest/search contracts, the SQL filter, table shape |
| `test_phase2_qdrant.py` | 4 | Vector ranking against a real Qdrant engine |
| `test_course_matching.py` | 70 | The Phase 1 -> Phase 2 translation |
| `test_dataset_import.py` | 46 | Loading courses from a file instead of crawling |
| `test_backfill_embeddings.py` | 16 | Free-tier pacing and the embedding checkpoint |
| `test_sync_cricos.py` | 12 | Detecting a new release on data.gov.au |
| `test_embedding_cache.py` | 9 | Query-vector caching on a metered tier |
| `test_auth.py` | 11 | Supabase token verification |
| `test_turn_planning.py` | 10 | When the card reprints, and what the reply may say |

### `test_gpa_converter.py` — the numbers a student acts on

This module is the only place a CGPA becomes a US GPA, a German grade or a UK
classification, so the formulas are pinned by **worked examples** rather than
by re-running the implementation and asserting it matches itself.

- **Modified Bavarian Formula** `V = 1 + 3 × ((Nmax − Nd) / (Nmax − Nmin))` —
  hand-computed cases (80/100 with a 40 pass mark → 2.0), the boundaries (a
  top mark → 1.0, exactly the pass mark → 4.0), clamping below the pass mark,
  and a zero range refused rather than dividing by zero.
- **Country pass marks** — Pakistan passes at 40%, the default assumes 50, and
  the test asserts the choice actually moves the German grade. Getting this
  wrong shifts a student a full grade step.
- **US 4.0 scale** — monotonic across all 101 integer percentages (a higher
  percentage can never yield a lower GPA), round-trips through the anchor
  table, and a source already on the 4.0 scale passes through untouched rather
  than round-tripping through a percentage and accumulating error.
- **UK honours boundaries** — exact edges: 70.0 is a First, 69.9 is a 2:1.
- **Scale normalisation** — percentage, 10-point, 20-point, 5-point and the
  German 1–5 scale, plus an unknown scale with no stated maximum being
  *refused*, because guessing it fabricates every downstream number.
- **Credit weighting** — a 6-credit distinction outweighs a 1-credit pass;
  missing credits fall back to an unweighted mean; nothing numeric returns
  `None` so the agent asks instead of inventing a CGPA.

### `test_extraction.py` — what the agent records about a student

Every case here is a bug reported from the live app, kept as a regression.

- **Field of study is a subject, never a destination** — `in uk`, `at canada`,
  `to germany` and bare country names are all refused, on the model's output
  as well as the regex path. `graphic design`, `IT`, `economics` survive.
- **A degree is a level, not a subject** — answering `BS` sets the level and
  leaves the field empty; `BS computer science` sets both.
- **Names** — typo'd filler trimmed (`ahmad heere` → `Ahmad`), mistyped casing
  normalised (`HAshim`, `hAsHiM` → `Hashim`), deliberate capitalisation
  preserved (`McDonald`, `O'Brien`, `Jan van der Berg`). Phrases that are not
  names at all are **rejected, not trimmed** — trimming once produced the name
  "Pakistan" from "I am from Pakistan".
- **Countries** — typos and short forms resolve (`indiaa`, `srilanka`,
  `saudi`, `czech`); ambiguous prefixes (`united`, `south`) are refused;
  near-misses stay distinct (`chile` ≠ `china`).
- **Country role** — `citizenship` and `study` resolve; `yes`, `ok`, `both`
  resolve to nothing, because a bare "yes" answers an either/or question with
  nothing and must re-ask rather than guess.
- **Noise** — keyboard mashing (`wdladjsdvz`, `qwertyuiop`, `aaaaaa`)
  detected, real messages not. The same test now runs on the *model's* output,
  not just the regex path: mashing answers "what is your name" perfectly well
  syntactically, so a model files it without hesitating, and that was the only
  route by which `dldajsfdk` reached the profile. Pinned against names from
  Polish, Yoruba, Zulu, Vietnamese, Thai, Mandarin and Arabic — wrongly
  refusing a real person's name is far worse than storing one odd string.

### `test_scope.py` — staying on topic without blocking applicants

The policy is **allow-first**, so these tests weight the false-positive side
heavily: wrongly refusing a genuine question is worse than letting a
borderline one through to the model.

- Off-topic refused, including the general-knowledge shapes that name nothing
  suspicious (`where is southafrica`, `who is Elon Musk`).
- Prompt injection caught (`ignore all previous instructions`,
  `show me your system prompt`).
- **Slot answers never blocked** — `Sarah`, `pakistan`, `3.4` carry zero
  study-abroad vocabulary, and a keyword filter would refuse the onboarding
  flow itself.
- Real advisory questions allowed, including ones sharing a grammatical shape
  with the refused set (`where is the campus located?`).
- A study signal outweighs an off-topic word (`does the weather in Canada
  affect student visa timelines?`).

### `test_phase2.py` — the pipeline contracts

- **Schema coercion** — messy page values (`"€9,500 per year"`, `"Master's"`,
  `"IELTS 6.5"`) coerced; USD derived when absent; out-of-range values
  (IELTS 12, GPA 140) rejected. **Vague deadlines become NULL, never a guess**
  — a student plans around those.
- **Crawler output parsing** — block lists unwrapped, error blocks discarded,
  non-course pages and non-JSON reported clearly.
- **Step 1, the SQL hard filter** — compiled against the **real Postgres
  dialect** and asserted as emitted, so the predicates are verified rather
  than assumed: numeric limits, `IN` lists, the 500-row cap, cheapest-first
  ordering, and an unstated (NULL) deadline staying eligible rather than being
  read as already passed.
- **Step 2, ranking** — results ordered by similarity rather than SQL order;
  the Qdrant filter restricted to the SQL candidate ids; an empty filter skips
  the vector call entirely; eligible-but-unembedded courses returned unranked
  rather than dropped.
- **Embedding response quirks** — Gemini leaves the first item's `index` null
  while numbering the rest, which crashed a plain sort with
  `'<' not supported between int and NoneType`; OpenAI numbers every item and
  may reorder them. Both shapes are pinned, plus a width mismatch being
  reported at the source instead of as an opaque Qdrant rejection.

### `test_course_matching.py` — where the two phases must agree

The seam is a translation layer, and its failures are silent: the search
filter compares strings and numbers exactly, so a mismatch shows up as an
empty grid, not an error.

- **Country spelling** — the live bug. The interview canonicalises a
  destination to `UK`; every crawled page stored `United Kingdom`; the exact
  filter matched none of them. The destination now expands to its whole alias
  set, and `Europe` expands to countries rather than being filtered on
  literally.
- **Degree level** — the filter targets the qualification being *applied for*,
  not the one held, or it returns the course the student just finished.
- **One grade, one number** — the card's normalised percentage is asserted to
  be the same value the filter uses.
- **What is deliberately not filtered** — tuition (no budget is ever
  collected) and an unheld IELTS band ("planned" means unknown, and filtering
  on an unknown drops every course stating a requirement).
- **Relevance floor** — the other live bug. An English Literature graduate was
  shown a literature MA at 0.647 followed by three data-science degrees at
  0.555, 0.547 and 0.540: all four passed the grade and country filters, and
  ranking put the wrong three second to fourth because nothing else was left
  to rank. The tests pin both cuts against the real measured scores — the tail
  below the cliff dropped, a genuine cluster kept whole, and a subject the
  index does not cover returning nothing rather than the best of a bad set.

### `test_dataset_import.py` — loading courses from a file

The importer exists so the index can be filled without going out to the live
web. Its failure mode is not a crash but a **silent half-import**, so the
tests weight reporting as heavily as parsing.

- **Column mapping** — real header spellings (`Programme Name`, `Institution`,
  `Tuition Fees`, `IELTS Requirement`, `Work Rights`) resolving on their own;
  an explicit override beating the guess; an override naming a field that does
  not exist refused rather than ignored.
- **File shapes** — CSV, TSV, JSON Lines, a bare JSON list, and the envelope
  keys APIs actually use (`data`, `results`, `courses`, `items`, `records`),
  so a saved API response imports unedited. An unrecognised envelope names the
  keys it did find instead of saying "no records".
- **Coercion** — `£24,500`, `MA` / `Master's` / `postgraduate`, `yes` / `TRUE`
  / `1`, and the placeholder blanks (`n/a`, `TBC`, `-`) becoming *absent*
  rather than text — an invented deadline is something a student plans around.
- **Refusing rather than guessing** — out-of-range values rejected, not
  clamped (IELTS 99 is a misread of the source); every rejected row reported
  with its number and failing fields; ignored columns named.
- **Ragged rows** — `csv.DictReader` files an over-long row's overflow under a
  `None` key, which crashed both the header scan and the ignored-column
  report. Found by these tests, not in production.

### `test_phase2_qdrant.py` — real vector search

Not fakes: `AsyncQdrantClient(":memory:")` runs Qdrant's own local engine, so
collection creation, payload indexing, `MatchAny` filtering and cosine ranking
behave as they do against a server.

The load-bearing test is **`test_ineligible_courses_cannot_be_ranked_in`**: a
course whose syllabus is an *exact* match for the query, but which the SQL
filter rejected on budget, must not surface. That is the entire guarantee of
the two-step design — a semantic search alone will happily return a course the
student cannot afford.

---

## Coverage

Branch coverage, `app/` only, entry points omitted (see `.coveragerc`).

| Module | Cover | Note |
| --- | ---: | --- |
| `scope.py` | 96% | |
| `services/phase2/schemas.py` | 92% | |
| `services/phase2/hybrid_search_service.py` | 88% | |
| `gpa_converter.py` | 86% | |
| `config.py` | 83% | |
| `schemas.py` | 67% | |
| `services/phase2/embeddings.py` | 67% | |
| `llm_service.py` | 56% | uncovered half is the live LLM calls |
| `services/phase2/db.py` | 55% | engine/session wiring needs a live Postgres |
| `services/phase2/crawler_service.py` | 36% | uncovered part is Crawl4AI + browser |
| `services/phase2/ingestion_service.py` | 21% | uncovered part needs both stores |
| `diagnostics.py` | 0% | **gap — see below** |
| `main.py` | 0% | **gap — see below** |
| `ocr_service.py` | 0% | needs a vision API call |
| `session_store.py` | 0% | **gap — see below** |
| **TOTAL** | **44%** | |

### Reading that number honestly

44% is low, and the shape matters more than the figure. The modules that
*compute* things a student acts on are well covered — grade conversion at 86%,
the scope guardrail at 96%, the search filter at 88%. What is uncovered splits
into two kinds:

**Uncovered because it is I/O.** `crawler_service` is mostly Crawl4AI driving
a real browser; `ingestion_service` and `db` need a live Postgres and Qdrant;
`ocr_service` needs a vision API call; half of `llm_service` is the streaming
provider call. These are exercised by the manual `live_*.py` scripts in this
folder, which run against the real stack — that is how the Phase 2 pipeline
was verified end to end on a live TUM page.

**Genuine gaps worth closing.** `main.py` (the SSE endpoint and turn planner),
`diagnostics.py` (card assembly and country eligibility rules) and
`session_store.py` all sit at 0%. They *were* covered by an end-to-end suite
that drove the FastAPI app through `httpx.ASGITransport`, but those files were
kept in a temp scratchpad and were lost when it was cleared between sessions.
The extraction, converter and scope tests have since been rebuilt; the
endpoint-level ones have not. `main.py` at 0% is the most significant: the
confirmation gate, the ambiguity questions and the "card emitted once" rule
are all logic in that file with no automated test behind them.

### Manual scripts (not collected by pytest)

`live_phase2.py`, `live_phase3.py`, `live_in_uk.py`, `live_bs_level.py` hit the real databases
and the live API. They are named `live_*` so pytest ignores them; run one
directly when you want an end-to-end check:

```bash
.venv/Scripts/python.exe -m tests.live_phase2   # crawl -> ingest -> search
.venv/Scripts/python.exe -m tests.live_phase3   # profile -> card -> matches
```

`live_phase3.py` is the Phase 3 seam: it builds a completed profile, runs the
diagnostic card, and feeds the card's normalised percentage into the Phase 2
hard filter — the one place where a mismatch between the two phases would
show up as courses the student does not actually qualify for.
