"""HALIA engine: question bank, next-question selection and the alignment engine.

Pure functions, no database and no network, so every rule here is unit-tested directly.

What an alignment score means: how closely two profiles match on what both sides DECLARED.
It is not a prediction of how a relationship, partnership or job will turn out, and no birth-date,
numerology or astrology input is used. A score is only returned when enough of the domain has been
answered by both sides (the gate below); otherwise the engine says which answers are missing.

A domain (couple, co-founder, candidate-to-job, ...) is configuration: areas, items, weights and
the comparison used for each item. Adding a domain means adding an entry to DOMAINS.
"""
from __future__ import annotations
from datetime import date, timedelta

# ── Question bank ────────────────────────────────────────────────────────────────────────────────
# kind:  "choice" one code | "scale" 1..5 | "multi" several codes
# level: a current-level measure of a pillar, re-asked every 30 days (the strongest predictor in the
#        26 Nov 2026 replication was the current level of the outcome itself)
# sensitive: never asked unprompted on WhatsApp; only shown in the app where the person chose the topic
SCALE5 = [("1", "Very low"), ("2", "Low"), ("3", "OK"), ("4", "Good"), ("5", "Very good")]


def _q(field, pillar, text, options, kind="choice", ttl=180, level=False, sensitive=False):
    return {"id": f"Q_{field}_V1", "field": field, "pillar": pillar, "text": text, "kind": kind,
            "options": [{"code": c, "label": l} for c, l in options], "ttl_days": ttl,
            "level": level, "sensitive": sensitive}


_BANK = [
    # current level of each pillar (monthly)
    _q("L_CAREER", "career", "How satisfied are you with your work or studies right now?", SCALE5, "scale", 30, True),
    _q("L_RELATIONSHIPS", "relationships", "How satisfied are you with your closest relationships right now?", SCALE5, "scale", 30, True),
    _q("L_MONEY", "money", "How in control of your money do you feel right now?", SCALE5, "scale", 30, True),
    _q("L_HAPPINESS", "happiness", "Overall, how satisfied are you with life these days?", SCALE5, "scale", 30, True),
    _q("L_WELLBEING", "health", "How would you rate your energy this week?", SCALE5, "scale", 30, True),
    # context
    _q("FOCUS_PILLAR", "context", "What would you most like to improve right now?",
       [("career", "Career"), ("relationships", "Relationships"), ("money", "Money"), ("happiness", "Happiness"), ("health", "Health")], ttl=30),
    _q("OCCUPATION", "context", "What best describes your day?",
       [("employee", "Working for a company"), ("business", "Running a business"), ("student", "Studying"),
        ("freelance", "Freelancing"), ("seeking", "Looking for work"), ("homemaker", "Managing a home"), ("retired", "Retired")]),
    _q("TIME_AVAILABLE", "context", "How much time could you realistically spare each day?",
       [("5", "5 minutes"), ("15", "15 minutes"), ("30", "30 minutes"), ("60", "An hour or more")], ttl=30),
    # career and work
    _q("CAREER_GOAL", "career", "What matters most in your career this year?",
       [("skill", "Learning a skill"), ("job", "Getting a job"), ("growth", "Growing in my role"),
        ("business", "Building a business"), ("stability", "Stability")], ttl=90),
    _q("WORK_STYLE", "career", "How do you work best?", [("solo", "On my own"), ("mixed", "A mix"), ("team", "In a team")]),
    _q("WORK_PACE", "career", "What pace of work suits you?", [("steady", "Steady"), ("varies", "It varies"), ("fast", "Fast")]),
    _q("EXPERIENCE", "career", "How many years of work experience do you have?",
       [("0", "Under 1"), ("1", "1 to 3"), ("3", "3 to 6"), ("6", "More than 6")], ttl=365),
    _q("LOCATION_MODE", "career", "Where do you prefer to work?", [("onsite", "On site"), ("hybrid", "Hybrid"), ("remote", "Remote")]),
    _q("SKILLS", "career", "Which of these can you already do at work?",
       [("python", "Python"), ("data_engineering", "Data engineering"), ("data_analytics", "Data analytics"), ("devops", "DevOps"),
        ("agentic_ai", "Agentic AI"), ("cyber_security", "Cyber security"), ("servicenow", "ServiceNow")], kind="multi", ttl=90),
    _q("COMMITMENT", "career", "How much of your time can you give a new venture?",
       [("part", "Part time"), ("full", "Full time"), ("all_in", "All in")]),
    _q("ROLE_PREF", "career", "In a venture, which role is most you?",
       [("build", "Building the product"), ("sell", "Selling"), ("operate", "Running operations"), ("lead", "Leading and raising money")]),
    # money
    _q("RISK", "money", "How much risk are you comfortable taking for a bigger reward?", [("low", "Low"), ("medium", "Medium"), ("high", "High")]),
    _q("MONEY_STYLE", "money", "With money, are you more of a saver or a spender?",
       [("saver", "Saver"), ("balanced", "Balanced"), ("spender", "Spender")]),
    # relationships and home
    _q("SOCIAL", "relationships", "How do you like to spend free time?", [("home", "At home"), ("balanced", "A mix"), ("out", "Out with people")]),
    _q("SCHEDULE", "relationships", "Are you a morning or a night person?", [("early", "Morning"), ("flexible", "Either"), ("late", "Night")]),
    _q("CONFLICT", "relationships", "When there's a disagreement, what do you usually do?",
       [("talk", "Talk it through at once"), ("cool_off", "Cool off first, then talk"), ("avoid", "Let it pass")]),
    _q("CARE_PREF", "relationships", "What makes you feel most cared for?",
       [("talk", "A good conversation"), ("time", "Time together"), ("help", "Practical help"), ("space", "Being given space")]),
    _q("AMBITION", "relationships", "Right now, what comes first for you?",
       [("career", "Career"), ("balanced", "A balance"), ("family", "Family")]),
    _q("LIVING", "relationships", "Where do you want to live in the long run?",
       [("metro", "A big city"), ("flexible", "Flexible"), ("small", "A smaller city or town"), ("abroad", "Abroad")]),
    _q("DIET", "relationships", "What do you eat?",
       [("veg", "Vegetarian"), ("egg", "Vegetarian plus eggs"), ("nonveg", "Non-vegetarian"), ("vegan", "Vegan"), ("flexible", "Flexible")]),
    _q("FAMILY_SETUP", "relationships", "After marriage, which home set-up do you prefer?",
       [("joint", "Joint family"), ("flexible", "Flexible"), ("nuclear", "Nuclear family")], sensitive=True),
    _q("FAMILY_PLAN", "relationships", "How do you feel about having children?",
       [("want", "I want children"), ("open", "Open either way"), ("no", "I don't want children"), ("have", "I already have children")], sensitive=True),
    _q("MARRIAGE_TIMELINE", "relationships", "When would you like to marry?",
       [("1", "Within a year"), ("3", "In 1 to 3 years"), ("later", "Later"), ("unsure", "Not sure")], sensitive=True),
    _q("TRADITION", "relationships", "How important are faith and tradition in your daily life?",
       [("low", "Not very"), ("medium", "Somewhat"), ("high", "Very")], sensitive=True),
]
QUESTIONS = {q["id"]: q for q in _BANK}
BY_FIELD = {q["field"]: q for q in _BANK}
SKIP_COOLDOWN_DAYS = 7
MAX_UNPROMPTED_PER_DAY = 1      # WhatsApp sends at most one question a day


def clean_value(q: dict, value):
    """Return the stored form of an answer, or raise ValueError. Only codes from the bank are stored."""
    codes = [o["code"] for o in q["options"]]
    if q["kind"] == "multi":
        vals = value if isinstance(value, list) else [value]
        vals = [str(v) for v in vals]
        if not vals or any(v not in codes for v in vals):
            raise ValueError("Choose from the listed options.")
        return sorted(set(vals), key=codes.index)
    v = str(value)
    if v not in codes:
        raise ValueError("Choose one of the listed options.")
    return v


def match_reply(q: dict, text: str):
    """Read a WhatsApp reply to a question: a number ("2"), numbers for multi ("1,3"), or the option label."""
    t = (text or "").strip().lower()
    opts = q["options"]
    parts = [p for p in t.replace("and", ",").replace(" ", ",").split(",") if p]
    if parts and all(p.isdigit() and 1 <= int(p) <= len(opts) for p in parts):
        picks = [opts[int(p) - 1]["code"] for p in parts]
        if q["kind"] == "multi":
            return sorted(set(picks), key=[o["code"] for o in opts].index)
        return picks[0] if len(picks) == 1 else None
    for o in opts:
        if t == o["label"].lower() or t == o["code"].lower():
            return [o["code"]] if q["kind"] == "multi" else o["code"]
    return None


def is_fresh(q: dict, observed_day: str, today: date) -> bool:
    return date.fromisoformat(observed_day) + timedelta(days=q["ttl_days"]) > today


def next_question(facts: dict, log: list[dict], today: date, *, domain: str | None = None,
                  unprompted: bool = False) -> dict | None:
    """Pick the one most useful question to ask now, or None.

    facts: {field: {"value":..., "day": "YYYY-MM-DD"}}; log: [{"question_id", "status", "day"}] newest first.
    Order: questions the chosen domain still needs, then the level of the focus pillar, then other levels,
    then context. Skipped questions rest for a week. Unprompted (WhatsApp) asks never include sensitive
    questions and stop after MAX_UNPROMPTED_PER_DAY.
    """
    if unprompted and sum(1 for e in log if e["day"] == today.isoformat() and e["status"] in ("asked", "answered")) >= MAX_UNPROMPTED_PER_DAY:
        return None
    resting = {e["question_id"] for e in log if e["status"] == "skipped"
               and date.fromisoformat(e["day"]) + timedelta(days=SKIP_COOLDOWN_DAYS) > today}
    asked_today = {e["question_id"] for e in log if e["day"] == today.isoformat()}
    focus = (facts.get("FOCUS_PILLAR") or {}).get("value")
    wanted = set(domain_fields(domain)) if domain else set()

    def rank(q):
        if q["field"] in wanted:
            return 0
        if q["field"] in ("FOCUS_PILLAR", "OCCUPATION", "TIME_AVAILABLE"):
            return 1
        if q["level"] and q["pillar"] == focus:
            return 2
        if q["level"]:
            return 3
        return 4

    best = None
    for i, q in enumerate(_BANK):
        f = facts.get(q["field"])
        if f and is_fresh(q, f["day"], today):
            continue
        if q["id"] in resting or (unprompted and (q["sensitive"] or q["id"] in asked_today)):
            continue
        if q["sensitive"] and q["field"] not in wanted:
            continue                                  # sensitive questions only when the person opened that domain
        key = (rank(q), i)
        if best is None or key < best[0]:
            best = (key, q)
    return best[1] if best else None


# ── Alignment engine ─────────────────────────────────────────────────────────────────────────────
# item modes:
#   same        equal codes = 1, different = 0; codes in "wild" match anything (flexible, open, ...)
#   ordinal     1 - distance / (steps - 1) along the option order
#   complement  different codes = 1 (two co-founders who both want the same role overlap rather than fit)
#   atleast     a's level is at or above b's requirement (ordinal): 1, otherwise falls off with the gap
#   overlap     share of b's listed codes that a also has (b = requirement)
DOMAINS = {
    "couple": {
        "name": "Couple", "symmetric": True, "min_items": 6, "min_coverage": 0.6,
        "areas": [
            {"id": "life_goals", "name": "Life goals", "items": [
                {"field": "FAMILY_PLAN", "mode": "same", "weight": 3, "wild": ["open"]},
                {"field": "MARRIAGE_TIMELINE", "mode": "same", "weight": 2, "wild": ["unsure"]},
                {"field": "AMBITION", "mode": "ordinal", "weight": 2},
                {"field": "LIVING", "mode": "same", "weight": 2, "wild": ["flexible"]}]},
            {"id": "home_values", "name": "Home and values", "items": [
                {"field": "FAMILY_SETUP", "mode": "same", "weight": 2, "wild": ["flexible"]},
                {"field": "TRADITION", "mode": "ordinal", "weight": 2},
                {"field": "DIET", "mode": "same", "weight": 1, "wild": ["flexible"]}]},
            {"id": "money", "name": "Money", "items": [
                {"field": "MONEY_STYLE", "mode": "ordinal", "weight": 2},
                {"field": "RISK", "mode": "ordinal", "weight": 1}]},
            {"id": "day_to_day", "name": "Day to day", "items": [
                {"field": "SOCIAL", "mode": "ordinal", "weight": 1},
                {"field": "SCHEDULE", "mode": "same", "weight": 1, "wild": ["flexible"]},
                {"field": "CARE_PREF", "mode": "same", "weight": 1}]},
            {"id": "communication", "name": "Handling disagreement", "items": [
                {"field": "CONFLICT", "mode": "same", "weight": 2}]},
        ]},
    "cofounder": {
        "name": "Co-founders", "symmetric": True, "min_items": 4, "min_coverage": 0.6,
        "areas": [
            {"id": "commitment", "name": "Commitment and risk", "items": [
                {"field": "COMMITMENT", "mode": "ordinal", "weight": 3},
                {"field": "RISK", "mode": "ordinal", "weight": 2}]},
            {"id": "roles", "name": "Roles", "items": [
                {"field": "ROLE_PREF", "mode": "complement", "weight": 3}]},
            {"id": "working_style", "name": "Working style", "items": [
                {"field": "WORK_PACE", "mode": "ordinal", "weight": 2},
                {"field": "WORK_STYLE", "mode": "same", "weight": 1, "wild": ["mixed"]},
                {"field": "CONFLICT", "mode": "same", "weight": 2}]},
        ]},
    "job": {   # a = the candidate, b = the job's requirements
        "name": "Candidate and job", "symmetric": False, "min_items": 2, "min_coverage": 0.6,
        "areas": [
            {"id": "skills", "name": "Skills", "items": [{"field": "SKILLS", "mode": "overlap", "weight": 4}]},
            {"id": "experience", "name": "Experience", "items": [{"field": "EXPERIENCE", "mode": "atleast", "weight": 2}]},
            {"id": "working_style", "name": "Working style", "items": [
                {"field": "WORK_STYLE", "mode": "same", "weight": 1, "wild": ["mixed"]},
                {"field": "WORK_PACE", "mode": "ordinal", "weight": 1},
                {"field": "LOCATION_MODE", "mode": "same", "weight": 2, "wild": ["hybrid"]}]},
        ]},
}
NOTE = ("This shows how closely your answers match on what you each said matters. "
        "It is not a prediction of how things will turn out.")


def domain_fields(domain: str) -> list[str]:
    return [it["field"] for a in DOMAINS[domain]["areas"] for it in a["items"]]


def _label(field: str, value) -> str:
    opts = {o["code"]: o["label"] for o in BY_FIELD[field]["options"]}
    if isinstance(value, list):
        return ", ".join(opts.get(v, v) for v in value)
    return opts.get(value, str(value))


def _item_score(item: dict, a, b) -> float:
    codes = [o["code"] for o in BY_FIELD[item["field"]]["options"]]
    mode = item["mode"]
    if mode == "overlap":
        need = set(b if isinstance(b, list) else [b])
        have = set(a if isinstance(a, list) else [a])
        return len(need & have) / len(need) if need else 1.0
    if mode == "same":
        wild = item.get("wild", [])
        return 1.0 if a == b or a in wild or b in wild else 0.0
    if mode == "complement":
        return 0.0 if a == b else 1.0
    ia, ib, span = codes.index(a), codes.index(b), max(len(codes) - 1, 1)
    if mode == "atleast":
        return 1.0 if ia >= ib else max(0.0, 1 - (ib - ia) / span)
    return 1 - abs(ia - ib) / span          # ordinal


def align(domain: str, a: dict, b: dict) -> dict:
    """Compare two sets of answers ({field: value}) for one domain.

    Returns per-area scores (0–100), an overall score weighted by item weight, and the items where the two
    differ most. Below the domain's gate it returns enough=False and the fields each side still needs.
    """
    cfg = DOMAINS[domain]
    areas, total_w, got_w, sum_w, n_items, diffs = [], 0.0, 0.0, 0.0, 0, []
    for area in cfg["areas"]:
        aw = asum = 0.0
        for it in area["items"]:
            total_w += it["weight"]
            va, vb = a.get(it["field"]), b.get(it["field"])
            if va is None or vb is None:
                continue
            s = _item_score(it, va, vb)
            aw += it["weight"]; asum += it["weight"] * s; n_items += 1
            if s < 0.67:
                diffs.append({"field": it["field"], "question": BY_FIELD[it["field"]]["text"], "area": area["name"],
                              "a": _label(it["field"], va), "b": _label(it["field"], vb),
                              "gap": round((1 - s) * it["weight"], 2)})
        got_w += aw; sum_w += asum
        areas.append({"id": area["id"], "name": area["name"],
                      "score": round(100 * asum / aw) if aw else None,
                      "answered": sum(1 for it in area["items"] if a.get(it["field"]) is not None and b.get(it["field"]) is not None),
                      "of": len(area["items"])})
    coverage = got_w / total_w if total_w else 0.0
    enough = n_items >= cfg["min_items"] and coverage >= cfg["min_coverage"]
    fields = domain_fields(domain)
    out = {"domain": domain, "name": cfg["name"], "enough": enough, "coverage": round(coverage, 2),
           "missing_a": [f for f in fields if a.get(f) is None],
           "missing_b": [f for f in fields if b.get(f) is None], "note": NOTE}
    if enough:
        diffs.sort(key=lambda d: -d["gap"])
        out.update(score=round(100 * sum_w / got_w), areas=areas,
                   talk_about=[{k: d[k] for k in ("area", "question", "a", "b")} for d in diffs[:5]])
    return out


def coverage(domain: str, facts: dict) -> dict:
    fields = domain_fields(domain)
    have = [f for f in fields if f in facts]
    return {"domain": domain, "name": DOMAINS[domain]["name"], "answered": len(have), "of": len(fields)}
