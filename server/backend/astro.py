"""Vedic (sidereal, Lahiri) chart, Vimshottari dasha and daily transits via Swiss Ephemeris."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import swisseph as swe

swe.set_sid_mode(swe.SIDM_LAHIRI)
FLAGS = swe.FLG_MOSEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra",
         "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
NAKSHATRAS = ["Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu",
              "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta",
              "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha",
              "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada",
              "Uttara Bhadrapada", "Revati"]
PLANETS = [("Sun", swe.SUN), ("Moon", swe.MOON), ("Mars", swe.MARS), ("Mercury", swe.MERCURY),
           ("Jupiter", swe.JUPITER), ("Venus", swe.VENUS), ("Saturn", swe.SATURN),
           ("Rahu", swe.MEAN_NODE)]
DASHA_ORDER = [("Ketu", 7), ("Venus", 20), ("Sun", 6), ("Moon", 10), ("Mars", 7),
               ("Rahu", 18), ("Jupiter", 16), ("Saturn", 19), ("Mercury", 17)]
YEAR_DAYS = 365.2425
NAK_SPAN = 360 / 27


def _jd(dt_utc: datetime) -> float:
    h = dt_utc.hour + dt_utc.minute / 60 + dt_utc.second / 3600
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, h)


def _sign(lon: float) -> dict:
    lon %= 360
    return {"sign": SIGNS[int(lon // 30)], "degree": round(lon % 30, 2),
            "nakshatra": NAKSHATRAS[int(lon // NAK_SPAN)], "longitude": round(lon, 3)}


def positions(dt_utc: datetime) -> dict:
    jd = _jd(dt_utc)
    out = {}
    for name, pid in PLANETS:
        xx, _ = swe.calc_ut(jd, pid, FLAGS)
        out[name] = {**_sign(xx[0]), "retrograde": xx[3] < 0 and name not in ("Rahu",)}
    k = (out["Rahu"]["longitude"] + 180) % 360
    out["Ketu"] = {**_sign(k), "retrograde": False}
    return out


def lagna(dt_utc: datetime, lat: float, lon: float) -> dict:
    _, ascmc = swe.houses_ex(_jd(dt_utc), lat, lon, b"W", swe.FLG_SIDEREAL)
    return _sign(ascmc[0])


def vimshottari(moon_lon: float, birth_utc: datetime, at: datetime) -> dict:
    idx = int((moon_lon % 360) // NAK_SPAN)
    frac = ((moon_lon % 360) % NAK_SPAN) / NAK_SPAN
    start_i = idx % 9
    lord, yrs = DASHA_ORDER[start_i]
    # Mahadasha that was running at birth began before birth
    md_start = birth_utc - timedelta(days=frac * yrs * YEAR_DAYS)
    timeline = []
    i = start_i
    t = md_start
    while t < at + timedelta(days=40 * YEAR_DAYS):
        l, y = DASHA_ORDER[i % 9]
        end = t + timedelta(days=y * YEAR_DAYS)
        timeline.append({"lord": l, "start": t, "end": end, "years": y})
        t = end
        i += 1
    cur = next(p for p in timeline if p["start"] <= at < p["end"])
    # Antardasha
    ci = [d[0] for d in DASHA_ORDER].index(cur["lord"])
    t = cur["start"]
    ad = None
    for k in range(9):
        l, y = DASHA_ORDER[(ci + k) % 9]
        end = t + timedelta(days=cur["years"] * y / 120 * YEAR_DAYS)
        if t <= at < end:
            ad = {"lord": l, "start": t.date().isoformat(), "end": end.date().isoformat()}
            break
        t = end
    fmt = lambda p: {"lord": p["lord"], "start": p["start"].date().isoformat(),
                     "end": p["end"].date().isoformat(), "years": p["years"]}
    nxt = timeline[timeline.index(cur) + 1]
    return {"mahadasha": fmt(cur), "antardasha": ad, "next_mahadasha": fmt(nxt),
            "birth_nakshatra": NAKSHATRAS[idx]}


def whole_sign_house(planet_sign: str, lagna_sign: str) -> int:
    return (SIGNS.index(planet_sign) - SIGNS.index(lagna_sign)) % 12 + 1


def build_chart(dob: str, time: str | None, lat: float, lon: float, tz: str) -> dict:
    time_known = bool(time)
    hh, mm = (int(x) for x in (time or "12:00").split(":")[:2])
    y, m, d = (int(x) for x in dob.split("-"))
    local = datetime(y, m, d, hh, mm, tzinfo=ZoneInfo(tz))
    birth_utc = local.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)

    natal = positions(birth_utc)
    asc = lagna(birth_utc, lat, lon) if time_known else None
    if asc:
        for p in natal.values():
            p["house"] = whole_sign_house(p["sign"], asc["sign"])
    transits = positions(now)
    moon_sign_natal = natal["Moon"]["sign"]
    for p in transits.values():
        p["house_from_moon"] = whole_sign_house(p["sign"], moon_sign_natal)
        if asc:
            p["house_from_lagna"] = whole_sign_house(p["sign"], asc["sign"])

    return {
        "time_known": time_known,
        "lagna": asc,
        "natal": natal,
        "dasha": vimshottari(natal["Moon"]["longitude"], birth_utc, now),
        "transits": transits,
        "moon_today": transits["Moon"],
        "generated_at": now.isoformat(),
        "notes": ([] if time_known else
                  ["Birth time not given: lagna and houses are omitted, and Moon position "
                   "(so dasha dates) may be off by up to a few months."]),
    }
