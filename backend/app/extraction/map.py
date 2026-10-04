"""LLM call #2: map each bid line to a company production rate, then verify.

The LLM picks one production rate code per line. Code then expands that
production rate into the line's components, so the labor hours, material and
equipment per unit are the company's numbers, not the LLM's. It never sees a
price.

Only when no production rate fits may the LLM propose components with its own
quantities per unit. Those numbers are guesses, and every such line is
flagged ASSUMED_PRODUCTION_RATE whatever confidence the LLM reports.
"""

from decimal import Decimal
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process

from app.extraction.extract import parse_quantity
from app.llm import LLMClient
from app.schemas import (
    BidLineItem,
    ComponentType,
    Flag,
    LineItemComponent,
    ProductionRate,
    RateCard,
)
from app.units import normalize_unit, units_match

# Lists smaller than this are sent whole; larger ones are shortlisted. Applies
# to the production rates and to the rate card entries separately.
SMALL_RATE_CARD_ENTRIES = 40
SHORTLIST_PER_TYPE = 8
PRODUCTION_RATE_SHORTLIST = 8
# Lines per LLM call. Batching sends the candidate lists once per batch
# instead of once per line, which matters on a tokens-per-minute limit.
LINES_PER_CALL = 5

Confidence = Literal["high", "medium", "low"]


class ProposedComponent(BaseModel):
    """A component with a quantity per unit chosen by the LLM (a guess)."""

    rate_card_code: str = Field(description="A code copied from the rate card entries list.")
    type: ComponentType
    quantity_per_unit: str = Field(
        description=(
            "Amount of this component per ONE unit of the bid line, as a plain "
            "decimal number in the component's own unit, e.g. '2.5'."
        )
    )
    rationale: str = Field(
        description="One line: why this code fits and what quantity_per_unit assumes."
    )


class LineMapping(BaseModel):
    line_id: str
    production_rate_code: str | None = Field(
        description=(
            "A code copied from the standard production rates list, or null if "
            "no standard production rate covers this work."
        )
    )
    confidence: Confidence
    rationale: str = Field(description="One line: why this choice fits the bid line.")
    proposed_components: list[ProposedComponent] = Field(
        description=(
            "Empty when production_rate_code is set. Only when no standard "
            "production rate fits: components with your own quantity_per_unit."
        )
    )
    no_match_reason: str | None = Field(
        description="Why no (or not all of the) work could be mapped, else null."
    )


class LineMappings(BaseModel):
    lines: list[LineMapping]


class Candidate(NamedTuple):
    type: ComponentType
    code: str
    name: str
    unit: str  # the unit quantity_per_unit is measured in


_PROMPT = """You are helping an estimator at {company} ({trade}) price a bid schedule.
For each bid line below, choose the company's standard production rate that covers the work.

Rules:
- A standard production rate already holds the company's labor hours, material and equipment per unit. You only choose its code: never state, adjust or restate those quantities.
- production_rate_code must be copied exactly from the standard production rates list. Never invent a code. When you set it, proposed_components must be an empty list.
- Choose a standard production rate only when it describes the same work as the bid line (same kind of item, same size or capacity where one is stated). Do not pick a poor match just to fill a line.
- Do not reject a standard production rate because of how the unit is written ("each" and "EA" are the same unit). Units are checked afterwards in code.
- Only if no standard production rate fits: set production_rate_code to null and propose components from the rate card entries list, each with the type shown there and your own quantity_per_unit per ONE unit of the bid line, in the entry's own unit (labor in hours). Bid lines are installed work unless they say otherwise ("supply only"), so include labor as well as material, and equipment where the work needs it. Do not multiply by the line quantity. These quantities are your guesses and will be flagged for review, so state what each one assumes in its rationale.
- If nothing in either list fits, set production_rate_code to null, leave proposed_components empty and explain why in no_match_reason. If only part of the work can be mapped, map that part and describe what is missing in no_match_reason. Otherwise no_match_reason is null.
- confidence: "high" when the choice clearly matches the bid line, "medium" when it matches but the bid line leaves a detail open (for example no size is stated), "low" when it is a guess.
- Return exactly one entry per bid line, using its line_id.

Standard production rates (code | description | unit):
{production_rates}

Rate card entries, only for lines with no standard production rate (type | code | description | unit):
{candidates}

Bid lines (line_id | item number | description | unit of the bid line):
{lines}"""


def map_line_items(
    lines: list[BidLineItem], rate_card: RateCard, llm: LLMClient
) -> list[BidLineItem]:
    """Return copies of `lines` with components, assumptions and mapping flags."""
    mapped: list[BidLineItem] = []
    for start in range(0, len(lines), LINES_PER_CALL):
        batch = lines[start : start + LINES_PER_CALL]
        prompt = build_mapping_prompt(
            batch,
            production_rates_for(batch, rate_card),
            candidates_for(batch, rate_card),
            rate_card,
        )
        response = llm.structured(prompt, LineMappings)
        mapped.extend(verify_mappings(batch, response.lines, rate_card))
    return mapped


def all_candidates(rate_card: RateCard) -> list[Candidate]:
    return [
        *(Candidate("labor", r.code, r.role, "hrs") for r in rate_card.labor_rates),
        *(Candidate("material", m.code, m.name, m.unit) for m in rate_card.materials),
        *(Candidate("equipment", e.code, e.name, e.unit) for e in rate_card.equipment),
    ]


def shortlist(
    description: str, rate_card: RateCard, per_type: int = SHORTLIST_PER_TYPE
) -> list[Candidate]:
    """The `per_type` entries of each type most similar to the description."""
    result: list[Candidate] = []
    entries = all_candidates(rate_card)
    for component_type in ("labor", "material", "equipment"):
        of_type = [c for c in entries if c.type == component_type]
        matches = process.extract(
            description,
            {index: c.name for index, c in enumerate(of_type)},
            scorer=fuzz.token_set_ratio,
            processor=str.casefold,
            limit=per_type,
        )
        result.extend(of_type[index] for _name, _score, index in matches)
    return result


def candidates_for(lines: list[BidLineItem], rate_card: RateCard) -> list[Candidate]:
    """Candidates for a batch: the whole card if small, else merged shortlists."""
    entries = all_candidates(rate_card)
    if len(entries) < SMALL_RATE_CARD_ENTRIES:
        return entries
    wanted = {c for line in lines for c in shortlist(line.description, rate_card)}
    return [c for c in entries if c in wanted]  # keep rate card order


def shortlist_production_rates(
    description: str, rate_card: RateCard, limit: int = PRODUCTION_RATE_SHORTLIST
) -> list[ProductionRate]:
    """The `limit` production rates whose descriptions best match the line."""
    rates = rate_card.production_rates
    matches = process.extract(
        description,
        {index: rate.description for index, rate in enumerate(rates)},
        scorer=fuzz.token_set_ratio,
        processor=str.casefold,
        limit=limit,
    )
    return [rates[index] for _description, _score, index in matches]


def production_rates_for(
    lines: list[BidLineItem], rate_card: RateCard
) -> list[ProductionRate]:
    """Production rates for a batch: all if few, else merged shortlists."""
    rates = rate_card.production_rates
    if len(rates) < SMALL_RATE_CARD_ENTRIES:
        return list(rates)
    wanted = {
        rate.code
        for line in lines
        for rate in shortlist_production_rates(line.description, rate_card)
    }
    return [rate for rate in rates if rate.code in wanted]  # keep rate card order


def build_mapping_prompt(
    lines: list[BidLineItem],
    production_rates: list[ProductionRate],
    candidates: list[Candidate],
    rate_card: RateCard,
) -> str:
    return _PROMPT.format(
        company=rate_card.company_name,
        trade=rate_card.trade,
        production_rates="\n".join(
            f"{rate.code} | {rate.description} | {rate.unit}" for rate in production_rates
        )
        or "(none)",
        candidates="\n".join(f"{c.type} | {c.code} | {c.name} | {c.unit}" for c in candidates),
        lines="\n".join(
            f"{line.id} | {line.item_number} | {line.description} | {line.unit}"
            for line in lines
        ),
    )


def verify_mappings(
    lines: list[BidLineItem], mappings: list[LineMapping], rate_card: RateCard
) -> list[BidLineItem]:
    """Apply the LLM's mappings to the lines, keeping only what checks out.

    A line with a valid production rate code gets that rate's components,
    copied from the rate card. Flags added here:

        * UNKNOWN_PRODUCTION_RATE (blocker): the code is not a production
          rate in the rate card; nothing is priced for the line.
        * UNIT_MISMATCH (blocker): the bid line's unit is not the production
          rate's unit (after normalising "each"/"EA" etc.), so its per-unit
          quantities do not apply; its components are not priced.
        * ASSUMED_PRODUCTION_RATE (warning): no production rate was used and
          the LLM proposed its own quantities per unit. Raised whatever the
          LLM's confidence, listing every guessed number.
        * UNKNOWN_RATE_CODE (blocker): a proposed code is not in the rate
          card under the stated type; the component is dropped.
        * INVALID_QUANTITY_PER_UNIT (blocker): a proposed quantity is not a
          non-negative number; the component is dropped.
        * LOW_CONFIDENCE_MAPPING (warning): the LLM was unsure of its choice.
        * NO_RATE_CARD_MATCH (warning): the LLM's reason for mapping nothing,
          or only part of the work.
        * PROPOSED_COMPONENTS_IGNORED (info): the LLM chose a production rate
          and proposed components too; only the production rate is used.
        * MAPPING_MISSING (blocker): the LLM returned nothing for the line.

    Every component that is kept adds one entry to the line's `assumptions`.
    """
    known = {(c.type, c.code): c for c in all_candidates(rate_card)}
    production_rates = {rate.code: rate for rate in rate_card.production_rates}
    by_line_id: dict[str, LineMapping] = {}
    for mapping in mappings:
        by_line_id.setdefault(mapping.line_id.strip(), mapping)

    result: list[BidLineItem] = []
    for line in lines:
        flags = list(line.flags)
        components: list[LineItemComponent] = []
        assumptions = list(line.assumptions)
        production_rate_code: str | None = None

        mapping = by_line_id.get(line.id)
        if mapping is None:
            flags.append(
                Flag(
                    severity="blocker",
                    code="MAPPING_MISSING",
                    message="The LLM returned no rate card mapping for this line.",
                )
            )
        else:
            chosen = (mapping.production_rate_code or "").strip()
            rationale = mapping.rationale.strip()
            if chosen and chosen not in production_rates:
                flags.append(
                    Flag(
                        severity="blocker",
                        code="UNKNOWN_PRODUCTION_RATE",
                        message=(
                            f"The LLM chose production rate '{chosen}', which is "
                            "not in the rate card. Nothing is priced for this "
                            f"line. Its rationale was: {rationale}"
                        ),
                    )
                )
            elif chosen:
                production_rate = production_rates[chosen]
                production_rate_code = chosen
                assumptions.append(
                    f"Standard production rate {chosen} ({production_rate.description}), "
                    f"per {production_rate.unit} [{mapping.confidence} confidence] {rationale}"
                )
                if units_match(line.unit, production_rate.unit):
                    for standard in production_rate.components:
                        candidate = known[(standard.type, standard.rate_card_code)]
                        components.append(
                            LineItemComponent(
                                type=standard.type,
                                rate_card_code=standard.rate_card_code,
                                quantity_per_unit=standard.quantity_per_unit,
                            )
                        )
                        assumptions.append(
                            f"{standard.type.capitalize()} {standard.rate_card_code} "
                            f"({candidate.name}): {_number(standard.quantity_per_unit)} "
                            f"{candidate.unit} per {production_rate.unit} "
                            f"[company standard {chosen}]"
                        )
                else:
                    flags.append(
                        Flag(
                            severity="blocker",
                            code="UNIT_MISMATCH",
                            message=(
                                f"The bid line is in '{line.unit}' "
                                f"({normalize_unit(line.unit) or 'no unit'}) but "
                                f"production rate {chosen} is per "
                                f"{production_rate.unit}. Its components are not "
                                "priced; convert the quantity or choose another rate."
                            ),
                        )
                    )
                if mapping.confidence == "low":
                    flags.append(
                        Flag(
                            severity="warning",
                            code="LOW_CONFIDENCE_MAPPING",
                            message=(
                                f"Low confidence that production rate {chosen} "
                                f"fits this line: {rationale}"
                            ),
                        )
                    )
                if mapping.proposed_components:
                    flags.append(
                        Flag(
                            severity="info",
                            code="PROPOSED_COMPONENTS_IGNORED",
                            message=(
                                f"The LLM also proposed {len(mapping.proposed_components)} "
                                f"component(s) of its own; only standard rate {chosen} "
                                "is used."
                            ),
                        )
                    )
            else:
                guessed: list[str] = []
                for proposed in mapping.proposed_components:
                    code = proposed.rate_card_code.strip()
                    candidate = known.get((proposed.type, code))
                    if candidate is None:
                        flags.append(
                            Flag(
                                severity="blocker",
                                code="UNKNOWN_RATE_CODE",
                                message=(
                                    f"The LLM proposed {proposed.type} code '{code}', "
                                    "which is not in the rate card. Component dropped. "
                                    f"Its rationale was: {proposed.rationale}"
                                ),
                            )
                        )
                        continue

                    quantity_per_unit = parse_quantity(proposed.quantity_per_unit)
                    if quantity_per_unit is None or quantity_per_unit < 0:
                        flags.append(
                            Flag(
                                severity="blocker",
                                code="INVALID_QUANTITY_PER_UNIT",
                                message=(
                                    f"The LLM proposed '{proposed.quantity_per_unit}' "
                                    f"{candidate.unit} of {code} per {line.unit}, which is "
                                    "not a non-negative number. Component dropped."
                                ),
                            )
                        )
                        continue

                    components.append(
                        LineItemComponent(
                            type=proposed.type,
                            rate_card_code=code,
                            quantity_per_unit=quantity_per_unit,
                        )
                    )
                    amount = f"{_number(quantity_per_unit)} {candidate.unit} per {line.unit}"
                    assumptions.append(
                        f"{proposed.type.capitalize()} {code} ({candidate.name}): {amount} "
                        f"[ASSUMED by the LLM, {mapping.confidence} confidence] "
                        f"{proposed.rationale.strip()}"
                    )
                    guessed.append(f"{amount} of {code} ({candidate.name})")

                if guessed:
                    flags.append(
                        Flag(
                            severity="warning",
                            code="ASSUMED_PRODUCTION_RATE",
                            message=(
                                "No company production rate was used for this line. "
                                "These quantities per unit were guessed by the LLM "
                                "and must be checked: " + "; ".join(guessed) + "."
                            ),
                        )
                    )
                    if mapping.confidence == "low":
                        flags.append(
                            Flag(
                                severity="warning",
                                code="LOW_CONFIDENCE_MAPPING",
                                message=f"Low confidence in the proposed components: {rationale}",
                            )
                        )

            if mapping.no_match_reason and mapping.no_match_reason.strip():
                flags.append(
                    Flag(
                        severity="warning",
                        code="NO_RATE_CARD_MATCH",
                        message=mapping.no_match_reason.strip(),
                    )
                )

        result.append(
            line.model_copy(
                update={
                    "components": components,
                    "flags": flags,
                    "assumptions": assumptions,
                    "production_rate_code": production_rate_code,
                }
            )
        )
    return result


def _number(value: Decimal) -> str:
    return f"{value.normalize():,f}"
