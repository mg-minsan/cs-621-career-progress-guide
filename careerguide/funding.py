"""Funding calculator: coded rules, exact to the cent (Decimal, never float).

ASSUMPTIONS -- hand-verify against the SkillsFuture rule pages before the E3 eval:
  * Fee subsidy (SSG-funded courses only): citizen 40+ 90%, citizen <40 70%, PR 70%.
  * SkillsFuture Credit $500: citizens 25+. Mid-Career Credit top-up $4,000: citizens 40+.
    Credits apply to the fee left after subsidy; SkillsFuture Credit is used before the top-up.
  * PRs get no credits. Non-subsidised (self-funded) courses get no subsidy.
  * Jobseeker Support ($6,000 over 6 months, retrenched citizens/PRs) and the Mid-Career Training
    Allowance (up to $3,000/month, citizens 40+, up to 24 months, full-time courses) are income
    support: reported as eligibility notes, never deducted from course fees.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
SFC_AMOUNT = Decimal("500")
MCC_AMOUNT = Decimal("4000")


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def subsidy_rate(age: int, residency: str) -> Decimal:
    if residency == "citizen":
        return Decimal("0.90") if age >= 40 else Decimal("0.70")
    if residency == "pr":
        return Decimal("0.70")
    return Decimal("0")


def credit_balances(age: int, residency: str) -> dict[str, Decimal]:
    if residency != "citizen":
        return {"SkillsFuture Credit": Decimal("0"), "Mid-Career Credit": Decimal("0")}
    return {"SkillsFuture Credit": SFC_AMOUNT if age >= 25 else Decimal("0"),
            "Mid-Career Credit": MCC_AMOUNT if age >= 40 else Decimal("0")}


def price_courses(courses: list[dict], profile: dict) -> dict:
    """courses: [{id, title, fee, subsidised}] in the order they will be taken (each counted once)."""
    age, res = int(profile["age"]), profile["residency"]
    rate = subsidy_rate(age, res)
    credits = credit_balances(age, res)
    lines, tot = [], {"full": Decimal("0"), "subsidy": Decimal("0"), "sfc": Decimal("0"),
                      "mcc": Decimal("0"), "pay": Decimal("0")}
    for c in courses:
        fee = money(c["fee"])
        subsidy = money(fee * rate) if c["subsidised"] else Decimal("0")
        after = fee - subsidy
        used = {}
        for scheme in ("SkillsFuture Credit", "Mid-Career Credit"):
            take = min(credits[scheme], after)
            credits[scheme] -= take
            after -= take
            used[scheme] = take
        lines.append({"id": c["id"], "title": c["title"], "full_fee": float(fee), "subsidy": float(subsidy),
                      "skillsfuture_credit": float(used["SkillsFuture Credit"]),
                      "mid_career_credit": float(used["Mid-Career Credit"]), "you_pay": float(after)})
        tot["full"] += fee
        tot["subsidy"] += subsidy
        tot["sfc"] += used["SkillsFuture Credit"]
        tot["mcc"] += used["Mid-Career Credit"]
        tot["pay"] += after

    notes = []
    if profile.get("status") == "retrenched" and res in ("citizen", "pr"):
        notes.append("Jobseeker Support: up to $6,000 over 6 months for retrenched citizens and PRs "
                     "(income support - not deducted from course fees).")
    if res == "citizen" and age >= 40:
        notes.append("Mid-Career Training Allowance: up to $3,000/month for up to 24 months on approved "
                     "full-time courses (check eligibility; not deducted from fees).")
    if any(not c["subsidised"] for c in courses):
        notes.append("Some courses are self-funded and get no subsidy.")
    return {
        "rate": float(rate),
        "lines": lines,
        "full_fee": float(tot["full"]),
        "subsidy": float(tot["subsidy"]),
        "skillsfuture_credit": float(tot["sfc"]),
        "mid_career_credit": float(tot["mcc"]),
        "you_pay": float(tot["pay"]),
        "credits_available": {k: float(v) for k, v in credit_balances(age, res).items()},
        "notes": notes,
    }
