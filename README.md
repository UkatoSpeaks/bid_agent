# Bid Draft Agent

Turns a contractor's bid schedule (PDF/Excel) plus their company rate card
into a draft, itemized estimate for a human estimator to review.

**Status:** the backend pipeline works end to end from the command line and
the API: parse -> extract (LLM) -> map to rate card (LLM) -> price (code).
No frontend yet.

## Principle: the LLM extracts, code computes

The LLM's job is limited to reading the bid schedule and classifying each
line against rate card codes. It never produces a price, and it is never
shown one.

All arithmetic is done by `backend/app/pricing/engine.py`, a pure function:

```python
price_estimate(lines: list[BidLineItem], rate_card: RateCard) -> Estimate
```

- No I/O, no randomness, no LLM: the same input always gives the same output.
- All money and quantities are `Decimal`, never `float`.
- Every priced line carries a `calculation_trace` showing each multiplication,
  e.g. `Labor: 12 EA x 2.5 hrs x $85.00/hr (HVAC Technician) = $2,550.00`.
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
  -> map       app/extraction/map.py       LLM call #2, then checks in code
  -> price     app/pricing/engine.py       all arithmetic, no LLM
  -> Estimate  lines, calculation traces, assumptions, flags, totals
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
   written*, unit, the ref of the row it came from, and a note for anything
   ambiguous. It is told to skip headers, section titles and (sub)total rows,
   and never to compute or infer a quantity.
3. **Map.** For each line (in batches of 5) the LLM gets a list of candidate
   rate card entries (code, description and unit, never prices) and returns
   components: code, type, quantity per unit of the bid line, a confidence
   and a one-line rationale. The candidate list is the whole rate card when
   it has fewer than 40 entries, otherwise a rapidfuzz shortlist of the 8
   most similar entries per type.
4. **Price.** The verified lines go to `price_estimate()`.

### Hallucination checks

The LLM's output is never trusted. After each call, code checks it against
the document and the rate card and turns every problem into a flag:

| Flag | Severity | Check |
| --- | --- | --- |
| `QUANTITY_NOT_IN_SOURCE` | blocker | The quantity is not written in the row the LLM cited. It must match a whole number in that row (`2` is not found in `12` or `2.5`); another spelling of the same number (`1150` for `1,150`) is accepted. |
| `UNKNOWN_SOURCE_REF` | blocker | The cited row does not exist in the document. |
| `QUANTITY_NOT_NUMERIC` | blocker | The quantity is not a number (`TBD`, blank). The line keeps quantity 0. |
| `EXTRACTION_NOTE` | info | The LLM's own note about an ambiguity. |
| `UNKNOWN_RATE_CODE` | blocker | The LLM proposed a code that is not in the rate card under that type. The component is dropped. |
| `INVALID_QUANTITY_PER_UNIT` | blocker | A component quantity that is not a non-negative number. The component is dropped. |
| `LOW_CONFIDENCE_MAPPING` | warning | The LLM marked a component as a guess. |
| `NO_RATE_CARD_MATCH` | warning | The LLM's reason for mapping nothing, or only part of the work. |
| `MAPPING_MISSING` | blocker | The LLM returned no mapping for a line. |

Also:

- Header and subtotal/total rows that the LLM returns anyway are recognised
  in code, dropped, and reported as "rows not treated as bid items" instead
  of being priced.
- Every component the LLM proposes is recorded on the line in `assumptions`
  (code, quantity per unit, confidence, rationale). Production rates such as
  labor hours per unit are the LLM's assumptions, not facts from the document
  or the rate card, and they usually drive most of the labor cost. They are
  what a reviewer most needs to check.
- A line with a blocker stays in the estimate, priced at 0 where it cannot be
  priced, so the grand total of a draft with blockers is incomplete.

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
by model + prompt + schema, so repeated runs do not call the API. Set
`LLM_CACHE=false` to disable the cache.

## Pricing order of operations

Per line: `component cost = line quantity x quantity_per_unit x rate`, summed
into the line's labor, material and equipment costs (direct costs only).

Across the estimate:

1. `direct_labor`, `direct_material`, `direct_equipment` = sums of line costs
2. `material_markup = direct_material x material_markup_pct`
3. `sales_tax = (direct_material + material_markup) x sales_tax_pct_on_materials`
4. `subtotal = direct_labor + direct_material + material_markup + sales_tax + direct_equipment`
5. `overhead = round(subtotal x overhead_pct)`
6. `profit = round((subtotal + overhead) x profit_pct)`
7. `grand_total = round(subtotal) + overhead + profit`

Percentages in the rate card are written as percent (`15` means 15%).

**Rounding:** 2 decimals, `ROUND_HALF_UP`. Line costs are rounded once per
line. Markup, tax and subtotal chain at full precision and are rounded when
reported. Overhead and profit are calculated from the unrounded subtotal,
rounded, and then summed, so the displayed subtotal + overhead + profit
always equals the displayed grand total exactly. See the docstring in
`engine.py`.

## Layout

```
backend/
  app/
    main.py                 FastAPI app (GET /health, POST /estimates/draft)
    config.py               settings from environment / .env
    pipeline.py             draft_estimate(): parse -> extract -> map -> price
    schemas/                Pydantic v2 models (RateCard, BidLineItem, Estimate, ...)
    llm/                    LLMClient interface, Groq implementation, cache
    parsing/                PDF / Excel / CSV -> rows with source refs
    extraction/extract.py   LLM call #1 and its checks
    extraction/map.py       LLM call #2 and its checks
    pricing/engine.py       deterministic pricing engine
    pricing/rate_cards.py   rate card loader
  data/rate_cards/          sample rate card (fictional "Northline Mechanical")
  data/bids/                three synthetic sample bid schedules
  scripts/
    draft_estimate.py       CLI
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

This prints each line with its source ref, assumptions, calculation trace and
flags, then the totals and a flag summary. Options: `--json` prints the
`Estimate` as JSON, `--rate-card PATH` uses another rate card.

On Groq's free tier a first run may pause on rate limits (it logs
`Groq rate limit hit ... waiting`); a second run of the same file is served
from the cache.

The sample bids are synthetic. Regenerate them with
`uv run python scripts/make_sample_bids.py`.

### API

```sh
curl -F "file=@data/bids/clean_bid.xlsx" http://127.0.0.1:8000/estimates/draft
```

Returns the `Estimate` JSON, priced against the default sample rate card.
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
