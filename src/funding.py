"""
STEP 2 - Funding calculator. Plain code, no AI.

Design rule: the model never does money maths. This module is both
  (a) a TOOL the agent calls in Stage 5, and
  (b) the reference the E4 eval is checked against.

RULES (copied from official pages - re-check before submission)
Source 1: MySkillsFuture "SkillsFuture Funding for Individuals"
  https://www.myskillsfuture.gov.sg/content/portal/en/career-resources/career-resources/education-career-personal-development/SkillsFuture_Funding.html
  Tier 1 courses: Citizens, PRs (and LTVP+)       up to 70% of course fees
                  Citizens aged 40+ (MCES)         up to 90%
  Tier 2 courses (CASL skills / CEB-endorsed):
                  Citizens, PRs, self-sponsored 21+ up to 50%
                  Citizens aged 40+ (MCES)         up to 70%
Source 2: MOE press release, SkillsFuture Level-Up Programme (4 Mar 2024)
  https://www.moe.gov.sg/news/press-releases/20240304-new-skillsfuture-level-up-programme-to-boost-mid-career-upskilling-and-reskilling
  SkillsFuture Credit: $500 base tier at age 25; $4,000 Mid-Career top-up
  for Singaporeans 40+ from 1 May 2024.
RULES_CHECKED_ON = "2026-10-05"   <- update when your team re-verifies

DATA FINDING (Step 2): the course file does not say which tier a course is
in, but its listed after-subsidy fee does. Of 26,055 courses with a fee,
listed fee / full fee is 0.30 for 10,781 (= 70% subsidy, Tier 1),
0.50 for 8,307 (= 50%, Tier 2) and 1.00 for 6,903 (no subsidy).
So we infer the tier from that ratio. Under ~0.5% of courses fit no tier;
we mark those "unknown" and the agent must say so instead of guessing.

DELIBERATE SIMPLIFICATIONS (state them in the report):
  * "Up to" rates are treated as the exact rate. Real subsidies can be lower.
  * GST is not modelled.
  * Only the $500 base credit is applied automatically. The $4,000 Mid-Career
    credit is limited to selected courses, and the course file does not say
    which, so we flag it as "may apply - check" rather than subtract it.
    Overstating funding is the expensive mistake (cost table), so we stay
    conservative.
  * If the user's remaining credit balance is unknown, we do NOT assume it is
    unused; we return needs_user_input=True (an L3 "ask" point).
"""
from __future__ import annotations

from dataclasses import dataclass, field

RULES_CHECKED_ON = "2026-10-05"

# subsidy rate by course tier, for (base, citizen 40+)
TIER_RATES = {
    "tier1": {"base": 0.70, "mces": 0.90},
    "tier2": {"base": 0.50, "mces": 0.70},
    "none":  {"base": 0.00, "mces": 0.00},
}
BASE_CREDIT_AGE, BASE_CREDIT = 25, 500.00
MIDCAREER_CREDIT_AGE, MIDCAREER_CREDIT = 40, 4000.00
TIER2_MIN_SELF_SPONSORED_AGE = 21


class FundingError(Exception):
    """Bad input, raised loudly."""


@dataclass
class Person:
    residency: str                 # "citizen" | "pr" | "other"
    age: int
    credit_balance: float | None = None   # None = unknown -> must ask


@dataclass
class CostBreakdown:
    full_fee: float
    tier: str
    subsidy_rate: float
    subsidy: float
    fee_after_subsidy: float
    credit_used: float
    out_of_pocket: float
    schemes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    needs_user_input: bool = False


def infer_tier(full_fee: float, listed_after_subsidy: float | None) -> str:
    """Tier from the listed fees (see DATA FINDING above)."""
    if full_fee is None or full_fee <= 0 or listed_after_subsidy is None:
        return "unknown"
    ratio = round(listed_after_subsidy / full_fee, 2)
    return {0.30: "tier1", 0.50: "tier2", 1.00: "none"}.get(ratio, "unknown")


def subsidy_rate(person: Person, tier: str) -> tuple[float, list[str]]:
    if tier not in TIER_RATES:
        raise FundingError(f"Unknown tier '{tier}'. Valid: {list(TIER_RATES)} - "
                           "if the tier cannot be inferred, tell the user the cost is unknown.")
    res = person.residency.lower()
    if res not in {"citizen", "pr", "other"}:
        raise FundingError(f"residency must be citizen, pr or other, got '{person.residency}'")
    if res == "other" or tier == "none":
        return 0.0, []
    if tier == "tier2" and person.age < TIER2_MIN_SELF_SPONSORED_AGE:
        return 0.0, []
    if res == "citizen" and person.age >= MIDCAREER_CREDIT_AGE:
        return TIER_RATES[tier]["mces"], ["SkillsFuture Mid-Career Enhanced Subsidy"]
    return TIER_RATES[tier]["base"], ["SSG course fee subsidy"]


def course_cost(person: Person, full_fee: float, tier: str,
                use_credit: bool = True) -> CostBreakdown:
    """Out-of-pocket cost of one course for one person. Rounded to the cent."""
    if full_fee is None or full_fee < 0:
        raise FundingError(f"full_fee must be >= 0, got {full_fee}")
    if tier == "unknown":
        raise FundingError("Course tier unknown: the listed fees match no funding tier. "
                           "Show the full fee and tell the user to check the subsidy.")
    rate, schemes = subsidy_rate(person, tier)
    subsidy = round(full_fee * rate, 2)
    after = round(full_fee - subsidy, 2)

    notes, credit_used, needs_input = [], 0.0, False
    is_citizen = person.residency.lower() == "citizen"
    if use_credit and is_citizen and person.age >= BASE_CREDIT_AGE and after > 0:
        if person.credit_balance is None:
            needs_input = True
            notes.append("Credit balance unknown: ask the user before applying SkillsFuture Credit.")
        elif person.credit_balance > credit_entitlement(person):
            # Boundary (E5 b10): more credit than the person can ever have received.
            needs_input = True
            notes.append(f"Stated credit balance ${person.credit_balance:,.2f} exceeds the maximum "
                         f"${credit_entitlement(person):,.2f} for this age; ask the user to check it.")
        else:
            credit_used = round(min(person.credit_balance, after), 2)
            if credit_used > 0:
                schemes.append("SkillsFuture Credit")
    if is_citizen and person.age >= MIDCAREER_CREDIT_AGE:
        notes.append("SkillsFuture Credit (Mid-Career) may also apply to selected courses - check.")
    if person.residency.lower() == "pr":
        notes.append("PRs are not eligible for SkillsFuture Credit or the Mid-Career Enhanced Subsidy.")

    return CostBreakdown(full_fee=round(full_fee, 2), tier=tier, subsidy_rate=rate,
                         subsidy=subsidy, fee_after_subsidy=after, credit_used=credit_used,
                         out_of_pocket=round(after - credit_used, 2), schemes=schemes,
                         notes=notes, needs_user_input=needs_input)


def credit_entitlement(person: Person) -> float:
    """Total SkillsFuture Credit ever granted by age (not the remaining balance)."""
    if person.residency.lower() != "citizen":
        return 0.0
    total = BASE_CREDIT if person.age >= BASE_CREDIT_AGE else 0.0
    if person.age >= MIDCAREER_CREDIT_AGE:
        total += MIDCAREER_CREDIT
    return total


def plan_cost(person: Person, course_fees: list[float | None]) -> dict:
    """Total for a whole plan. Fees are per course AFTER subsidy, BEFORE credit.
    SkillsFuture Credit is applied ONCE here, across the plan - never per course,
    which would count the same $500 several times."""
    known = [f for f in course_fees if f is not None]
    unknown = len(course_fees) - len(known)
    total = round(sum(known), 2)
    res = person.residency.lower()
    credit, needs, notes = 0.0, False, []
    if res == "citizen" and person.age >= BASE_CREDIT_AGE and total > 0:
        if person.credit_balance is None:
            needs = True
            base = min(BASE_CREDIT, total)
            notes.append(f"SkillsFuture Credit not applied: your balance is unknown. If your ${BASE_CREDIT:,.0f} "
                         f"base credit is unused, you would pay ${total - base:,.2f}.")
        elif person.credit_balance > credit_entitlement(person):
            needs = True
            notes.append("Stated credit balance is higher than possible for this age; not applied.")
        else:
            credit = round(min(person.credit_balance, total), 2)
    if res == "citizen" and person.age >= MIDCAREER_CREDIT_AGE:
        notes.append("SkillsFuture Credit (Mid-Career) may also apply to selected courses - check.")
    if res == "pr":
        notes.append("PRs are not eligible for SkillsFuture Credit.")
    if unknown:
        notes.append(f"{unknown} course(s) have an unknown fee and are not in the total.")
    return {"total_after_subsidy": total, "credit_used": credit,
            "out_of_pocket": round(total - credit, 2), "unknown_cost_courses": unknown,
            "needs_user_input": needs, "notes": notes, "rules_checked_on": RULES_CHECKED_ON}
