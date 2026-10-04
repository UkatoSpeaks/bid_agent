"""LLM call #2: map each bid line to rate card components, then verify.

The LLM picks rate card codes and proposes a quantity of each per unit of the
bid line (e.g. labor hours per unit installed). It never sees a price. Its
choices are checked in code, and every proposed quantity is recorded on the
line as an assumption for the reviewer.
"""

from decimal import Decimal
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process

from app.extraction.extract import parse_quantity
from app.llm import LLMClient
from app.schemas import BidLineItem, ComponentType, Flag, LineItemComponent, RateCard

# Rate cards smaller than this are sent whole; larger ones are shortlisted.
SMALL_RATE_CARD_ENTRIES = 40
SHORTLIST_PER_TYPE = 8
# Lines per LLM call. Batching sends the candidate list once per batch
# instead of once per line, which matters on a tokens-per-minute limit.
LINES_PER_CALL = 5

Confidence = Literal["high", "medium", "low"]


class MappedComponent(BaseModel):
    rate_card_code: str = Field(description="A code copied from the candidate list.")
    type: ComponentType
    quantity_per_unit: str = Field(
        description=(
            "Amount of this component per ONE unit of the bid line, as a plain "
            "decimal number in the component's own unit, e.g. '2.5'."
        )
    )
    confidence: Confidence
    rationale: str = Field(
        description="One line: why this code fits and what quantity_per_unit assumes."
    )


class LineMapping(BaseModel):
    line_id: str
    components: list[MappedComponent]
    no_match_reason: str | None = Field(
        description="Why no (or not every) component could be mapped, else null."
    )


class LineMappings(BaseModel):
    lines: list[LineMapping]


class Candidate(NamedTuple):
    type: ComponentType
    code: str
    name: str
    unit: str  # the unit quantity_per_unit is measured in


_PROMPT = """You are helping an estimator at {company} ({trade}) price a bid schedule.
For each bid line below, choose the rate card entries (components) needed to do the work, and how much of each is needed per ONE unit of the bid line.

Rules:
- Only use codes from the candidate list below, copied exactly, with the type shown there. Never invent a code.
- If no candidate fits a line, return no components for it and explain why in no_match_reason. If only part of the work can be mapped, return the components that fit and describe what is missing in no_match_reason. Do not pick a poor match just to fill a line.
- Bid lines are installed work unless they say otherwise ("supply only", "material only"): include the labor to install each item as well as its material, and equipment where the work needs it.
- quantity_per_unit is per ONE unit of the bid line, in the candidate's own unit (labor in hours). Do not multiply by the line quantity; all totals are calculated later by the pricing engine.
- Production rates such as labor hours per unit or equipment days per unit are your assumptions, not facts from the document. State each assumption in the rationale.
- confidence: "high" when the code is a clear match and the quantity is not in doubt, "medium" when it rests on a typical production rate, "low" when the match or quantity is a guess.
- Return exactly one entry per bid line, using its line_id.

Candidate rate card entries (type | code | description | unit):
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
        candidates = candidates_for(batch, rate_card)
        prompt = build_mapping_prompt(batch, candidates, rate_card)
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


def build_mapping_prompt(
    lines: list[BidLineItem], candidates: list[Candidate], rate_card: RateCard
) -> str:
    return _PROMPT.format(
        company=rate_card.company_name,
        trade=rate_card.trade,
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

    Flags added here:

        * UNKNOWN_RATE_CODE (blocker): the code is not in the rate card under
          the stated type; the component is dropped.
        * INVALID_QUANTITY_PER_UNIT (blocker): not a non-negative number; the
          component is dropped.
        * LOW_CONFIDENCE_MAPPING (warning): the LLM was unsure of a component.
        * NO_RATE_CARD_MATCH (warning): the LLM's reason for mapping nothing,
          or only part of the work.
        * MAPPING_MISSING (blocker): the LLM returned nothing for the line.

    Every component that is kept adds one entry to the line's `assumptions`.
    """
    known = {(c.type, c.code): c for c in all_candidates(rate_card)}
    by_line_id: dict[str, LineMapping] = {}
    for mapping in mappings:
        by_line_id.setdefault(mapping.line_id.strip(), mapping)

    result: list[BidLineItem] = []
    for line in lines:
        flags = list(line.flags)
        components: list[LineItemComponent] = []
        assumptions = list(line.assumptions)

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
            for proposed in mapping.components:
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
                assumptions.append(
                    f"{proposed.type.capitalize()} {code} ({candidate.name}): "
                    f"{_number(quantity_per_unit)} {candidate.unit} per {line.unit} "
                    f"[{proposed.confidence} confidence] {proposed.rationale.strip()}"
                )
                if proposed.confidence == "low":
                    flags.append(
                        Flag(
                            severity="warning",
                            code="LOW_CONFIDENCE_MAPPING",
                            message=(
                                f"Low confidence in {proposed.type} {code} at "
                                f"{_number(quantity_per_unit)} {candidate.unit} per "
                                f"{line.unit}: {proposed.rationale.strip()}"
                            ),
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
                }
            )
        )
    return result


def _number(value: Decimal) -> str:
    return f"{value.normalize():,f}"
