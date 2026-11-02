"""End-to-end tests of the customer journey. Run: cd backend && python -m pytest -q tests"""
import hashlib, hmac, json, os, sys, tempfile

os.environ.update({"DESTINY_DB": tempfile.mktemp(suffix=".db"), "COOKIE_SECURE": "0",
                   "SESSION_SECRET": "test-secret", "ANTHROPIC_API_KEY": "sk-ant-test",
                   "RAZORPAY_KEY_ID": "rzp_test_x", "RAZORPAY_KEY_SECRET": "ks", "RAZORPAY_PLAN_ID": "plan_x",
                   "RAZORPAY_WEBHOOK_SECRET": "whs", "OTP_DEV_MODE": "1", "FREE_QUESTIONS": "3", "DAILY_QUESTIONS": "30"})
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient
import auth, billing, db, main, reports

SECTIONS = {k: f"{k} body sentence one. Sentence two." for k in reports.FREE_SECTIONS + reports.LOCKED_SECTIONS}
CODES = {}
RZP = {"subs": {}}


def fake_claude(system, messages, model=None, max_tokens=1500):
    text = json.dumps(messages[-1]["content"]) if messages else ""
    if "core report" in text:
        return json.dumps({"headline": "You build things that last", "sections": SECTIONS})
    if "compatibility" in text:
        return json.dumps({"headline": "Good match", "score": 7, "sections": {"how_you_connect": "x", "strengths": "y",
                                                                              "friction_points": "z", "how_to_make_it_work": "w"}})
    if "12-month forecast" in text:
        return json.dumps({"headline": "Year of building", "year_theme": "t", "months": [], "best_windows": "May"})
    if "daily guidance" in text.lower() or "today's guidance" in text.lower():
        return json.dumps({"astro_headline": "h", "manifestation": "m", "decisions": [], "wear": [], "avoid": []})
    return "Here is your answer."


def fake_rzp(method, path, **kw):
    if path == "/subscriptions":
        sid = f"sub_{len(RZP['subs']) + 1}"
        RZP["subs"][sid] = {"id": sid, "status": "created"}
        return RZP["subs"][sid]
    if path.startswith("/subscriptions/") and path.endswith("/cancel"):
        sid = path.split("/")[2]
        RZP["subs"][sid]["status"] = "active"   # Razorpay keeps it active until cycle end
        return {**RZP["subs"][sid], "current_end": db.now() + 20 * 86400}
    if path.startswith("/subscriptions/"):
        sid = path.split("/")[2]
        return {"id": sid, "status": "active", "current_end": db.now() + 30 * 86400}
    if path == "/orders":
        return {"id": f"order_{db.now()}_{kw['json']['notes']['item']}"}
    raise AssertionError(path)


@pytest.fixture(autouse=True)
def patches(monkeypatch):
    monkeypatch.setattr(main, "ask_claude", fake_claude)
    monkeypatch.setattr(billing, "_rzp", fake_rzp)
    monkeypatch.setattr(auth, "send_sms_otp", lambda phone, code: CODES.__setitem__(phone, code))
    main._hits.clear()


def sign(msg, secret):
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def signup(c, phone="9876543210", name="Priya Sharma", src="instagram"):
    r = c.post("/api/auth/otp", json={"phone": phone}); assert r.status_code == 200, r.text
    p = r.json()["phone"]
    r = c.post("/api/auth/verify", json={"phone": phone, "code": CODES[p]}); assert r.status_code == 200
    j = r.json()
    if j["needs_registration"]:
        r = c.post("/api/auth/register", json={"signup_token": j["signup_token"], "name": name, "dob": "1994-08-17",
                                                "birth_time": "06:30", "city": "Bengaluru", "consent": True,
                                                "whatsapp_optin": True, "source": src})
        assert r.status_code == 200, r.text
    return p


def subscribe(c):
    r = c.post("/api/billing/subscribe"); assert r.status_code == 200, r.text
    sid = r.json()["subscription_id"]
    r = c.post("/api/billing/subscribe/verify", json={"razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid,
                                                      "razorpay_signature": sign(f"pay_1|{sid}", "ks")})
    assert r.status_code == 200 and r.json()["subscribed"], r.text
    return sid


def test_signed_out_is_blocked():
    c = TestClient(main.app)
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/report").status_code == 401


def test_phone_normalisation_and_bad_numbers():
    assert auth.normalise_phone("98765 43210") == "+919876543210"
    assert auth.normalise_phone("+91-98765-43210") == "+919876543210"
    with pytest.raises(Exception):
        auth.normalise_phone("12345")


def test_wrong_otp_then_lockout():
    c = TestClient(main.app)
    p = c.post("/api/auth/otp", json={"phone": "9000000001"}).json()["phone"]
    for _ in range(5):
        assert c.post("/api/auth/verify", json={"phone": p, "code": "000000" if CODES[p] != "000000" else "111111"}).status_code == 400
    assert c.post("/api/auth/verify", json={"phone": p, "code": CODES[p]}).status_code == 429


def test_otp_resend_gap():
    c = TestClient(main.app)
    c.post("/api/auth/otp", json={"phone": "9000000002"})
    assert c.post("/api/auth/otp", json={"phone": "9000000002"}).status_code == 429


def test_free_journey_locks_then_subscription_unlocks():
    c = TestClient(main.app)
    signup(c, "9111111111")
    me = c.get("/api/me").json()
    assert me["free_report_available"] and not me["plan"]["subscribed"] and me["questions"] == {"kind": "free", "left": 3, "of": 3}

    rep = c.post("/api/report").json()
    locked = [s for s in rep["sections"] if s["locked"]]
    assert len(locked) == len(reports.LOCKED_SECTIONS)
    assert all("body" not in s for s in locked), "locked text must never reach a free user's browser"
    assert all(s["teaser"] for s in locked)
    assert c.get("/api/me").json()["free_report_available"] is False

    # Plus-only features are blocked with 402 (payment required)
    assert c.post("/api/brief", json={"meals": []}).status_code == 402
    assert c.post("/api/compass", json={}).status_code == 402

    # 3 free questions, then the paywall
    for i in range(3):
        r = c.post("/api/ask", json={"turns": [{"role": "user", "content": f"q{i}"}]}); assert r.status_code == 200
    r = c.post("/api/ask", json={"turns": [{"role": "user", "content": "q4"}]})
    assert r.status_code == 402 and "Subscribe" in r.json()["detail"]

    subscribe(c)
    rep = c.get("/api/report").json()
    assert not any(s["locked"] for s in rep["sections"]) and all(s["body"] for s in rep["sections"])
    assert c.post("/api/brief", json={"meals": []}).status_code == 200
    r = c.post("/api/ask", json={"turns": [{"role": "user", "content": "now?"}]})
    assert r.status_code == 200 and r.json()["questions"]["kind"] == "daily" and r.json()["questions"]["left"] == 29


def test_fair_use_daily_cap(monkeypatch):
    monkeypatch.setattr(main, "DAILY_QUESTIONS", 2)
    c = TestClient(main.app)
    signup(c, "9222222222"); subscribe(c)
    for _ in range(2):
        assert c.post("/api/ask", json={"turns": [{"role": "user", "content": "x"}]}).status_code == 200
    r = c.post("/api/ask", json={"turns": [{"role": "user", "content": "x"}]})
    assert r.status_code == 429 and "fair-use" in r.json()["detail"]


def test_bad_payment_signature_rejected():
    c = TestClient(main.app)
    signup(c, "9333333333")
    sid = c.post("/api/billing/subscribe").json()["subscription_id"]
    r = c.post("/api/billing/subscribe/verify", json={"razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid,
                                                      "razorpay_signature": "forged"})
    assert r.status_code == 400 and not c.get("/api/me").json()["plan"]["subscribed"]


def test_webhook_signature_and_lifecycle():
    c = TestClient(main.app)
    signup(c, "9444444444")
    sid = c.post("/api/billing/subscribe").json()["subscription_id"]

    def hook(event, status, end):
        body = json.dumps({"event": event, "payload": {"subscription": {"entity": {"id": sid, "status": status, "current_end": end}}}})
        return c.post("/api/billing/webhook", content=body, headers={"x-razorpay-signature": sign(body, "whs")})

    bad = json.dumps({"event": "subscription.activated"})
    assert c.post("/api/billing/webhook", content=bad, headers={"x-razorpay-signature": "nope"}).status_code == 400
    assert hook("subscription.activated", "active", db.now() + 30 * 86400).status_code == 200
    assert c.get("/api/me").json()["plan"]["subscribed"]
    # renewal failed: halted but still inside the 3-day grace window
    hook("subscription.halted", "halted", db.now() - 86400)
    assert c.get("/api/me").json()["plan"]["subscribed"]
    # well past grace: locked again
    hook("subscription.halted", "halted", db.now() - 10 * 86400)
    assert not c.get("/api/me").json()["plan"]["subscribed"]


def test_cancel_keeps_access_until_period_end():
    c = TestClient(main.app)
    signup(c, "9555555555"); subscribe(c)
    r = c.post("/api/billing/cancel"); assert r.status_code == 200 and r.json()["cancel_at_period_end"]
    assert c.get("/api/me").json()["plan"]["subscribed"]


def test_one_free_report_per_phone_survives_deletion():
    c = TestClient(main.app)
    signup(c, "9666666666")
    assert c.post("/api/report").status_code == 200
    assert c.delete("/api/me").status_code == 200
    assert c.get("/api/me").status_code == 401           # session gone with the account
    signup(c, "9666666666")                              # same number registers again
    me = c.get("/api/me").json()
    assert me["free_report_available"] is False
    r = c.post("/api/report"); assert r.status_code == 402 and "already" in r.json()["detail"]
    subscribe(c)                                         # paying gets the full report
    assert c.post("/api/report").status_code == 200


def test_deletion_removes_personal_data():
    c = TestClient(main.app)
    p = signup(c, "9777777777"); c.post("/api/report")
    c.delete("/api/me")
    assert db.one("SELECT * FROM users WHERE phone=?", p) is None
    assert db.one("SELECT 1 FROM reports r LEFT JOIN users u ON u.id=r.user_id WHERE u.id IS NULL") is None


def test_addons_compatibility_and_consultation():
    c = TestClient(main.app)
    signup(c, "9888888888")
    assert c.post("/api/billing/order", json={"item": "compatibility", "details": {}}).status_code == 422
    o = c.post("/api/billing/order", json={"item": "compatibility",
                                           "details": {"name": "Arjun Rao", "dob": "1992-02-03", "relation": "partner"}}).json()
    assert o["amount"] == 99900
    pid_resp = c.post("/api/billing/order/verify", json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_9",
                                                         "razorpay_signature": sign(f"{o['order_id']}|pay_9", "ks")})
    assert pid_resp.status_code == 200
    rep = c.post(f"/api/addon/{pid_resp.json()['purchase_id']}/generate").json()
    assert rep["kind"] == "compatibility" and rep["partner"] == "Arjun Rao"

    o = c.post("/api/billing/order", json={"item": "consultation"}).json()
    pid = db.one("SELECT id FROM purchases WHERE provider_order_id=?", o["order_id"])["id"]
    assert c.post(f"/api/addon/{pid}/generate").status_code == 402          # not paid yet
    c.post("/api/billing/order/verify", json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_8",
                                             "razorpay_signature": sign(f"{o['order_id']}|pay_8", "ks")})
    assert "wa.me" in c.post(f"/api/addon/{pid}/generate").json()["whatsapp"]


def test_users_cannot_see_each_others_purchases():
    a, b = TestClient(main.app), TestClient(main.app)
    signup(a, "9000000011"); signup(b, "9000000012")
    o = a.post("/api/billing/order", json={"item": "annual"}).json()
    pid = db.one("SELECT id FROM purchases WHERE provider_order_id=?", o["order_id"])["id"]
    assert b.post(f"/api/addon/{pid}/generate").status_code == 402
    assert b.post("/api/billing/order/verify", json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": "p",
                                                     "razorpay_signature": sign(f"{o['order_id']}|p", "ks")}).status_code == 400


def test_daily_whatsapp_only_opted_in_subscribers(monkeypatch, capsys):
    import daily_whatsapp
    monkeypatch.setattr(daily_whatsapp, "compose", lambda u: [u["name"].split()[0], "5", "change", "green", "write it 6 times"])
    sent = []
    monkeypatch.setattr(daily_whatsapp, "send", lambda phone, params: sent.append(phone))
    c = TestClient(main.app); p = signup(c, "9000000021", name="Opted In"); subscribe(c)
    c2 = TestClient(main.app); signup(c2, "9000000022", name="Free User")            # opted in but not paying
    c3 = TestClient(main.app); p3 = signup(c3, "9000000023", name="No Optin"); subscribe(c3)
    c3.patch("/api/me", json={"whatsapp_optin": False})
    stats = daily_whatsapp.run(dry=False)
    assert p in sent and p3 not in sent and "+919000000022" not in sent
    again = daily_whatsapp.run(dry=False)                                          # never twice a day
    assert sent.count(p) == 1 and again["skipped"] >= 1


# ── Regression tests for the security review ──
from concurrent.futures import ThreadPoolExecutor


def test_parallel_requests_dont_crash_or_sign_out():
    c = TestClient(main.app)
    signup(c, "9100000001")
    with ThreadPoolExecutor(32) as ex:
        codes = list(ex.map(lambda _: c.get("/api/me").status_code, range(200)))
    assert codes.count(200) == 200, {k: codes.count(k) for k in set(codes)}


def test_parallel_free_questions_cannot_exceed_allowance(monkeypatch):
    def slow(*a, **k):
        import time; time.sleep(0.05); return "ok"
    c = TestClient(main.app)
    signup(c, "9100000002")
    monkeypatch.setattr(main, "ask_claude", slow)
    body = {"turns": [{"role": "user", "content": "q"}]}
    with ThreadPoolExecutor(10) as ex:
        codes = list(ex.map(lambda _: c.post("/api/ask", json=body).status_code, range(10)))
    assert codes.count(200) == 3 and codes.count(402) == 7, codes
    assert db.one("SELECT free_questions_used FROM users WHERE phone='+919100000002'")["free_questions_used"] == 3


def test_failed_answer_gives_the_question_back(monkeypatch):
    c = TestClient(main.app)
    signup(c, "9100000003")
    def boom(*a, **k):
        raise main.HTTPException(502, "down")
    monkeypatch.setattr(main, "ask_claude", boom)
    assert c.post("/api/ask", json={"turns": [{"role": "user", "content": "q"}]}).status_code == 502
    assert c.get("/api/me").json()["questions"]["left"] == 3


def test_deleting_does_not_reset_free_questions():
    c = TestClient(main.app)
    signup(c, "9100000004")
    for _ in range(3):
        c.post("/api/ask", json={"turns": [{"role": "user", "content": "q"}]})
    c.delete("/api/me")
    signup(c, "9100000004")
    assert c.get("/api/me").json()["questions"]["left"] == 0
    assert c.post("/api/ask", json={"turns": [{"role": "user", "content": "q"}]}).status_code == 402


def test_new_user_never_inherits_a_deleted_users_id_subscription_or_chart():
    a = TestClient(main.app)
    signup(a, "9100000005", name="Deleted Person")
    sid = subscribe(a)
    old_id = db.one("SELECT id FROM users WHERE phone='+919100000005'")["id"]
    a.get("/api/chart")
    a.delete("/api/me")
    b = TestClient(main.app)
    signup(b, "9100000006", name="New Person")
    new_id = db.one("SELECT id FROM users WHERE phone='+919100000006'")["id"]
    assert new_id != old_id
    body = json.dumps({"event": "subscription.cancelled", "payload": {"subscription": {"entity": {
        "id": sid, "status": "cancelled", "current_end": db.now() + 20 * 86400, "notes": {"user_id": str(new_id)}}}}})
    b.post("/api/billing/webhook", content=body, headers={"x-razorpay-signature": sign(body, "whs")})
    assert not b.get("/api/me").json()["plan"]["subscribed"]
    assert not any(k[0] == old_id for k in main._chart_cache)


def test_late_webhook_on_old_subscription_doesnt_hide_the_live_one():
    c = TestClient(main.app)
    signup(c, "9100000007")
    old = c.post("/api/billing/subscribe").json()["subscription_id"]      # abandoned checkout
    subscribe(c)                                                          # the real one
    body = json.dumps({"event": "subscription.halted", "payload": {"subscription": {"entity": {
        "id": old, "status": "halted", "current_end": None}}}})
    c.post("/api/billing/webhook", content=body, headers={"x-razorpay-signature": sign(body, "whs")})
    assert c.get("/api/me").json()["plan"]["subscribed"]


def test_spoofed_forwarded_for_doesnt_dodge_otp_limit():
    c = TestClient(main.app)
    codes = [c.post("/api/auth/otp", json={"phone": f"98000{i:05d}"}, headers={"x-forwarded-for": f"1.2.3.{i}"}).status_code
             for i in range(12)]
    assert codes.count(429) >= 2, codes


def test_impossible_birth_date_is_a_clear_error():
    c = TestClient(main.app)
    p = c.post("/api/auth/otp", json={"phone": "9100000008"}).json()["phone"]
    tok = c.post("/api/auth/verify", json={"phone": p, "code": CODES[p]}).json()["signup_token"]
    r = c.post("/api/auth/register", json={"signup_token": tok, "name": "Test Name", "dob": "1990-02-31",
                                           "city": "Bengaluru", "consent": True})
    assert r.status_code == 422 and "exist" in r.json()["detail"]
