"""Server-side numerology, matching frontend/app.js so reports and the app always agree."""
from __future__ import annotations
from datetime import date

PYTH = {ch: (i % 9) + 1 for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
CHALD = dict(A=1, B=2, C=3, D=4, E=5, F=8, G=3, H=5, I=1, J=1, K=2, L=3, M=4, N=5, O=7, P=8,
             Q=1, R=2, S=3, T=4, U=6, V=6, W=6, X=5, Y=1, Z=7)
VOWELS = set("AEIOU")
MASTER = {11, 22, 33}

MEANING = {
    1: ("Initiation", "Start things, lead, act independently."),
    2: ("Cooperation", "Partnership, listening, patient diplomacy."),
    3: ("Expression", "Create, communicate, connect socially."),
    4: ("Foundation", "Structure, discipline, finish practical work."),
    5: ("Change", "Adapt, explore, try something new."),
    6: ("Harmony", "Family, care, responsibility, beauty."),
    7: ("Introspection", "Research, reflection, spiritual work."),
    8: ("Achievement", "Money, authority, decisive execution."),
    9: ("Completion", "Release, finish, give back."),
    11: ("Illumination", "Intuition and inspiration (master number)."),
    22: ("Master building", "Large practical vision (master number)."),
    33: ("Master teaching", "Service and healing (master number)."),
}
COLOUR = {1: "Gold", 2: "Cream", 3: "Yellow", 4: "Grey-blue", 5: "Green", 6: "Rose",
          7: "Violet", 8: "Navy", 9: "Red"}


def _digits(n: int) -> int:
    return sum(int(d) for d in str(n))


def reduce(n: int) -> int:
    while n > 9 and n not in MASTER:
        n = _digits(n)
    return n


def reduce_full(n: int) -> int:
    while n > 9:
        n = _digits(n)
    return n


def _sum_name(name: str, table: dict, part: str = "all") -> int:
    total = 0
    for ch in name.upper():
        if ch not in table:
            continue
        if part == "v" and ch not in VOWELS:
            continue
        if part == "c" and ch in VOWELS:
            continue
        total += table[ch]
    return total


def calc(name: str, dob: str, system: str = "pyth", when: date | None = None) -> dict:
    when = when or date.today()
    table = PYTH if system == "pyth" else CHALD
    y, m, d = (int(x) for x in dob.split("-"))
    py = reduce_full(reduce_full(m) + reduce_full(d) + reduce_full(when.year))
    pm = reduce_full(py + when.month)
    pd = reduce_full(pm + when.day)
    return {
        "lifePath": reduce(reduce(m) + reduce(d) + reduce(y)),
        "birthNumber": reduce_full(d),
        "expression": reduce(_sum_name(name, table)),
        "expressionCompound": _sum_name(name, table),
        "soulUrge": reduce(_sum_name(name, table, "v")),
        "personality": reduce(_sum_name(name, table, "c")),
        "personalYear": py, "personalMonth": pm, "personalDay": pd,
    }


def both(name: str, dob: str, when: date | None = None) -> dict:
    return {"pythagorean": calc(name, dob, "pyth", when), "chaldean": calc(name, dob, "chal", when)}
