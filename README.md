# Bid Draft Agent

Turns a contractor's bid schedule (PDF/Excel) plus their company rate card
into a draft, itemized estimate for a human estimator to review.

**Status:** the backend pipeline works end to end from the command line and
the API: parse -> extract (LLM) -> map to production rates (LLM) -> price
(code) -> review (code). No frontend yet.

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
    main.py                 FastAPI app (GET /health, POST /estimates/draft)
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
    pricing/rate_cards.py   rate card loader
  data/rate_cards/          sample rate card (fictional "Northline Mechanical")
  data/bids/                three synthetic sample bid schedules
  scripts/
    draft_estimate.py       CLI
    consistency_check.py    runs the pipeline repeatedly and compares the results
    make_sample_bids.py     regenerates data/bids/
  tests/
frontend/                   empty for now
```

## Running

Requires [uv](https://docs.astral.sh/uv/). Copy `.env.example` to `.env` and
set `GROQ_API_KEY` (free key at https://console.groq.com/keys). From
`backend/`:

```sh
uv sync                                  # install dependencies
uv run pytest                            # run the tests (never calls the API)
uv run pytest -m live                    # one test against the real API
uv run uvicorn app.main:app --reload     # start the server
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

```sh
curl -F "file=@data/bids/clean_bid.xlsx" http://127.0.0.1:8000/estimates/draft
```

Returns the `Estimate` JSON, priced against the default sample rate card:
`lines`, `totals`, `all_flags`, `review` (the review summary) and
`skipped_rows` (rows not treated as bid items, each with `source_ref`,
`description` and `reason`).
Errors: 415 unsupported file type, 422 unreadable document (e.g. scanned
PDF), 502 LLM failure, 503 rate limited or `GROQ_API_KEY` missing.

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
