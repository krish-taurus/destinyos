"""HALIA: engine rules, consent, answers, chat allowance and the ₹499 plan, QR, compare links, job fit, WhatsApp."""
import hashlib, hmac, json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from test_flows import CODES, fake_claude, fake_rzp, sign, signup, subscribe   # sets the test environment first
import auth, billing, db, halia, halia_daily, main
import halia_engine as eng

SENT = []


@pytest.fixture(autouse=True)
def patches(monkeypatch):
    monkeypatch.setattr(main, "ask_claude", fake_claude)
    monkeypatch.setattr(billing, "_rzp", fake_rzp)
    monkeypatch.setattr(billing, "PLAN_ID_CHAT", "plan_chat")
    monkeypatch.setattr(auth, "send_sms_otp", lambda phone, code: CODES.__setitem__(phone, code))
    monkeypatch.setattr(halia, "wa_send_text", lambda phone, text: SENT.append((phone, text)))
    monkeypatch.setattr(halia, "WA_APP_SECRET", "appsecret")
    monkeypatch.setattr(halia, "WA_VERIFY_TOKEN", "verify-me")
    main._hits.clear(); SENT.clear()


def client(phone, name="Asha Rao", consent=True, daily=False):
    c = TestClient(main.app)
    signup(c, phone, name)
    if consent:
        assert c.post("/api/halia/consent", json={"consent": True, "daily_optin": daily}).status_code == 200
    return c


def answer(c, field, value):
    r = c.post("/api/halia/answers", json={"question_id": eng.BY_FIELD[field]["id"], "value": value})
    assert r.status_code == 200, r.text


def wa(c, frm, text, mid):
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"from": frm, "id": mid, "type": "text", "text": {"body": text}}]}}]}]})
    sig = "sha256=" + hmac.new(b"appsecret", body.encode(), hashlib.sha256).hexdigest()
    return c.post("/api/whatsapp/webhook", content=body, headers={"x-hub-signature-256": sig, "content-type": "application/json"})


COUPLE = {"FAMILY_PLAN": "want", "MARRIAGE_TIMELINE": "3", "AMBITION": "balanced", "LIVING": "metro", "FAMILY_SETUP": "nuclear",
          "TRADITION": "medium", "DIET": "veg", "MONEY_STYLE": "saver", "RISK": "low", "SOCIAL": "home", "SCHEDULE": "early",
          "CARE_PREF": "time", "CONFLICT": "talk"}


# ── engine ──
def test_identical_answers_score_100_and_opposites_score_low():
    same = eng.align("couple", COUPLE, dict(COUPLE))
    assert same["enough"] and same["score"] == 100 and same["talk_about"] == []
    other = {**COUPLE, "FAMILY_PLAN": "no", "MONEY_STYLE": "spender", "CONFLICT": "avoid", "TRADITION": "low", "LIVING": "small"}
    rep = eng.align("couple", COUPLE, other)
    assert rep["score"] < 70
    assert rep["talk_about"][0]["question"] == eng.BY_FIELD["FAMILY_PLAN"]["text"]      # heaviest difference first
    assert "not a prediction" in rep["note"]


def test_no_score_until_enough_is_answered_by_both():
    rep = eng.align("couple", COUPLE, {"DIET": "veg", "RISK": "low"})
    assert rep["enough"] is False and "score" not in rep and "FAMILY_PLAN" in rep["missing_b"]


def test_flexible_answers_match_and_ordinal_is_graded():
    assert eng._item_score({"field": "LIVING", "mode": "same", "wild": ["flexible"]}, "flexible", "abroad") == 1
    assert eng._item_score({"field": "RISK", "mode": "ordinal"}, "low", "medium") == 0.5
    assert eng._item_score({"field": "ROLE_PREF", "mode": "complement"}, "build", "build") == 0


def test_job_fit_uses_skill_overlap_and_minimum_experience():
    me = {"SKILLS": ["python", "data_engineering"], "EXPERIENCE": "3", "WORK_STYLE": "team", "WORK_PACE": "fast", "LOCATION_MODE": "remote"}
    good = eng.align("job", me, {"SKILLS": ["python", "data_engineering"], "EXPERIENCE": "1", "LOCATION_MODE": "remote"})
    weak = eng.align("job", me, {"SKILLS": ["devops", "cyber_security"], "EXPERIENCE": "6", "LOCATION_MODE": "onsite"})
    assert good["score"] == 100 and weak["score"] < 30


def test_no_symbolic_input_exists_in_the_engine():
    text = json.dumps([eng.QUESTIONS, eng.DOMAINS]).lower()
    for word in ("birth", "zodiac", "moolank", "nakshatra", "numerolog", "horoscope"):
        assert word not in text


def test_next_question_rules():
    today = date(2026, 11, 26)
    q = eng.next_question({}, [], today)
    assert q["field"] == "FOCUS_PILLAR"
    facts = {"FOCUS_PILLAR": {"value": "money", "day": "2026-11-26"}, "OCCUPATION": {"value": "employee", "day": "2026-11-26"},
             "TIME_AVAILABLE": {"value": "15", "day": "2026-11-26"}}
    assert eng.next_question(facts, [], today)["field"] == "L_MONEY"                   # level of the focus pillar first
    skipped = [{"question_id": "Q_L_MONEY_V1", "status": "skipped", "day": "2026-11-24"}]
    assert eng.next_question(facts, skipped, today)["field"] != "L_MONEY"              # rests for a week
    stale = {**facts, "L_MONEY": {"value": "3", "day": "2026-10-01"}}
    assert eng.next_question(stale, [], today)["field"] == "L_MONEY"                   # re-measured monthly
    asked = [{"question_id": "Q_L_MONEY_V1", "status": "asked", "day": "2026-11-26"}]
    assert eng.next_question(facts, asked, today, unprompted=True) is None             # one WhatsApp question a day
    full = {q["field"]: {"value": q["options"][0]["code"], "day": "2026-11-26"} for q in eng.QUESTIONS.values() if not q["sensitive"]}
    assert eng.next_question(full, [], today, unprompted=True) is None                 # sensitive ones are never sent unprompted
    assert eng.next_question(full, [], today) is None                                  # nor in the app without choosing the domain
    assert eng.next_question(full, [], today, domain="couple")["sensitive"]


def test_reading_whatsapp_replies():
    q = eng.BY_FIELD["RISK"]
    assert eng.match_reply(q, "2") == "medium" and eng.match_reply(q, " High ") == "high"
    assert eng.match_reply(q, "7") is None and eng.match_reply(q, "what does this mean?") is None
    assert eng.match_reply(eng.BY_FIELD["SKILLS"], "1, 3") == ["python", "data_analytics"]


# ── consent and answers ──
def test_nothing_is_stored_without_consent_and_withdrawal_erases():
    c = client("8111000001", consent=False)
    assert c.get("/api/halia/state").json()["consented"] is False
    assert c.post("/api/halia/answers", json={"question_id": "Q_RISK_V1", "value": "low"}).status_code == 403
    assert c.post("/api/halia/chat", json={"text": "hi"}).status_code == 403
    assert c.post("/api/halia/consent", json={"consent": False}).status_code == 422
    assert c.post("/api/halia/consent", json={"consent": True}).status_code == 200
    answer(c, "RISK", "low")
    assert c.post("/api/halia/chat", json={"text": "hi"}).status_code == 200
    assert c.delete("/api/halia/consent").status_code == 200
    uid = db.one("SELECT id FROM users WHERE phone='+918111000001'")["id"]
    for t in ("halia_answers", "halia_chat", "halia_question_log", "halia_settings"):
        assert db.one(f"SELECT COUNT(*) n FROM {t} WHERE user_id=?", uid)["n"] == 0


def test_minors_cannot_turn_halia_on():
    c = TestClient(main.app)
    r = c.post("/api/auth/otp", json={"phone": "8111000002"}); p = r.json()["phone"]
    j = c.post("/api/auth/verify", json={"phone": "8111000002", "code": CODES[p]}).json()
    dob = (date.today() - timedelta(days=365 * 16)).isoformat()
    assert c.post("/api/auth/register", json={"signup_token": j["signup_token"], "name": "Young User", "dob": dob,
                                               "city": "Bengaluru", "consent": True}).status_code == 200
    assert c.post("/api/halia/consent", json={"consent": True}).status_code == 403


def test_answers_validate_update_and_delete():
    c = client("8111000003")
    assert c.post("/api/halia/answers", json={"question_id": "Q_RISK_V1", "value": "enormous"}).status_code == 422
    assert c.post("/api/halia/answers", json={"question_id": "Q_NOPE", "value": "x"}).status_code == 404
    answer(c, "RISK", "low"); answer(c, "RISK", "high"); answer(c, "SKILLS", ["python", "devops"])
    got = {a["field"]: a for a in c.get("/api/halia/state").json()["answers"]}
    assert got["RISK"]["value"] == "high" and got["RISK"]["label"] == "High" and got["SKILLS"]["value"] == ["python", "devops"]
    assert c.delete("/api/halia/answers/RISK").status_code == 200
    assert "RISK" not in {a["field"] for a in c.get("/api/halia/state").json()["answers"]}
    q = c.get("/api/halia/questions/next").json()["question"]
    assert c.post("/api/halia/answers", json={"question_id": q["id"], "skip": True}).json()["skipped"]
    assert c.get("/api/halia/questions/next").json()["question"]["id"] != q["id"]


def test_account_deletion_removes_halia_data():
    c = client("8111000004"); answer(c, "RISK", "low"); c.post("/api/halia/chat", json={"text": "hello"})
    uid = db.one("SELECT id FROM users WHERE phone='+918111000004'")["id"]
    assert c.delete("/api/me").status_code == 200
    for t in ("halia_answers", "halia_chat", "halia_settings"):
        assert db.one(f"SELECT COUNT(*) n FROM {t} WHERE user_id=?", uid)["n"] == 0


# ── chat allowance and the ₹499 plan ──
def test_free_taster_then_499_plan_gives_25_a_day(monkeypatch):
    c = client("8111000005")
    for _ in range(3):
        assert c.post("/api/halia/chat", json={"text": "How do I plan my week?"}).status_code == 200
    r = c.post("/api/halia/chat", json={"text": "one more"})
    assert r.status_code == 402 and "₹499" in r.json()["detail"]
    r = c.post("/api/billing/subscribe", json={"plan": "chat"}); assert r.status_code == 200 and "₹499" in r.json()["description"]
    sid = r.json()["subscription_id"]
    r = c.post("/api/billing/subscribe/verify", json={"razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid,
                                                      "razorpay_signature": sign(f"pay_1|{sid}", "ks")})
    st = r.json(); assert st["tier"] == "chat" and st["chat"] and not st["subscribed"]
    assert c.post("/api/brief", json={"meals": []}).status_code == 402            # HALIA Chat alone doesn't unlock Plus
    assert c.get("/api/halia/state").json()["chat"] == {"kind": "daily", "left": 25, "of": 25}
    for _ in range(25):
        assert c.post("/api/halia/chat", json={"text": "next"}).status_code == 200
    assert c.post("/api/halia/chat", json={"text": "26th"}).status_code == 429
    assert c.post("/api/billing/subscribe", json={"plan": "chat"}).status_code == 409


def test_plus_includes_halia_chat_and_upgrade_stops_the_499_plan():
    c = client("8111000006")
    r = c.post("/api/billing/subscribe", json={"plan": "chat"}); sid = r.json()["subscription_id"]
    c.post("/api/billing/subscribe/verify", json={"razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid,
                                                  "razorpay_signature": sign(f"pay_1|{sid}", "ks")})
    subscribe(c, "plus")
    assert c.get("/api/billing/status").json()["tier"] == "plus"
    assert db.one("SELECT cancel_requested FROM subscriptions WHERE provider_sub_id=?", sid)["cancel_requested"] == 1
    assert c.get("/api/halia/state").json()["chat"]["of"] == 25


def test_failed_reply_does_not_cost_a_chat(monkeypatch):
    c = client("8111000007")
    def boom(*a, **k): raise main.HTTPException(502, "down")
    monkeypatch.setattr(main, "ask_claude", boom)
    assert c.post("/api/halia/chat", json={"text": "hi"}).status_code == 502
    assert c.get("/api/halia/state").json()["chat"]["left"] == 3


def test_chat_saves_only_valid_stated_facts_and_hides_the_marker(monkeypatch):
    c = client("8111000008")
    monkeypatch.setattr(main, "ask_claude", lambda *a, **k: "Start with one task.\nFACTS: OCCUPATION=student; RISK=galactic; FAMILY_PLAN=want")
    r = c.post("/api/halia/chat", json={"text": "I'm a student and want to plan my day"}).json()
    assert r["reply"] == "Start with one task." and r["question"]
    got = {a["field"]: a["value"] for a in c.get("/api/halia/state").json()["answers"]}
    assert got == {"OCCUPATION": "student"}                                         # bad code and sensitive field ignored


def test_chat_prompt_carries_the_rules_and_no_birth_details(monkeypatch):
    c = client("8111000009"); seen = {}
    monkeypatch.setattr(main, "ask_claude", lambda system, msgs, **k: seen.update(system=system) or "ok")
    c.post("/api/halia/chat", json={"text": "Are we compatible?"})
    assert "Never say whether two people are compatible" in seen["system"] and "14416" in seen["system"]
    assert "1994" not in seen["system"] and "Life Path" not in seen["system"]


def test_qr_code_is_public_svg_of_the_chat_link(monkeypatch):
    c = TestClient(main.app)
    r = c.get("/api/halia/chat/qr")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg") and b"<svg" in r.content
    assert halia.chat_link() == "https://destinyos.in/halia/"
    monkeypatch.setattr(halia, "WA_NUMBER", "919812345678")
    assert halia.chat_link() == "https://wa.me/919812345678?text=Hi%20HALIA"


# ── compare ──
def test_invite_compare_and_unlink():
    a, b = client("8111000010", "Asha Rao"), client("8111000011", "Vikram Shah")
    url = a.post("/api/halia/invites", json={"domain": "couple"}).json()["url"]
    token = url.split("invite=")[1]
    assert a.post(f"/api/halia/invites/{token}/accept", json={"agree": True}).status_code == 409      # own invite
    assert b.get(f"/api/halia/invites/{token}").json()["from"] == "Asha"
    assert b.post(f"/api/halia/invites/{token}/accept", json={"agree": False}).status_code == 422
    lid = b.post(f"/api/halia/invites/{token}/accept", json={"agree": True}).json()["link_id"]
    assert b.post(f"/api/halia/invites/{token}/accept", json={"agree": True}).status_code == 404      # single use
    assert a.get(f"/api/halia/links/{lid}").json()["enough"] is False
    for f, v in COUPLE.items():
        answer(a, f, v); answer(b, f, "no" if f == "FAMILY_PLAN" else v)
    ra, rb = a.get(f"/api/halia/links/{lid}").json(), b.get(f"/api/halia/links/{lid}").json()
    assert ra["enough"] and ra["score"] == rb["score"] < 100 and ra["with"] == "Vikram" and rb["with"] == "Asha"
    assert ra["talk_about"][0]["you"] == "I want children" and rb["talk_about"][0]["you"] == "I don't want children"
    assert a.get("/api/halia/links").json()["links"][0]["score"] == ra["score"]
    outsider = client("8111000012", "Other Person")
    assert outsider.get(f"/api/halia/links/{lid}").status_code == 404
    assert b.delete("/api/halia/consent").status_code == 200                                          # withdrawing removes the link
    assert a.get("/api/halia/links").json()["links"] == []
    assert a.post("/api/halia/invites", json={"domain": "job"}).status_code == 404


def test_job_fit_endpoint():
    c = client("8111000013")
    answer(c, "SKILLS", ["python"]); answer(c, "EXPERIENCE", "1"); answer(c, "LOCATION_MODE", "remote")
    r = c.post("/api/halia/fit/job", json={"title": "Data Engineer", "requirements":
                                           {"SKILLS": ["python", "data_engineering"], "EXPERIENCE": "1", "LOCATION_MODE": "hybrid"}}).json()
    assert r["enough"] and r["title"] == "Data Engineer" and 50 < r["score"] < 100
    assert r["talk_about"][0]["job"] == "Python, Data engineering"
    assert c.post("/api/halia/fit/job", json={"requirements": {"EXPERIENCE": "forever"}}).status_code == 422


# ── WhatsApp ──
def test_webhook_verification_and_signature():
    c = TestClient(main.app)
    r = c.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"
    assert c.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "wrong"}).status_code == 403
    assert c.post("/api/whatsapp/webhook", content="{}", headers={"x-hub-signature-256": "sha256=bad"}).status_code == 400


def test_daily_question_goes_only_to_opted_in_people_and_reply_is_saved(monkeypatch, capsys):
    yes, no = client("8111000014", "Meera Iyer", daily=True), client("8111000015", "No Daily")
    out = []
    monkeypatch.setattr(halia_daily, "send", lambda phone, p: out.append((phone, p)))
    assert halia_daily.run(dry=False)["sent"] >= 1
    mine = [p for ph, p in out if ph == "+918111000014"]
    assert len(mine) == 1 and mine[0][0] == "Meera" and "improve right now" in mine[0][1] and "1) Career" in mine[0][2]
    assert not [1 for ph, _ in out if ph == "+918111000015"]
    out.clear(); halia_daily.run(dry=False)
    assert not [1 for ph, _ in out if ph == "+918111000014"]                         # one a day
    assert wa(yes, "918111000014", "3", "wamid.1").status_code == 200
    assert {a["field"]: a["value"] for a in yes.get("/api/halia/state").json()["answers"]} == {"FOCUS_PILLAR": "money"}
    assert "Noted: Money" in SENT[-1][1]
    n = len(SENT); wa(yes, "918111000014", "3", "wamid.1")                           # Meta re-delivery is ignored
    assert len(SENT) == n
    wa(yes, "918111000014", "STOP", "wamid.2")
    assert yes.get("/api/halia/state").json()["daily_optin"] is False


def test_whatsapp_chat_uses_the_same_allowance_and_gates(monkeypatch):
    c = client("8111000016")
    for i in range(3):
        wa(c, "918111000016", f"question {i}", f"wamid.c{i}")
    assert SENT[-1] == ("+918111000016", "Here is your answer.")
    wa(c, "918111000016", "a fourth", "wamid.c3")
    assert "₹499" in SENT[-1][1] and "/halia/" in SENT[-1][1]
    assert c.get("/api/halia/state").json()["chat"]["left"] == 0
    wa(c, "919999999999", "hello", "wamid.x1")
    assert "create your account" in SENT[-1][1]
    nc = client("8111000017", consent=False)
    wa(nc, "918111000017", "hello", "wamid.x2")
    uid = db.one("SELECT id FROM users WHERE phone='+918111000016'")["id"]
    assert "accept" in SENT[-1][1] and db.one("SELECT COUNT(*) n FROM halia_chat WHERE user_id=?", uid)["n"] == 6


def test_public_preview_returns_numbers_and_chart_and_stores_nothing():
    c = TestClient(main.app)
    before = db.one("SELECT COUNT(*) n FROM users")["n"], db.one("SELECT COUNT(*) n FROM events")["n"]
    r = c.post("/api/preview", json={"name": "Priya Sharma", "dob": "1994-08-17", "birth_time": "06:30", "city": "Bengaluru"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["numbers"]["pythagorean"]["lifePath"] == 3 and j["chart"]["lagna"] and len(j["chart"]["natal"]) == 9
    assert j["chart"]["natal"]["Moon"]["sign"] and j["chart"]["birth_nakshatra"]
    r = c.post("/api/preview", json={"name": "Priya Sharma", "dob": "1994-08-17"})
    assert r.json()["chart"]["lagna"] is None and r.json()["chart"]["notes"]
    assert c.post("/api/preview", json={"name": "Priya", "dob": "1994-02-31"}).status_code == 422
    assert before == (db.one("SELECT COUNT(*) n FROM users")["n"], db.one("SELECT COUNT(*) n FROM events")["n"])


def test_chart_uses_lahiri_in_api_worker_threads_too():
    """Swiss Ephemeris keeps the sidereal mode per thread; requests run in worker threads."""
    import threading, astro
    from datetime import datetime, timezone
    d, out = datetime(1994, 8, 17, 1, 0, tzinfo=timezone.utc), {}
    t = threading.Thread(target=lambda: out.update(sun=astro.positions(d)["Sun"], asc=astro.lagna(d, 12.97, 77.59))); t.start(); t.join()
    assert out["sun"]["longitude"] == astro.positions(d)["Sun"]["longitude"] == 120.131 and out["sun"]["sign"] == "Leo"
    assert out["asc"]["longitude"] == astro.lagna(d, 12.97, 77.59)["longitude"]
    j = TestClient(main.app).post("/api/preview", json={"name": "Priya Sharma", "dob": "1994-08-17", "birth_time": "06:30", "city": "Bengaluru"}).json()
    assert j["chart"]["natal"]["Sun"]["sign"] == "Leo"


def pay(c, item):
    o = c.post("/api/billing/order", json={"item": item}).json()
    r = c.post("/api/billing/order/verify", json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_t",
                                                  "razorpay_signature": sign(f"{o['order_id']}|pay_t", "ks")})
    assert r.status_code == 200, r.text
    return o, r.json()["purchase_id"]


def test_three_year_report_costs_499_opens_the_full_report_and_uses_halia_answers(monkeypatch):
    c = client("8111000030")
    answer(c, "L_CAREER", "2"); answer(c, "FOCUS_PILLAR", "career")
    free = c.post("/api/report").json()
    assert any(s["locked"] for s in free["sections"]) and c.get("/api/me").json()["full_report"] is False
    seen = {}
    real = main.ask_claude
    monkeypatch.setattr(main, "ask_claude", lambda system, msgs, **k: seen.update(p=msgs[-1]["content"]) or real(system, msgs, **k))
    o, pid = pay(c, "three_year")
    assert o["amount"] == 49900
    rep = c.post(f"/api/addon/{pid}/generate").json()
    first = rep["calendar"][0]["year"]
    assert rep["kind"] == "three_year" and [y["year"] for y in rep["years"]] == [first, first + 1, first + 2]
    assert all(1 <= k["personal_year"] <= 33 and k["dasha"] for k in rep["calendar"]) and rep["halia_answers"] == 2
    assert "How satisfied are you with your work or studies right now? Low" in seen["p"] and "never promise" in seen["p"].lower()
    assert not any(s["locked"] for s in c.get("/api/report").json()["sections"]) and c.get("/api/me").json()["full_report"] is True
    again = c.post(f"/api/addon/{pid}/generate").json()                    # paid once, written once
    assert again["created_at"] == rep["created_at"]


def test_three_year_report_needs_payment_and_works_without_halia_answers():
    c = client("8111000031", consent=False)
    o = c.post("/api/billing/order", json={"item": "three_year"}).json()
    pid = db.one("SELECT id FROM purchases WHERE provider_order_id=?", o["order_id"])["id"]
    assert c.post(f"/api/addon/{pid}/generate").status_code == 402
    c.post("/api/billing/order/verify", json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_u",
                                             "razorpay_signature": sign(f"{o['order_id']}|pay_u", "ks")})
    assert c.post(f"/api/addon/{pid}/generate").json()["halia_answers"] == 0


def test_dasha_window_is_continuous_and_clipped():
    import astro
    from datetime import datetime, timezone
    b = datetime(1994, 8, 17, 1, 0, tzinfo=timezone.utc)
    a, z = datetime(2027, 1, 1, tzinfo=timezone.utc), datetime(2030, 1, 1, tzinfo=timezone.utc)
    w = astro.dasha_window(astro.positions(b)["Moon"]["longitude"], b, a, z)
    assert w[0]["start"] == "2027-01-01" and w[-1]["end"] == "2030-01-01"
    assert all(x["end"] == y["start"] for x, y in zip(w, w[1:])) and 3 <= len(w) <= 12
    now = astro.vimshottari(astro.positions(b)["Moon"]["longitude"], b, a)
    assert (w[0]["maha"], w[0]["antar"]) == (now["mahadasha"]["lord"], now["antardasha"]["lord"])


def test_report_pdf_holds_only_what_the_person_can_see(monkeypatch):
    c = client("8111000040", name="Asha Rao")
    assert c.get("/api/report/pdf").status_code == 404                           # nothing written yet
    c.post("/api/report"); answer(c, "L_MONEY", "2"); answer(c, "TIME_AVAILABLE", "30")
    r = c.get("/api/report/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-"
    assert 'filename="Destiny-OS-Asha-Rao.pdf"' in r.headers["content-disposition"]
    _, pid = pay(c, "three_year"); c.post(f"/api/addon/{pid}/generate")
    full = c.get("/api/report/pdf")
    assert full.status_code == 200 and len(full.content) > len(r.content)        # three years and seven more chapters added
    assert TestClient(main.app).get("/api/report/pdf").status_code == 401         # signed-in people only, their own report


def test_report_pdf_renders_hindi():
    c = TestClient(main.app); signup(c, "8111000042", "Priya Sharma", language="hi")
    c.post("/api/halia/consent", json={"consent": True})
    assert c.post("/api/report", params={"lang": "hi"}).status_code == 200
    r = c.get("/api/report/pdf", params={"lang": "hi"})
    assert r.status_code == 200 and b"NotoSansDevanagari" in r.content           # the Devanagari font was needed and embedded
