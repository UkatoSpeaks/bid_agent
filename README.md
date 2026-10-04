# Bid Draft Agent

Turns a contractor's bid schedule (PDF/Excel) plus their company rate card
into a draft, itemized estimate for a human estimator to review.

**Status:** the backend pipeline works end to end from the command line and
the API: parse -> extract (LLM) -> map to production rates (LLM) -> price
(code) -> review (code). The review UI in `frontend/` takes an estimator from
handing off a bid to an approved, exported estimate. State lives in the
browser; there is no database yet.

## Quick start

Two terminals. Requires [uv](https://docs.astral.sh/uv/) and Node.js 20.9+.

```sh
# 1. Backend, from backend/  (needs GROQ_API_KEY in .env, see "Running")
uv sync
uv run uvicorn app.main:app --port 8010

# 2. Frontend, from frontend/
npm install
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://127.0.0.1:8010
npm run dev
```

Open http://localhost:3000 and pick one of the three sample bids.

The backend port is your choice; 8010 is used here because 8000 is often
taken. If you change it, change `NEXT_PUBLIC_API_URL` in
`frontend/.env.local` to match and restart `npm run dev`. If the frontend
runs on another origin than `http://localhost:3000`, add it to
`CORS_ORIGINS` in `.env`.

## Principle: the LLM extracts and classifies, company data and code do the rest

The LLM's job is limited to reading the bid schedule and choosing, for each
line, which of the company's standard production rates covers the work. It
never produces a price, and it is never shown one.

- **Prices** come from the rate card.
- **Production rates** (labor hours, material and equipment per unit of
  installed work) come from the rate card too. They drive most of an
  estimate, so they are company data, not something the LLM may guess. If no
  company rate fits a line, the LLM may propose its own quantities, and that
  line is always flagged, whatever confidence the LLM reports.
- **Arithmetic** is done by `backend/app/pricing/engine.py`, a pure function:

  ```python
  price_estimate(lines: list[BidLineItem], rate_card: RateCard) -> Estimate
  ```

  - No I/O, no randomness, no LLM: the same input always gives the same output.
  - All money and quantities are `Decimal`, never `float`.
  - Every priced line carries a `calculation_trace` showing each
    multiplication, e.g.
    `Labor: 12 EA x 2.5 hrs x $85.00/hr (HVAC Technician) = $2,550.00`.
  - The engine never guesses. Problems become flags for the estimator:

    | Flag | Severity | Effect |
    | --- | --- | --- |
    | `UNKNOWN_RATE_CODE` | blocker | component skipped, adds 0 |
    | `NEGATIVE_QUANTITY` | blocker | line not priced, adds 0 |
    | `NO_COMPONENTS` | blocker | line adds 0 |
    | `ZERO_QUANTITY` | warning | line prices to 0 |

## Pipeline

```
bid schedule (PDF / Excel / CSV)
  -> parse     app/parsing/                raw rows, each with a source ref
  -> extract   app/extraction/extract.py   LLM call #1, then checks in code
  -> map       app/extraction/map.py       LLM call #2 picks a production rate;
                                           code expands it into components
  -> price     app/pricing/engine.py       all arithmetic, no LLM
  -> review    app/pricing/review.py       impact flags and review summary, no LLM
  -> Estimate  lines, calculation traces, assumptions, flags, totals, review
```

1. **Parse.** `parse_bid_document(path)` returns every row or text line as
   written, with a source ref: `p2-t1-r4` (PDF page 2, table 1, row 4),
   `p2-l7` (PDF page 2, text line 7), `Base Bid!R5` (Excel sheet and row),
   `R5` (CSV row). PDFs use table extraction (pdfplumber) and fall back to
   page text; Excel reads every sheet. Nothing is interpreted at this stage.
   Unsupported file types and PDFs with no text layer (scans) raise a clear
   error.
2. **Extract.** The LLM is shown the rows with their refs and returns, per
   bid item: item number, description, quantity *as a string exactly as
   written*, unit, the ref of the row it came from, a note for anything
   ambiguous, and whether the scope is `clear` or `vague` (with a reason). It
   is told to skip headers, section titles and (sub)total rows, and never to
   compute or infer a quantity.
3. **Map.** For each line (in batches of 5) the LLM gets the company's
   production rates (code, description and unit; never the hours inside them
   and never prices) and returns one `production_rate_code` with a confidence
   and a one-line rationale. Code then expands that production rate into the
   line's components. The list is the whole set when there are fewer than 40
   production rates, otherwise a rapidfuzz shortlist of the 8 whose
   descriptions best match each line.

   Only if no production rate fits may the LLM propose components from the
   rate card with its own quantity per unit. Such a line is always flagged
   `ASSUMED_PRODUCTION_RATE`.
4. **Price.** The verified lines go to `price_estimate()`.
5. **Review.** `review_estimate()` works out each line's share of the
   subtotal, flags the lines that matter most and builds the review summary.

### Production rates

A production rate is the company's standard recipe for one unit of installed
work. It lives in the rate card under `production_rates`:

```json
{
  "code": "PR-DUCT-SPIRAL-12",
  "description": "Spiral round duct, up to 12 in diameter, installed",
  "unit": "LF",
  "components": [
    { "type": "material", "rate_card_code": "MAT-DUCT-SPIRAL-12", "quantity_per_unit": "1" },
    { "type": "labor", "rate_card_code": "LAB-SHMT", "quantity_per_unit": "0.18" }
  ],
  "notes": "..."
}
```

`unit` is the bid unit the rate is per. The rate card is validated on load:
production rate codes must be unique, each needs at least one component, and
every `rate_card_code` must exist in the rate card under the stated type. A
card that fails is rejected.

The 15 production rates in `data/rate_cards/hvac_rate_card.json` are
**illustrative values for a fictional company**, written for the sample
bids. They are not measured crew productivity (see `production_rates_note` in
the file).

### Checks on the LLM's output

The LLM's output is never trusted. After each call, code checks it against
the document and the rate card and turns every problem into a flag:

| Flag | Severity | Check |
| --- | --- | --- |
| `QUANTITY_NOT_IN_SOURCE` | blocker | The quantity is not written in the row the LLM cited. It must match a whole number in that row (`2` is not found in `12` or `2.5`); another spelling of the same number (`1150` for `1,150`) is accepted. |
| `UNKNOWN_SOURCE_REF` | blocker | The cited row does not exist in the document. |
| `QUANTITY_NOT_NUMERIC` | blocker | The quantity is not a number (`TBD`, blank). The line keeps quantity 0. |
| `EXTRACTION_NOTE` | info | The LLM's own note about an ambiguity. |
| `VAGUE_SCOPE` | warning | The LLM marked the scope as vague, **or** the description contains a phrase such as "as required", "as needed", "misc.", "allowance", "TBD", "per plans", "per specifications" or "etc." The phrase check runs in code, so the flag does not depend on the LLM noticing. One flag per line, carrying both reasons. |
| `UNKNOWN_PRODUCTION_RATE` | blocker | The LLM chose a production rate code that is not in the rate card. Nothing is priced for the line. |
| `UNIT_MISMATCH` | blocker | The bid line's unit is not the production rate's unit, so its per-unit quantities do not apply. Its components are not priced. Units are normalised first (`each`, `Each`, `ea.` = `EA`; `lin. ft`, `linear feet` = `LF`; see `app/units.py`). Nothing is converted between units. |
| `ASSUMED_PRODUCTION_RATE` | warning, or blocker on a high-impact line | No production rate was used and the quantities per unit were guessed by the LLM. Raised regardless of confidence; the message lists every guessed number. |
| `UNKNOWN_RATE_CODE` | blocker | The LLM proposed a component code that is not in the rate card under that type. The component is dropped. |
| `INVALID_QUANTITY_PER_UNIT` | blocker | A proposed component quantity that is not a non-negative number. The component is dropped. |
| `LOW_CONFIDENCE_MAPPING` | warning | The LLM marked its choice as a guess. |
| `NO_RATE_CARD_MATCH` | warning | The LLM's reason for mapping nothing, or only part of the work. |
| `PROPOSED_COMPONENTS_IGNORED` | info | The LLM chose a production rate and also proposed components. Only the production rate is used. |
| `MAPPING_MISSING` | blocker | The LLM returned no mapping for a line. |
| `STANDARD_RATE_DECLINED` | warning | The LLM used no production rate for the line, although one in the line's unit matches its description with a score of at least `STANDARD_RATE_DECLINED_SCORE` (default 85 of 100). The flag names that rate (`suggested_production_rate_code`) and the UI offers it as a one-click button. It only suggests: the line keeps the LLM's numbers until a reviewer applies it. |

The score for `STANDARD_RATE_DECLINED` is rapidfuzz's `token_set_ratio`
between the two descriptions after lower-casing and removing punctuation and
plural "s", so "Supply registers" scores 100 against "Supply register, 10 x
6, installed". Rates in another unit are never suggested, because applying
one would only produce a `UNIT_MISMATCH`.

Also:

- Header and subtotal/total rows that the LLM returns anyway are recognised
  in code, dropped, and reported in `Estimate.skipped_rows` (source ref,
  description and reason) instead of being priced.
- Every line records in `assumptions` which production rate was chosen and
  each component it expands to, marked `[company standard PR-...]` or
  `[ASSUMED by the LLM, ...]`.
- A line with a blocker stays in the estimate, priced at 0 where it cannot be
  priced, so the grand total of a draft with blockers is incomplete.

### Review by dollar impact

After pricing, `review_estimate()` adds, in code:

| Flag | Severity | Rule |
| --- | --- | --- |
| `HIGH_IMPACT_LINE` | warning | The line is more than 15% of the subtotal (`HIGH_IMPACT_LINE_PCT`), so the reviewer checks the biggest numbers first. |
| `ASSUMED_PRODUCTION_RATE` | raised to blocker | The line is high-impact *and* rests on an assumed production rate. |

Each line gets `rate_basis` (`standard`, `assumed` or `none`),
`production_rate_code` and `subtotal_share_pct`. The estimate gets a `review`
summary:

| Field | |
| --- | --- |
| `blocker_count`, `warning_count`, `info_count` | flag counts |
| `standard_rate_pct` | share of the subtotal priced from company standard production rates. **The key number for the UI.** |
| `assumed_rate_pct` | share resting on rates assumed by the LLM (`100 - standard_rate_pct`) |
| `lines_on_standard_rates`, `lines_on_assumed_rates`, `lines_not_priced` | line counts |
| `high_impact_threshold_pct`, `high_impact_line_ids` | the threshold used and the lines above it |

A line's share of the subtotal is its direct cost with its own material
markup and sales tax added (`labor + equipment + material x (1 + markup) x
(1 + tax)`), divided by the sum of those for all lines. That is what the line
contributes to the subtotal, and the shares add up to 100%.

### LLM client

`app/llm/` is the only place that imports a provider SDK. Everything else
uses one method:

```python
LLMClient.structured(prompt: str, schema: type[BaseModel]) -> BaseModel
```

The Groq implementation uses Structured Outputs (`response_format` of type
`json_schema` in strict mode; no streaming, no tool calls), validates every
reply with Pydantic, retries once with the validation error added to the
prompt, and backs off exponentially on HTTP 429 (up to 4 attempts, honouring
`Retry-After`). Parsed responses are cached in `backend/.cache/llm/`, keyed
by model + prompt + schema + temperature + reasoning effort, so repeated runs
do not call the API. Set `LLM_CACHE=false` to disable the cache.

## Reviewer edits and repricing

`backend/app/pricing/reviewer.py` applies an estimator's edits and prices the
estimate again. Like the engine it is pure code: no LLM, no I/O. The edits
are always applied to the lines as they were drafted
(`Estimate.source_lines`), never to an already edited estimate, so the same
lines and edits always give the same result and removing an edit restores
the draft.

| Reviewer action | Effect |
| --- | --- |
| Set the quantity | The line is repriced. `QUANTITY_NOT_NUMERIC` and `QUANTITY_NOT_IN_SOURCE` are removed: they are checks on what the LLM extracted, not on a number the reviewer typed. |
| Choose a production rate | The line's components are replaced by that rate's and the flags about the LLM's mapping are removed. The unit is checked again (`UNIT_MISMATCH`). |
| Mark reviewed | Resolves the line's warnings, info flags and the blockers that only ask for a confirmation: `ASSUMED_PRODUCTION_RATE`, `QUANTITY_NOT_IN_SOURCE`, `UNKNOWN_SOURCE_REF`. Any other blocker means the line is not priced properly and stays open until the line is fixed or excluded. |
| Exclude, with a reason | The line stays in the list, priced at 0 and out of every share and total. All of its flags are resolved. |

Resolved flags stay on the line (`Flag.resolved`) but are not counted in the
review summary. `review.ready_to_approve` is true when no blocker is
unresolved and at least one line is left in the estimate.

## The review UI

`frontend/` is a Next.js app (App Router, TypeScript, Tailwind, shadcn/ui,
TanStack Table). One page, three steps:

1. **01 You hand off.** Upload a bid schedule or pick a sample. Shows the
   rate card in use, with a dialog to read all of it.
2. **02 The agent works.** The five pipeline steps. The backend answers
   once, when all of them are done, so while it runs the steps are shown as
   one sequence in progress with a real elapsed-time counter, and they
   complete together. Each then shows what it produced, taken from the
   response.
3. **03 What comes back.** Summary header (grand total, share of the
   subtotal on company standard rates, open blockers and warnings, approve
   status), "Review first", the estimate table, skipped rows, totals and
   the audit log. Selecting a line opens the side panel, **where your people
   step in**: source reference, calculation trace, the LLM's rationale and
   confidence, assumptions, flags, and the reviewer actions.

The frontend never calculates money. Every edit goes to
`POST /estimates/reprice` and the screen shows what comes back; the totals
card prints the backend's figures as they are. Approval is disabled while
`review.ready_to_approve` is false or any blocker flag is unresolved.

The audit log records each reviewer action (who, what, before, after, time)
in the browser and goes into the Excel export.

**Design tokens.** Colours, fonts and the corner radius are defined once, at
the top of `frontend/app/globals.css` (`--brand`, `--ink`, `--surface`,
`--night`, the status colours, ...), and exposed as Tailwind utilities
(`bg-brand`, `text-ink`, `border-line`, ...). The two fonts are chosen in
`frontend/app/layout.tsx`.

### Screenshots to take for a demo

Run both servers and use a 1440 px wide browser window. The sample bids are
served from the LLM cache after their first run, so they return in under a
second; run each once before recording.

| # | Screen | How to get there | What it shows |
| --- | --- | --- | --- |
| 1 | Hand off | Open the app | The upload card, the three sample bids, the rate card in use |
| 2 | Rate card | "View rate card" | Production rates are company data, with the "illustrative values" note |
| 3 | The agent works | Click "Clean bid" | Five steps done, each with its real result |
| 4 | A clean result | Scroll to "What comes back" | 100.0% on company standard rates, 0 blockers, "Ready to approve" |
| 5 | A result that needs a person | "New bid", then "Tricky bid" | 2 blockers, approval locked, "Review first" sorted by severity then dollars |
| 6 | Side panel | Click item B-5 | Source reference `Base Bid!R9`, the trace, the "TBD" quantity blocker |
| 7 | Edit and reprice | Type 40 as the quantity, "Reprice" | The line and the grand total change; one blocker fewer |
| 8 | Reviewing is not enough | Open B-6, "Mark reviewed" | The message that a line that is not priced must be fixed or excluded |
| 9 | Exclude with a reason | "Exclude line" on B-6 | The reason is required; the line is struck through |
| 10 | An assumed rate | Open ALT-3 | The LLM's guessed quantities, listed in the flag and in the assumptions |
| 11 | Approve | "Mark reviewed" on ALT-3, then "Approve estimate" | The button unlocks once no blocker is open |
| 12 | Audit log and export | Scroll down, "Export .xlsx" | Every action with before and after; open the workbook's three sheets |
| 13 | Messy PDF | "New bid", then "Messy bid" | Mixed units ("each", "ea.", "lin. ft") all mapped; one vague lump sum blocked |

`STANDARD_RATE_DECLINED` appears only when the LLM declines a matching rate,
which it does not do on every run (it did in 1 of 3 consistency-check runs
for "Supply registers" in the messy bid). To record it, run the messy bid
with `LLM_CACHE=false` until the flag shows on item B4, then use "Apply
PR-REG-SUP" in the side panel.

### Design choices where the spec was open

- **What "Reviewed" resolves.** Marking a line reviewed confirms an assumed
  rate or an unverified quantity, but does not clear a blocker that leaves
  the line unpriced (missing quantity, no mapping, unit mismatch). Those
  need a fix or an exclusion. Otherwise a reviewer could approve an
  estimate with a $0 line by clicking through it.
- **Warnings never block approval.** Only unresolved blockers do. Open
  warnings stay visible in the header and in "Review first".
- **Flag counts are of open flags.** The header counts go down as the
  reviewer works. Resolved flags stay on the line, greyed and ticked.
- **Edits are replayed on the draft.** Each reprice sends the untouched
  draft lines plus all edits, so "Reset to draft" is exact and the backend
  holds no state.
- **Excluded lines stay visible**, struck through, with the reason. They
  leave the totals and the percentage shares.
- **An edit after approval withdraws the approval** and says so in the
  audit log.
- **The export reprices on the server.** `POST /estimates/export` takes the
  lines and edits, not a finished estimate, so no figure in the workbook
  comes from the browser. The workbook holds values only, no formulas.
- **Sample bids run on the server** (`POST /estimates/draft/sample/{id}`)
  rather than being downloaded and re-uploaded by the browser.
- **Errors carry a code.** 502 and 503 responses have an `X-Error-Code`
  header (`llm_failed`, `llm_rate_limited`, `llm_not_configured`) so the UI
  can tell a rate limit from a missing API key without parsing the message.
- **The share on standard rates is a number first**, then a two-part bar
  (solid for standard, hatched for assumed) with both parts labelled, so it
  does not rely on colour.
- **"Dollar impact"** in "Review first" is the line subtotal. A blocked line
  priced at $0 therefore sorts last among the blockers.
- **Light theme only.** Dark mode was optional and is not built; the dark
  band of step 02 is part of the light design.
- **Table sorting** is offered on quantity, line subtotal and share only.
- **Fonts:** Figtree and JetBrains Mono, both open source, as the nearest
  match to the reference style.

## Pricing order of operations

Per line: `component cost = line quantity x quantity_per_unit x rate`, summed
into the line's labor, material and equipment costs (direct costs only).

Across the estimate:

1. `direct_labor`, `direct_material`, `direct_equipment` = sums of line costs
2. `material_markup = round(direct_material x material_markup_pct)`
3. `sales_tax = round((direct_material + material_markup) x sales_tax_pct_on_materials)`
4. `subtotal = direct_labor + direct_material + material_markup + sales_tax + direct_equipment`
5. `overhead = round(subtotal x overhead_pct)`
6. `profit = round((subtotal + overhead) x profit_pct)`
7. `grand_total = subtotal + overhead + profit`

Percentages in the rate card are written as percent (`15` means 15%).

**Rounding:** 2 decimals, `ROUND_HALF_UP`. Every displayed figure is rounded
before it is added to another, so every displayed sum foots to the cent: line
costs add up to the direct totals, the five cost categories add up to the
subtotal, and subtotal + overhead + profit is the grand total. Inside a
percentage chain the input stays unrounded (tax uses the unrounded markup,
profit the unrounded overhead). See the docstring in `engine.py`.

## Layout

```
backend/
  app/
    main.py                 FastAPI app: draft, reprice, export, rate card, samples
    export.py               the .xlsx export
    samples.py              the sample bids offered by the API
    config.py               settings from environment / .env
    pipeline.py             draft_estimate(): parse -> extract -> map -> price -> review
    units.py                unit normalisation ("each" = "EA")
    schemas/                Pydantic v2 models (RateCard, ProductionRate, BidLineItem, Estimate, ...)
    llm/                    LLMClient interface, Groq implementation, cache
    parsing/                PDF / Excel / CSV -> rows with source refs
    extraction/extract.py   LLM call #1 and its checks
    extraction/map.py       LLM call #2, production rate expansion and its checks
    pricing/engine.py       deterministic pricing engine
    pricing/review.py       impact flags and review summary
    pricing/reviewer.py     reviewer edits: apply, reprice, resolve flags
    pricing/rate_cards.py   rate card loader
  data/rate_cards/          sample rate card (fictional "Northline Mechanical")
  data/bids/                three synthetic sample bid schedules
  scripts/
    draft_estimate.py       CLI
    consistency_check.py    runs the pipeline repeatedly and compares the results
    make_sample_bids.py     regenerates data/bids/
  tests/
frontend/
  app/                      layout (fonts), globals.css (design tokens), the page
  components/               hand-off, pipeline, rate card dialog, brand pieces
  components/review/        summary header, review first, table, side panel, totals, audit log
  components/ui/            shadcn/ui components
  lib/                      api client, types, formatting, review logic, session state
  tests/                    Vitest: summary header and approve gating
```

## Running

Requires [uv](https://docs.astral.sh/uv/). Copy `.env.example` to `.env` and
set `GROQ_API_KEY` (free key at https://console.groq.com/keys). From
`backend/`:

```sh
uv sync                                  # install dependencies
uv run pytest                            # run the tests (never calls the API)
uv run pytest -m live                    # one test against the real API
uv run uvicorn app.main:app --port 8010 --reload     # start the server
```

From `frontend/`:

```sh
npm install
npm run dev          # http://localhost:3000
npm test             # Vitest: summary header, approve gating, review logic
npm run lint
npm run typecheck
npm run build        # production build
```

### Draft an estimate from the command line

```sh
uv run python scripts/draft_estimate.py data/bids/clean_bid.xlsx
uv run python scripts/draft_estimate.py data/bids/messy_bid.pdf
uv run python scripts/draft_estimate.py data/bids/tricky_bid.xlsx
```

This prints each line with its source ref, rate basis, share of the subtotal,
assumptions, calculation trace and flags, then the totals and the review
summary. Options: `--json` prints the `Estimate` as JSON, `--rate-card PATH`
uses another rate card.

On Groq's free tier a first run may pause on rate limits (it logs
`Groq rate limit hit ... waiting`); a second run of the same file is served
from the cache.

The sample bids are synthetic. Regenerate them with
`uv run python scripts/make_sample_bids.py`.

### Determinism check

```sh
uv run python scripts/consistency_check.py            # the three sample bids, 3 runs each
uv run python scripts/consistency_check.py data/bids/clean_bid.xlsx --runs 5
```

Runs the full pipeline several times per bid with the cache disabled (so
every run calls the API) and reports, per bid, whether the chosen production
rate codes and the grand total were identical across runs. For each line that
differs it says why: the LLM's choice of rate changed, the guessed quantities
on a line without a company rate changed, or the line was extracted
differently. Exit status is 1 if anything differed.

Lines mapped to a company production rate price identically whenever the LLM
picks the same code. Lines with no company rate rest on guessed quantities
and can still vary between runs, which is one more reason they are flagged.

### API

| Endpoint | |
| --- | --- |
| `GET /health` | liveness |
| `GET /rate-card` | the rate card in use, with its production rates |
| `GET /samples` | the three sample bids (`id`, `filename`, `title`, `description`) |
| `POST /estimates/draft` | upload a bid schedule (`file`), get a draft `Estimate` |
| `POST /estimates/draft/sample/{id}` | the same, for a sample bid |
| `POST /estimates/reprice` | apply reviewer edits and price again. No LLM. |
| `POST /estimates/export` | the reviewed estimate as `.xlsx` |

```sh
curl -F "file=@data/bids/clean_bid.xlsx" http://127.0.0.1:8010/estimates/draft
```

Returns the `Estimate` JSON, priced against the default sample rate card:
`lines`, `totals`, `all_flags`, `review` (the review summary),
`skipped_rows` (rows not treated as bid items, each with `source_ref`,
`description` and `reason`) and `source_lines` (the mapped lines before
pricing, which a reprice takes back).
Errors: 415 unsupported file type, 422 unreadable document (e.g. scanned
PDF), 502 LLM failure, 503 rate limited or `GROQ_API_KEY` missing. 502 and
503 carry an `X-Error-Code` header.

**Reprice.** Send the draft's `source_lines` unchanged as `lines`, with one
edit per line the reviewer has touched:

```json
{
  "lines": [ "...Estimate.source_lines..." ],
  "edits": [
    { "line_id": "L005", "quantity": "40" },
    { "line_id": "L008", "production_rate_code": "PR-REG-SUP", "status": "reviewed" },
    { "line_id": "L006", "status": "excluded", "exclusion_reason": "Subcontracted" }
  ],
  "skipped_rows": [ "...Estimate.skipped_rows..." ]
}
```

`status` is `open` (default), `reviewed` or `excluded`. Returns a fresh
`Estimate` with its review summary. 422 if an edit names an unknown line or
production rate, or excludes a line without a reason.

**Export.** The same body plus `audit_log` (entries with `timestamp`, `who`,
`action`, `line_id`, `item_number`, `before`, `after`, `note`) and
`source_filename`. Returns a workbook with three sheets: `Estimate` (lines
and totals), `Flags and assumptions` (each with its status) and `Audit log`.

### Settings (`.env`)

| Name | Default | |
| --- | --- | --- |
| `GROQ_API_KEY` | none | required for the CLI and `POST /estimates/draft` |
| `LLM_MODEL` | `openai/gpt-oss-120b` | |
| `LLM_TEMPERATURE` | `0.2` | |
| `LLM_REASONING_EFFORT` | `medium` | |
| `LLM_CACHE` | `true` | `false` always calls the API |
| `RATE_CARD_PATH` | `data/rate_cards/hvac_rate_card.json` | relative to `backend/` |
| `HIGH_IMPACT_LINE_PCT` | `15` | a line above this share of the subtotal is flagged `HIGH_IMPACT_LINE` |
| `STANDARD_RATE_DECLINED_SCORE` | `85` | match score (0-100) from which a production rate the LLM did not use is suggested |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | browser origins allowed to call the API, comma separated |

The frontend has one setting, in `frontend/.env.local`:
`NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8010`).
