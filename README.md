# Bid Draft Agent

Turns a contractor's bid schedule (PDF/Excel) plus their company rate card
into a draft, itemized estimate for a human estimator to review.

**Status:** project foundation and pricing engine only. No LLM calls and no
frontend yet.

## Principle: the LLM extracts, code computes

The LLM's job is limited to reading the bid schedule and classifying each
line against rate card codes. It never produces a price.

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

## Pricing order of operations

Per line: `component cost = line quantity x quantity_per_unit x rate`, summed
into the line's labor, material and equipment costs (direct costs only).

Across the estimate:

1. `direct_labor`, `direct_material`, `direct_equipment` = sums of line costs
2. `material_markup = direct_material x material_markup_pct`
3. `sales_tax = (direct_material + material_markup) x sales_tax_pct_on_materials`
4. `subtotal = direct_labor + direct_material + material_markup + sales_tax + direct_equipment`
5. `overhead = subtotal x overhead_pct`
6. `profit = (subtotal + overhead) x profit_pct`
7. `grand_total = subtotal + overhead + profit`

Percentages in the rate card are written as percent (`15` means 15%).

**Rounding:** 2 decimals, `ROUND_HALF_UP`, applied only at line level and on
the final reported totals, never mid-calculation. Because steps 2-7 chain at
full precision, a reported total can differ by one cent from re-adding the
reported figures above it. See the docstring in `engine.py`.

## Layout

```
backend/
  app/
    main.py                 FastAPI app (GET /health)
    config.py               settings from environment / .env
    schemas/                Pydantic v2 models (RateCard, BidLineItem, Estimate, ...)
    pricing/engine.py       deterministic pricing engine
    pricing/rate_cards.py   rate card loader
  data/rate_cards/          sample rate card (fictional "Northline Mechanical")
  tests/
frontend/                   empty for now
```

## Running

Requires [uv](https://docs.astral.sh/uv/). From `backend/`:

```sh
uv sync                                  # install dependencies
uv run pytest                            # run the tests
uv run uvicorn app.main:app --reload     # start the server
```

Then open http://127.0.0.1:8000/health.

Configuration is optional: copy `.env.example` to `.env` to override defaults.
