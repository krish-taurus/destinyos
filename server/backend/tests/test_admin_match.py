"""Admin panel, discount codes, the HALIA snapshot and HALIA Match."""
import pytest
from fastapi.testclient import TestClient

from test_flows import CODES, fake_claude, fake_rzp, sign, signup   # sets the test environment first
import admin, auth, billing, conf, db, halia, main, match
import halia_engine as eng

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def patches(monkeypatch):
    monkeypatch.setattr(main, "ask_claude", fake_claude)
    monkeypatch.setattr(billing, "_rzp", fake_rzp)
    monkeypatch.setattr(auth, "send_sms_otp", lambda phone, code: CODES.__setitem__(phone, code))
    monkeypatch.setenv("ADMIN_PASSWORD", PW)
    main._hits.clear(); admin._tries.clear()
    with db.tx() as c:                                   # each test starts with an empty Match
        for t in ("matches", "match_swipes", "match_blocks", "match_profiles"):
            c.execute(f"DELETE FROM {t}")
    yield
    conf.save({k: "" for k in conf.KEYS})


def boss():
    c = TestClient(main.app)
    assert c.post("/api/admin/login", json={"password": PW}).status_code == 200
    return c


def person(phone, name, dob="1994-08-17"):
    c = TestClient(main.app)
    r = c.post("/api/auth/otp", json={"phone": phone}).json()
    j = c.post("/api/auth/verify", json={"phone": phone, "code": CODES[r["phone"]]}).json()
    c.post("/api/auth/register", json={"signup_token": j["signup_token"], "name": name, "dob": dob, "city": "Bengaluru", "consent": True})
    return c


COUPLE = {"FAMILY_PLAN": "want", "MARRIAGE_TIMELINE": "1", "AMBITION": "balanced", "LIVING": "metro", "FAMILY_SETUP": "nuclear",
          "TRADITION": "medium", "DIET": "veg", "MONEY_STYLE": "saver", "RISK": "low", "SOCIAL": "home", "SCHEDULE": "early",
          "CARE_PREF": "time", "CONFLICT": "talk"}


def matcher(phone, name, gender, seeking, answers=COUPLE, **kw):
    c = person(phone, name, kw.pop("dob", "1994-08-17"))
    assert c.post("/api/halia/consent", json={"consent": True}).status_code == 200
    for f, v in answers.items():
        assert c.post("/api/halia/answers", json={"question_id": eng.BY_FIELD[f]["id"], "value": v}).status_code == 200
    body = {"display_name": name.split()[0], "gender": gender, "seeking": seeking, "age_min": 21, "age_max": 45, "city": "Bengaluru",
            "intent": "marriage", "bio": "Books and long walks.", "consent": True, **kw}
    r = c.put("/api/match/profile", json=body); assert r.status_code == 200, r.text
    return c


def uid(phone):
    return db.one("SELECT id FROM users WHERE phone=?", "+91" + phone)["id"]


# ── admin ──
def test_admin_needs_the_password_and_locks_after_five_wrong_tries(monkeypatch):
    c = TestClient(main.app)
    assert c.get("/api/admin/overview").status_code == 401 and c.get("/api/admin/users").status_code == 401
    assert c.put("/api/admin/settings", json={"values": {"MSG91_AUTH_KEY": "x"}}).status_code == 401
    for _ in range(5):
        assert c.post("/api/admin/login", json={"password": "nope"}).status_code == 401
    assert c.post("/api/admin/login", json={"password": PW}).status_code == 429
    admin._tries.clear(); monkeypatch.setenv("ADMIN_PASSWORD", "short")
    assert c.post("/api/admin/login", json={"password": "short"}).status_code == 503
    admin._tries.clear(); monkeypatch.setenv("ADMIN_PASSWORD", PW); monkeypatch.setenv("ADMIN_EMAIL", "Owner@Example.com")
    assert c.post("/api/admin/login", json={"password": PW}).status_code == 401                      # email now required
    assert c.post("/api/admin/login", json={"email": "someone@else.com", "password": PW}).status_code == 401
    assert c.post("/api/admin/login", json={"email": " owner@example.com", "password": PW}).status_code == 200
    c.post("/api/admin/logout"); monkeypatch.delenv("ADMIN_EMAIL")
    signed_in_user = person("8222000001", "Ravi Kumar")
    assert signed_in_user.get("/api/admin/overview").status_code == 401          # an ordinary account is not an admin


def test_keys_saved_in_the_panel_take_effect_at_once_and_are_never_shown():
    c = boss()
    assert auth.OTP_DEV_MODE is True or auth.MSG91_AUTH_KEY == ""
    r = c.put("/api/admin/settings", json={"values": {"RAZORPAY_KEY_ID": "rzp_live_abc", "RAZORPAY_KEY_SECRET": "supersecretvalue1234",
                                                     "WA_NUMBER": "+91 98123 45678"}})
    assert r.status_code == 200 and "supersecretvalue1234" not in r.text
    s = {x["key"]: x for x in r.json()["settings"]}
    assert s["RAZORPAY_KEY_SECRET"]["shown"] == "…1234" and s["RAZORPAY_KEY_SECRET"]["source"] == "panel" and s["RAZORPAY_KEY_ID"]["shown"] == "rzp_live_abc"
    assert billing.KEY_ID == "rzp_live_abc" and billing.KEY_SECRET == "supersecretvalue1234" and halia.WA_NUMBER == "919812345678"
    assert "supersecretvalue1234" not in str(db.all_("SELECT data FROM events WHERE kind='admin_settings'"))
    assert c.put("/api/admin/settings", json={"values": {"SESSION_SECRET": "x"}}).status_code == 422
    assert c.put("/api/admin/settings", json={"values": {"RAZORPAY_KEY_SECRET": ""}}).json()["settings"]
    assert billing.KEY_SECRET == conf._FILE["RAZORPAY_KEY_SECRET"]            # cleared: back to the server file
    assert c.post("/api/admin/settings/test-ai").json()["ok"] is True
    assert c.get("/api/admin/overview").json()["ready"]["payments"] in (True, False)


def test_admin_creates_finds_and_deletes_accounts():
    c = boss()
    r = c.post("/api/admin/users", json={"phone": "8222000002", "name": "Meera Iyer", "dob": "1990-03-04", "city": "Chennai"})
    assert r.status_code == 200, r.text
    i = r.json()["id"]
    assert c.post("/api/admin/users", json={"phone": "8222000002", "name": "Meera Iyer", "dob": "1990-03-04", "city": "Chennai"}).status_code == 409
    assert c.post("/api/admin/users", json={"phone": "12", "name": "Meera Iyer", "dob": "1990-03-04", "city": "Chennai"}).status_code == 422
    found = c.get("/api/admin/users", params={"q": "Meera"}).json()
    assert found["total"] == 1 and found["users"][0]["phone"] == "+918222000002" and found["users"][0]["tier"] == "free"
    u = TestClient(main.app)                                                    # she can sign in with her own number
    code = u.post("/api/auth/otp", json={"phone": "8222000002"}); assert code.status_code == 200
    assert u.post("/api/auth/verify", json={"phone": "8222000002", "code": CODES["+918222000002"]}).json()["needs_registration"] is False
    assert c.delete(f"/api/admin/users/{i}").status_code == 200
    assert db.one("SELECT 1 FROM users WHERE id=?", i) is None and c.get(f"/api/admin/users/{i}").status_code == 404
    assert u.get("/api/me").status_code == 401


def test_offers_free_report_free_plan_days_and_discount_codes():
    c = boss()
    u = person("8222000003", "Kiran Shah"); i = uid("8222000003")
    assert c.post(f"/api/admin/users/{i}/grant", json={"item": "three_year"}).status_code == 200
    assert u.get("/api/me").json()["full_report"] is True
    assert c.post(f"/api/admin/users/{i}/grant", json={"plan": "plus", "days": 30}).status_code == 200
    me = u.get("/api/me").json()["plan"]
    assert me["tier"] == "plus" and me["renews"] is False
    g = c.get(f"/api/admin/users/{i}").json()
    assert len(g["grants"]) == 1 and g["purchases"][0]["amount_paise"] == 0
    c.delete(f"/api/admin/users/{i}/grant/{g['grants'][0]['id']}")
    assert u.get("/api/me").json()["plan"]["tier"] == "free"
    assert c.post(f"/api/admin/users/{i}/grant", json={"item": "moon"}).status_code == 404

    assert c.post("/api/admin/coupons", json={"code": "diwali 50", "percent": 50, "item": "consultation", "max_uses": 1}).json()["code"] == "DIWALI50"
    assert c.post("/api/admin/coupons", json={"code": "GIFT", "percent": 100, "max_uses": 2}).status_code == 200
    v = person("8222000004", "Leela Nair")
    assert v.post("/api/billing/order", json={"item": "three_year", "coupon": "DIWALI50"}).status_code == 422      # wrong item
    assert v.post("/api/billing/order", json={"item": "three_year", "coupon": "NOPE"}).status_code == 422
    o = v.post("/api/billing/order", json={"item": "consultation", "coupon": "diwali50"}).json()
    assert o["amount"] == 249950 and o["full_amount"] == 499900
    v.post("/api/billing/order/verify", json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_c",
                                             "razorpay_signature": sign(f"{o['order_id']}|pay_c", "ks")})
    assert u.post("/api/billing/order", json={"item": "consultation", "coupon": "DIWALI50"}).status_code == 422    # used up
    f = v.post("/api/billing/order", json={"item": "three_year", "coupon": "GIFT"}).json()
    assert f["free"] is True and v.post(f"/api/addon/{f['purchase_id']}/generate").json()["kind"] == "three_year"
    c.delete("/api/admin/coupons/GIFT")
    assert u.post("/api/billing/order", json={"item": "annual", "coupon": "GIFT"}).status_code == 422
    assert {k["code"]: k["used"] for k in c.get("/api/admin/coupons").json()["coupons"]} == {"DIWALI50": 1, "GIFT": 1}


# ── HALIA snapshot ──
def test_snapshot_is_rule_based_and_follows_the_lowest_level_or_the_chosen_focus():
    s = eng.snapshot({})
    assert s["answered"] == 0 and s["step"] is None
    s = eng.snapshot({"L_CAREER": "4", "L_MONEY": "2", "L_WELLBEING": "3", "TIME_AVAILABLE": "30"})
    assert (s["lowest"], s["focus"], s["chosen"], s["minutes"]) == ("money", "money", False, 30) and s["step"] == eng.STEPS["money"][2]
    s = eng.snapshot({"L_CAREER": "4", "L_MONEY": "2", "FOCUS_PILLAR": "health"})
    assert s["focus"] == "health" and s["lowest"] == "money" and s["step"] == eng.STEPS["health"][1]
    c = person("8222000005", "Asha Rao")
    assert c.get("/api/halia/snapshot").status_code == 403                    # not before consent
    c.post("/api/halia/consent", json={"consent": True})
    c.post("/api/halia/answers", json={"question_id": "Q_L_CAREER_V1", "value": "1"})
    j = c.get("/api/halia/snapshot").json()
    assert j["focus"] == "career" and j["levels"][0]["label"] == "Very low" and "birth" in j["note"]


# ── HALIA Match ──
def test_match_needs_adult_consent_and_a_profile():
    kid = person("8222000010", "Young One", dob="2012-01-01")
    assert kid.put("/api/match/profile", json={"display_name": "Y", "gender": "man", "seeking": "women", "age_min": 18, "age_max": 30,
                                               "city": "Pune", "intent": "marriage", "consent": True}).status_code in (403, 422)
    a = person("8222000011", "Arun Das")
    body = {"display_name": "Arun", "gender": "man", "seeking": "women", "age_min": 21, "age_max": 40, "city": "Pune", "intent": "marriage"}
    assert a.put("/api/match/profile", json={**body, "consent": True}).status_code == 403          # HALIA not on
    assert a.get("/api/match/deck").status_code == 403
    a.post("/api/halia/consent", json={"consent": True})
    assert a.get("/api/match/deck").status_code == 409                                           # no profile yet
    assert a.put("/api/match/profile", json=body).status_code == 422                               # must agree to be shown
    assert a.put("/api/match/profile", json={**body, "consent": True, "bio": "call me 9812345678"}).status_code == 422
    assert a.put("/api/match/profile", json={**body, "consent": True}).status_code == 200
    assert a.get("/api/match/profile").json()["profile"]["display_name"] == "Arun"


def test_deck_is_ranked_by_alignment_and_respects_preferences_both_ways():
    me = matcher("8222000020", "Rohan Mehta", "man", "women")
    matcher("8222000021", "Anita Rao", "woman", "men")                                             # same answers: 100
    matcher("8222000022", "Bhavna Jain", "woman", "men", answers={**COUPLE, "FAMILY_PLAN": "no", "LIVING": "abroad", "CONFLICT": "avoid", "TRADITION": "high"})
    matcher("8222000023", "Chitra Bose", "woman", "women")                                         # not looking for men
    matcher("8222000024", "Dev Anand", "man", "women")                                             # he isn't looking for men
    matcher("8222000025", "Esha Old", "woman", "men", dob="1960-01-01")                            # outside his age range
    matcher("8222000026", "Farah Khan", "woman", "men", answers={"DIET": "veg"})                   # too few answers to score
    d = me.get("/api/match/deck").json()
    names = [c["name"] for c in d["cards"]]
    assert names == ["Anita", "Bhavna", "Farah"]
    assert d["cards"][0]["score"] == 100 and d["cards"][1]["score"] < 80 and d["cards"][2]["enough"] is False and "score" not in d["cards"][2]
    assert all("phone" not in c and "talk_about" not in c for c in d["cards"]) and "prediction" in d["cards"][0]["note"]
    assert d["left"] == {"likes": match.LIKES_PER_DAY, "strong": match.SUPERS_PER_DAY}


def test_two_likes_make_a_match_then_they_can_talk_unmatch_and_report():
    a = matcher("8222000030", "Gopal Varma", "man", "women")
    b = matcher("8222000031", "Hema Pillai", "woman", "men", answers={**COUPLE, "DIET": "nonveg", "SCHEDULE": "late"})
    c = matcher("8222000032", "Indu Menon", "woman", "men")
    ia, ib, ic = uid("8222000030"), uid("8222000031"), uid("8222000032")
    r = a.post("/api/match/swipe", json={"target_id": ib, "action": "like"}).json()
    assert r["matched"] is False and a.post("/api/match/swipe", json={"target_id": ib, "action": "like"}).status_code == 409
    assert a.post("/api/match/swipe", json={"target_id": ic, "action": "pass"}).json()["matched"] is False
    assert [x["name"] for x in a.get("/api/match/deck").json()["cards"]] == []                      # nobody is shown twice
    assert b.get("/api/match/deck").json()["cards"][0]["keen"] is False                             # a plain like stays private
    r = b.post("/api/match/swipe", json={"target_id": ia, "action": "super"}).json()
    assert r["matched"] is True and r["name"] == "Gopal" and r["left"]["strong"] == match.SUPERS_PER_DAY - 1
    assert c.post("/api/match/swipe", json={"target_id": ia, "action": "like"}).json()["matched"] is False   # he passed on her
    mid = r["match_id"]
    lst = a.get("/api/match/matches").json()["matches"]
    assert len(lst) == 1 and lst[0]["name"] == "Hema" and lst[0]["score"] < 100
    full = a.get(f"/api/match/matches/{mid}").json()
    assert {t["question"] for t in full["talk_about"]} == {eng.BY_FIELD["DIET"]["text"], eng.BY_FIELD["SCHEDULE"]["text"]}
    assert c.get(f"/api/match/matches/{mid}").status_code == 404                                    # not her match
    assert c.post(f"/api/match/matches/{mid}/messages", json={"body": "hi"}).status_code == 404
    assert a.post(f"/api/match/matches/{mid}/messages", json={"body": "  Namaste Hema  "}).json()["body"] == "Namaste Hema"
    got = b.get(f"/api/match/matches/{mid}").json()["messages"]
    assert got[0]["mine"] is False and got[0]["body"] == "Namaste Hema"
    assert b.get(f"/api/match/matches/{mid}", params={"after": got[0]["id"]}).json()["messages"] == []
    assert b.post("/api/match/report", json={"target_id": ia, "reason": "rude"}).status_code == 200
    assert a.get("/api/match/matches").json()["matches"] == [] and a.get(f"/api/match/matches/{mid}").status_code == 404
    rep = boss().get("/api/admin/match-reports").json()["reports"][0]
    assert rep["target_name"] == "Gopal Varma" and rep["reason"] == "rude"
    boss().post(f"/api/admin/match-profiles/{ia}/hide")
    assert a.get("/api/match/deck").json()["hidden"] is True


def test_strong_yes_puts_you_first_and_leaving_erases_everything():
    a = matcher("8222000040", "Jai Singh", "man", "women")
    b = matcher("8222000041", "Kavya Reddy", "woman", "men", answers={**COUPLE, "FAMILY_PLAN": "no", "CONFLICT": "avoid", "LIVING": "abroad"})
    c = matcher("8222000042", "Lata Joshi", "woman", "men")
    ia, ib = uid("8222000040"), uid("8222000041")
    b.post("/api/match/swipe", json={"target_id": ia, "action": "super"})
    cards = a.get("/api/match/deck").json()["cards"]
    assert [x["name"] for x in cards] == ["Kavya", "Lata"] and cards[0]["keen"] is True              # ahead of a 100% match
    mid = a.post("/api/match/swipe", json={"target_id": ib, "action": "like"}).json()["match_id"]
    a.post(f"/api/match/matches/{mid}/messages", json={"body": "hello"})
    assert b.delete("/api/match/profile").status_code == 200
    assert db.one("SELECT 1 FROM matches WHERE id=?", mid) is None and db.one("SELECT 1 FROM match_messages WHERE match_id=?", mid) is None
    assert db.one("SELECT 1 FROM match_swipes WHERE user_id=? OR target_id=?", ib, ib) is None
    assert [x["name"] for x in a.get("/api/match/deck").json()["cards"]] == ["Lata"]
    c.delete("/api/halia/consent")                                                                  # withdrawing HALIA leaves Match too
    assert a.get("/api/match/deck").json()["cards"] == [] and db.one("SELECT 1 FROM match_profiles WHERE user_id=?", uid("8222000042")) is None
    a.delete("/api/me")
    assert db.one("SELECT 1 FROM match_profiles WHERE user_id=?", ia) is None


def test_the_public_guide_shows_the_engines_own_steps_and_weights():
    from pathlib import Path
    page = (Path(__file__).resolve().parents[3] / "site" / "guide" / "index.html").read_text()
    assert all(step.replace('"', '\\"') in page or step in page for steps in eng.STEPS.values() for step in steps)
    weights = {a["name"]: sum(i["weight"] for i in a["items"]) for a in eng.DOMAINS["couple"]["areas"]}
    assert list(weights.values()) == [9, 5, 3, 3, 2] and sum(len(a["items"]) for a in eng.DOMAINS["couple"]["areas"]) == 13
    assert eng.DOMAINS["couple"]["min_items"] == 6 and eng.DOMAINS["couple"]["min_coverage"] == 0.6      # what the guide states
    it = {i["field"]: i for a in eng.DOMAINS["couple"]["areas"] for i in a["items"]}
    pts = (3 * eng._item_score(it["FAMILY_PLAN"], "want", "open") + 2 * eng._item_score(it["LIVING"], "metro", "abroad")
           + 2 * eng._item_score(it["MONEY_STYLE"], "saver", "balanced") + 2 * eng._item_score(it["CONFLICT"], "talk", "talk"))
    assert pts == 6 and round(100 * pts / 9) == 67                                                      # the worked example
