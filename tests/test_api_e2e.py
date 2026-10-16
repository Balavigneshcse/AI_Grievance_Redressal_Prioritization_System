"""End-to-end test of the running API and the AI pipeline. Exercises every
feature built up to Checkpoint 4 against the live server:

  languages (Tamil script, Devanagari, Tanglish, Hinglish, English), urgency,
  rules (gas leak, oxygen, repeat, child), photo with EXIF GPS, duplicates,
  PII masking and role visibility, district office and due time, officer
  decisions (reassign, merge, request info, resolve, close), admin metrics,
  rules test and model reload, auth (wrong password, register with OTP,
  forgot/reset invalidating old tokens), media access control, email logging.

Needs: API on :8000, Postgres, Ollama with gemma3:4b and bge-m3, Mailpit on :8025
(SMTP_HOST=localhost in .env, so OTPs can be read back). Settings are read from the environment
first, then .env: API_URL points the suite at another API (e.g. a test API on :8100 with its own
DATABASE_URL, which the suite also uses for its direct database updates).

Run from the project root:  python tests/test_api_e2e.py
Writes data/eval/e2e_report.json. Exit code 1 if any check fails.
"""
from __future__ import annotations

import io
import os
import json
import re
import string
import sys
import threading
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
API = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
MAIL = "http://localhost:8025"
URG = {"critical": 3, "high": 2, "medium": 1, "low": 0}

results: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)
    return ok


def env(key: str, default: str = "") -> str:
    # A variable set in the environment wins over .env, so the suite can run against
    # Mailpit while .env points at Gmail (export SMTP_HOST=localhost for both API and test).
    if key in os.environ:
        return os.environ[key]
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return default


def login(email: str, password: str) -> dict:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def latest_otp(email: str, seen: int = 0) -> str:
    """The newest OTP mail for the address, once more than `seen` mails exist for it.
    Mail leaves through a background outbox, so a fresh code can land a second or two
    after the request that created it."""
    for _ in range(40):
        msgs = requests.get(f"{MAIL}/api/v1/search", params={"query": f"to:{email}", "limit": 10}, timeout=10).json()["messages"]
        mine = [m for m in msgs if any(email == (t.get("Address") or "").lower() for t in m["To"])]
        if len(mine) > seen:
            for m in mine:  # Mailpit lists newest first
                text = requests.get(f"{MAIL}/api/v1/message/{m['ID']}", timeout=10).json()["Text"]
                found = re.search(r"\b(\d{6})\b", text)
                if found:
                    return found.group(1)
        time.sleep(1)
    raise RuntimeError("no OTP email for " + email)


def wait_mail(email: str, min_count: int, timeout: int = 120) -> int:
    """Mail count for the address once it reaches min_count, or the count at timeout.
    The outbox may be translating a note with the model in front of it."""
    t0 = time.time()
    n = mail_count(email)
    while n < min_count and time.time() - t0 < timeout:
        time.sleep(3)
        n = mail_count(email)
    return n


def mail_count(email: str) -> int:
    """Every mail Mailpit holds for the address. The search endpoint counts across the whole
    inbox; the newest-N list stops growing for an address once the inbox holds more than N mails."""
    r = requests.get(f"{MAIL}/api/v1/search", params={"query": f"to:{email}", "limit": 1}, timeout=10).json()
    return int(r.get("messages_count", 0))


def submit(H: dict, text: str, **fields) -> dict:
    files = fields.pop("files", None)
    r = requests.post(f"{API}/complaints", headers=H, data={"text": text, **fields}, files=files, timeout=120)
    if r.status_code != 202:
        raise RuntimeError(f"submit failed {r.status_code}: {r.text[:200]}")
    return r.json()


def wait_analysed(H: dict, cid: str, limit: int = 300) -> dict:
    t0 = time.time()
    while time.time() - t0 < limit:
        d = requests.get(f"{API}/complaints/{cid}", headers=H, timeout=30).json()
        if d["status"] not in ("received", "analysing"):
            d["_seconds"] = round(time.time() - t0)
            return d
        time.sleep(4)
    raise RuntimeError("analysis timed out for " + cid)


def at_once(fn, n: int) -> list:
    """Call fn from n threads released at the same moment (double clicks, two officers) and return the results."""
    barrier, out = threading.Barrier(n), [None] * n

    def run(i: int) -> None:
        barrier.wait()
        out[i] = fn()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def flat(d: dict, prefix: str = "") -> dict[str, str]:
    """An i18n file's nested keys as dotted paths."""
    out = {}
    for k, v in d.items():
        out.update(flat(v, f"{prefix}{k}.") if isinstance(v, dict) else {prefix + k: v})
    return out


def test_image_with_gps() -> bytes:
    img = Image.new("RGB", (640, 480), (118, 118, 118))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 300, 640, 480), fill=(90, 90, 90))
    d.ellipse((230, 200, 440, 340), fill=(25, 25, 25))
    d.text((20, 20), "Large pothole on the main road, bikes skidding", fill=(255, 255, 255))
    from PIL.TiffImagePlugin import IFDRational

    exif = Image.Exif()
    exif[0x8825] = {  # GPS IFD: 11°1'6" N, 76°58'3" E (Gandhipuram, Coimbatore)
        1: "N", 2: (IFDRational(11, 1), IFDRational(1, 1), IFDRational(6, 1)),
        3: "E", 4: (IFDRational(76, 1), IFDRational(58, 1), IFDRational(3, 1)),
    }
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


def main() -> int:
    seed_pw = env("SEED_PASSWORD", "Synapse@123")
    print("== health ==")
    h = requests.get(f"{API}/health", timeout=20).json()
    check("health: db and ollama up", h["db"] == "ok" and h["ollama"] == "ok", json.dumps(h["models"]))
    check("health: second-opinion model present", h["models"].get("second_opinion") is True)

    print("\n== auth ==")
    r = requests.post(f"{API}/auth/login", json={"email": "citizen@synapse.local", "password": "wrong-pass-1A!"}, timeout=30)
    check("wrong password rejected", r.status_code == 401)
    HC = login("citizen@synapse.local", seed_pw)
    HO_roads = login("officer.roads@synapse.local", seed_pw)
    HO_water = login("officer.water@synapse.local", seed_pw)
    HA = login("admin@synapse.local", seed_pw)
    r = requests.get(f"{API}/review/queue", headers=HC, timeout=30)
    check("complainant cannot open the review queue", r.status_code == 403)
    # Identity (name, Aadhaar last 4) is taken once at registration and copied onto every complaint.
    no_id = {"mobile": "9123456780", "email": "no.identity@synapse.local", "password": "Strong@12345"}
    r = requests.post(f"{API}/auth/register", json=no_id, timeout=30)
    check("registration without name and Aadhaar digits rejected", r.status_code in (400, 422), str(r.status_code))
    r = requests.post(f"{API}/auth/register", json={**no_id, "full_name": "No Identity", "aadhaar_last4": "12a4"}, timeout=30)
    check("registration with bad Aadhaar digits rejected", r.status_code == 400, r.json().get("detail", "")[:60])
    r = requests.patch(f"{API}/auth/me", headers=HC, json={"full_name": "Demo Citizen", "aadhaar_last4": "4321"}, timeout=30)
    check("citizen completes account details (PATCH /auth/me)", r.status_code == 200 and r.json().get("aadhaar_last4") == "4321", r.text[:80])
    r = requests.patch(f"{API}/auth/me", headers=HC, json={"aadhaar_last4": "43210"}, timeout=30)
    check("five-digit Aadhaar rejected", r.status_code == 400, str(r.status_code))

    mail_ok = env("SMTP_HOST", "localhost") == "localhost"
    stamp = int(time.time())
    new_email = f"e2e.{stamp}@synapse.local"
    new_mobile = "9" + str(stamp)[-9:]  # unique per run; mobiles are unique in the users table
    if mail_ok:
        new_user = {"mobile": new_mobile, "email": new_email, "preferred_language": "hi", "full_name": "E2E Citizen", "aadhaar_last4": "7788"}
        r = requests.post(f"{API}/auth/register", json={**new_user, "password": "Weak"}, timeout=30)
        check("weak password rejected", r.status_code == 400, r.json().get("detail", "")[:60])
        r = requests.post(f"{API}/auth/register", json={**new_user, "password": "Strong@12345"}, timeout=60)
        check("register accepted", r.status_code == 201, r.text[:80] if r.status_code != 201 else "")
        r = requests.post(f"{API}/auth/login", json={"email": new_email, "password": "Strong@12345"}, timeout=30)
        check("login blocked until verified", r.status_code == 403)
        code = latest_otp(new_email)
        r = requests.post(f"{API}/auth/verify-otp", json={"email": new_email, "code": "000000" if code != "000000" else "111111"}, timeout=30)
        check("wrong OTP rejected", r.status_code == 400)
        r = requests.post(f"{API}/auth/verify-otp", json={"email": new_email, "code": code}, timeout=30)
        check("correct OTP verifies and logs in", r.status_code == 200)
        me = r.json().get("user", {})
        check("account carries the name and Aadhaar digits given at registration", me.get("full_name") == "E2E Citizen" and me.get("aadhaar_last4") == "7788", str(me)[:100])
        H_new = {"Authorization": "Bearer " + r.json()["access_token"]}
        seen = mail_count(new_email)
        requests.post(f"{API}/auth/forgot", json={"email": new_email}, timeout=60)
        code2 = latest_otp(new_email, seen)
        r = requests.post(f"{API}/auth/reset", json={"email": new_email, "code": code2, "new_password": "Changed@12345"}, timeout=30)
        check("password reset with OTP", r.status_code == 200)
        r = requests.get(f"{API}/auth/me", headers=H_new, timeout=30)
        check("old token invalid after reset", r.status_code == 401)
        r = requests.post(f"{API}/auth/login", json={"email": new_email, "password": "Changed@12345"}, timeout=30)
        check("login with new password", r.status_code == 200)
        H_new = {"Authorization": "Bearer " + r.json()["access_token"]}
    else:
        print("skip: register/OTP tests need Mailpit (SMTP_HOST=localhost)")
        H_new = None

    print("\n== AI pipeline: languages, urgency, rules ==")
    cases = [
        ("ta script, water, child sick", "எங்கள் தெருவில் மூன்று நாட்களாக குடிநீர் வரவில்லை. வீட்டில் இரண்டு குழந்தைகள் வாந்தி மற்றும் காய்ச்சலால் அவதிப்படுகிறார்கள். காந்திபுரம் 5வது தெரு. உடனே தண்ணீர் அனுப்பவும்.",
         {"lat": 11.0183, "lng": 76.9674, "location_source": "browser"}, {"lang": "ta", "dept": {"water"}, "min_urg": "high", "review": True, "rule_any": ["R5", "R10"]}),
        ("hi script, power cut, oxygen", "हमारे इलाके में सुबह छह बजे से बिजली नहीं है। मेरे पिता ऑक्सीजन मशीन पर हैं और बैकअप सिर्फ दो घंटे चलेगा। आर एस पुरम, कोयंबटूर। कृपया तुरंत मदद करें।",
         {"lat": 11.008, "lng": 76.95, "location_source": "browser"}, {"lang": "hi", "dept": {"electricity"}, "min_urg": "critical", "review": True, "rule_any": ["R2"]}),
        ("en, suggestion, low", "Just a suggestion: the park near Race Course could use a few more benches for senior citizens. Thanks for the good work.",
         {"lat": 11.003, "lng": 76.973, "location_source": "browser"}, {"lang": "en", "dept": {"general"}, "max_urg": "medium", "review": False, "rule_any": []}),
        ("hi-en, gas smell", "gas ki badbu aa rahi hai humari building ke neeche wali dukaan se, kal raat se. bacche ghar pe hain. Peelamedu. jaldi kisi ko bhejo",
         {"lat": 11.027, "lng": 77.003, "location_source": "browser"}, {"lang": "hi", "dept": {"safety"}, "min_urg": "critical", "review": True, "rule_any": ["R1"]}),
        ("ta-en, pothole accident, repeat", "pothole romba periya, nethu oru auto thirumbi vizhundhuchu, driver ku kaayam. trichy road near lakshmi mills signal. already complaint pannen, no action taken",
         {"lat": 11.0, "lng": 76.99, "location_source": "browser"}, {"lang": "ta", "dept": {"roads"}, "min_urg": "high", "review": None, "rule_any": ["R8"]}),
    ]
    ids: dict[str, str] = {}
    for name, text, fields, exp in cases:
        acc = submit(HC, text, **fields)
        d = wait_analysed(HC, acc["id"])
        ids[name] = acc["id"]
        a = d["analysis"] or {}
        rules = a.get("matched_rule_ids") or []
        detail = f"{acc['tracking_id']} {d['status']} {d['department'] and d['department']['id']}/{d['urgency']} lang={a.get('language_primary')} conf={a.get('confidence')} rules={rules} {d['_seconds']}s"
        ok = a.get("language_primary") == exp["lang"]
        ok &= (d["department"] or {}).get("id") in exp["dept"]
        if "min_urg" in exp:
            ok &= URG.get(d["urgency"], -1) >= URG[exp["min_urg"]]
        if "max_urg" in exp:
            ok &= URG.get(d["urgency"], 9) <= URG[exp["max_urg"]]
        if exp["review"] is True:
            ok &= d["status"] == "under_review"
        if exp["review"] is False:
            ok &= d["status"] == "routed"
        if exp["rule_any"]:
            ok &= any(r in rules for r in exp["rule_any"])
        check(f"case: {name}", ok, detail)
        check(f"  evidence spans present and quoted from text", bool(a.get("evidence_spans")) and all(s[:12].lower() in text.lower() or s.lower() in text.lower() for s in a["evidence_spans"][:1]), str(a.get("evidence_spans", [])[:2])[:120])
        check(f"  english summary present", bool(a.get("summary_en")), (a.get("summary_en") or "")[:80])
        check(f"  district office and due time set", bool(d.get("office_name")) and bool(d.get("due_at")), f"{d.get('district')} / {d.get('office_name')}")
        check(f"  second opinion populated (staff view)", requests.get(f"{API}/review/{acc['id']}", headers=HA, timeout=30).json()["analysis"].get("second_opinion_department") is not None)
        check(f"  complaint carries the account's name and Aadhaar digits", d.get("complainant_name") == "Demo Citizen" and d.get("aadhaar_last4") == "4321")

    print("\n== photo with EXIF GPS ==")
    img = test_image_with_gps()
    acc = submit(HC, "see this road near our house, bikes are skidding every day, please fix", location_source="none",
                 files=[("files", ("pothole.jpg", img, "image/jpeg")), ("files", ("pothole2.jpg", img, "image/jpeg"))])
    d = wait_analysed(HC, acc["id"])
    ids["photo"] = acc["id"]
    a = d["analysis"] or {}
    check("photo: both photos stored and sent to the model", len(d["media"]) == 2, f"{len(d['media'])} media")
    check("photo: EXIF GPS used for location", d["location_source"] == "exif" and (d.get("resolved_place") or "").startswith("Gandhipuram"), f"{d['location_source']} {d.get('resolved_place')}")
    check("photo: image findings from the vision model", bool(a.get("image_findings")), (a.get("image_findings") or "")[:100])
    check("photo: media served to owner", requests.get(f"{API}{d['media'][0]['url']}", headers=HC, timeout=30).status_code == 200 if d["media"] else False)
    if H_new:
        check("photo: media hidden from another complainant", requests.get(f"{API}{d['media'][0]['url']}", headers=H_new, timeout=30).status_code == 403)

    print("\n== duplicates and PII ==")
    dup_text = cases[0][1]
    acc = submit(HC, dup_text, lat=11.0183, lng=76.9674, location_source="browser")
    d = wait_analysed(HC, acc["id"])
    ids["dup"] = acc["id"]
    reasons = (d["decision"] or {}).get("reasons", [])
    check("duplicate of the Tamil water complaint flagged", any("duplicate" in r for r in reasons) and d["status"] == "under_review", "; ".join(r for r in reasons if "duplicate" in r)[:100])
    pii_text = ("my aadhaar is 4321 8765 1234 and phone 9876501234, also 98765 43210 or +91 98765-43211, office +919876543212, "
                "water bill wrong for house 12, Saibaba Colony, Coimbatore 641011")
    acc = submit(HC, pii_text, lat=11.03, lng=76.945, location_source="browser")
    d = wait_analysed(HC, acc["id"])
    ids["pii"] = acc["id"]
    off = requests.get(f"{API}/review/{acc['id']}", headers=HA, timeout=30).json()["analysis"]
    check("PII hidden from complainant", d["analysis"].get("pii_map") in (None, {}))
    check("PII masked and mapped for staff", off.get("pii_map") and any(k.startswith("[PHONE") for k in off["pii_map"]) and any(k.startswith("[AADHAAR") for k in off["pii_map"]) and "9876501234" not in (off.get("masked_text") or ""), str(list((off.get("pii_map") or {}).keys())))
    pm = off.get("pii_map") or {}
    found = {label: sorted(v for k, v in pm.items() if k.startswith(f"[{label}_")) for label in ("PHONE", "AADHAAR", "PIN")}
    check("PII: mobiles with spaces, dashes or +91 masked as phones, the PIN code masked",
          found == {"PHONE": sorted(["9876501234", "98765 43210", "+91 98765-43211", "+919876543212"]), "AADHAAR": ["4321 8765 1234"], "PIN": ["641011"]}
          and not re.search(r"\d{5}", off.get("masked_text") or ""), json.dumps(found, ensure_ascii=False)[:160])

    print("\n== officer decisions ==")
    q = requests.get(f"{API}/review/queue?view=review", headers=HA, timeout=30).json()
    check("review queue lists the flagged cases", len(q) >= 3 and all("flags" in i and "status" in i for i in q), f"{len(q)} items; flags of first: {q[0]['flags'] if q else None}")
    r = requests.get(f"{API}/review/{ids[cases[0][0]]}", headers=HO_roads, timeout=30)
    check("roads admin cannot open a water complaint", r.status_code == 403, str(r.status_code))
    dq_roads = requests.get(f"{API}/review/queue?view=all", headers=HO_roads, timeout=30).json()
    check("department admin sees only its department", all(i["department"] == "roads" for i in dq_roads), f"{len(dq_roads)} items")
    r = requests.post(f"{API}/review/{ids['dup']}/decision", headers=HO_water, json={"action": "merge", "merged_into": "SYN-0", "reason": "looks like a duplicate"}, timeout=30)
    check("merge into unknown target rejected", r.status_code == 400, str(r.status_code))
    first_tid = requests.get(f"{API}/complaints/{ids[cases[0][0]]}", headers=HC, timeout=30).json()["tracking_id"]
    r = requests.post(f"{API}/review/{ids['dup']}/decision", headers=HO_water, json={"action": "merge", "merged_into": first_tid, "reason": "same street, same outage"}, timeout=30)
    check("merge duplicate into original", r.status_code == 200 and r.json()["status"] == "merged")
    r = requests.post(f"{API}/review/{ids[cases[1][0]]}/decision", headers=HA, json={"action": "request_info", "reason": "please share the exact door number"}, timeout=30)
    check("request info -> awaiting_info", r.status_code == 200 and r.json()["status"] == "awaiting_info")
    r = requests.post(f"{API}/review/{ids[cases[0][0]]}/decision", headers=HO_water, json={"action": "reassign", "department": "water", "urgency": "high", "reason": "tanker sent, no longer life risk"}, timeout=30)
    check("reassign urgency -> routed", r.status_code == 200 and r.json()["status"] == "routed")
    r = requests.post(f"{API}/review/{ids[cases[2][0]]}/decision", headers=HA, json={"action": "close", "reason": "closing without resolving"}, timeout=30)
    check("close before resolve rejected", r.status_code == 409, str(r.status_code))
    r = requests.post(f"{API}/review/{ids[cases[2][0]]}/decision", headers=HA, json={"action": "resolve", "reason": "benches approved"}, timeout=30)
    r2 = requests.post(f"{API}/review/{ids[cases[2][0]]}/decision", headers=HA, json={"action": "close", "reason": "citizen informed"}, timeout=30)
    check("resolve then close", r.status_code == 200 and r2.status_code == 200 and r2.json()["status"] == "closed")
    r = requests.post(f"{API}/review/{ids['pii']}/decision", headers=HO_water, json={"action": "reassign", "department": "water", "reason": ""}, timeout=30)
    check("decision without reason rejected", r.status_code == 422)
    tl = requests.get(f"{API}/complaints/{ids[cases[2][0]]}/timeline", headers=HC, timeout=30).json()
    check("timeline records every transition", [e["to_status"] for e in tl] == ["received", "analysing", "routed", "resolved", "closed"], str([e["to_status"] for e in tl]))
    dq = requests.get(f"{API}/departments/water/queue", headers=HO_water, timeout=30).json()
    check("department queue shows routed water complaints", any(i["id"] == ids[cases[0][0]] for i in dq), f"{len(dq)} items")

    print("\n== citizen reply, staff mail, overdue escalation ==")
    waiting = ids[cases[1][0]]  # HA asked for more information on this one above
    r = requests.post(f"{API}/complaints/{waiting}/reply", headers=HC, data={"text": "Door number 12, opposite the temple"}, timeout=60)
    check("citizen reply accepted", r.status_code == 200 and r.json()["status"] == "under_review", r.text[:100])
    tl = requests.get(f"{API}/complaints/{waiting}/timeline", headers=HC, timeout=30).json()
    check("reply recorded in the timeline by the citizen", any(e["actor_type"] == "complainant" and (e["note"] or "").startswith("reply:") for e in tl))
    r = requests.post(f"{API}/complaints/{ids[cases[0][0]]}/reply", headers=HC, data={"text": "Photo of the dry tap attached"}, files=[("files", ("tap.jpg", img, "image/jpeg"))], timeout=60)
    check("reply with a photo on a routed complaint", r.status_code == 200 and r.json()["attachments"] == 1 and r.json()["status"] == "routed", r.text[:100])
    r = requests.post(f"{API}/complaints/{ids[cases[2][0]]}/reply", headers=HC, data={"text": "one more thing"}, timeout=30)
    check("reply on a closed complaint rejected", r.status_code == 409, str(r.status_code))
    r = requests.post(f"{API}/complaints/{ids[cases[0][0]]}/reply", headers=HO_roads, data={"text": "hi"}, timeout=30)
    check("only the complainant can reply", r.status_code == 403, str(r.status_code))
    if mail_ok:
        n_w = wait_mail("officer.water@synapse.local", 1)
        check("department admin emailed about a routed water complaint", n_w >= 1, f"{n_w} mails")
        n_d = wait_mail("district.coimbatore@synapse.local", 1)
        check("district admin emailed about reviews in Coimbatore", n_d >= 1, f"{n_d} mails")
    before_district = mail_count("district.coimbatore@synapse.local") if mail_ok else 0
    import psycopg

    db_url = env("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5434/synapse").replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(db_url) as conn:
        conn.execute("update complaints set due_at = now() - interval '1 hour', escalated_at = null where id = %s", (ids[cases[0][0]],))
        conn.commit()
    r = requests.post(f"{API}/admin/sla/check", headers=HA, timeout=60)
    check("overdue check escalates the overdue complaint", r.status_code == 200 and r.json()["escalated"] >= 1, r.text[:80])
    q = requests.get(f"{API}/review/queue?view=active", headers=HA, timeout=30).json()
    item = next((i for i in q if i["id"] == ids[cases[0][0]]), None)
    check("overdue flag shown in the queue", item is not None and "overdue" in item["flags"], str(item["flags"]) if item else "not in queue")
    d = requests.get(f"{API}/review/{ids[cases[0][0]]}", headers=HA, timeout=30).json()
    check("escalation recorded on the complaint and in the timeline", d.get("escalated_at") is not None and any((e["note"] or "").startswith("SLA breached") for e in d["timeline"]))
    if mail_ok:
        n_d = wait_mail("district.coimbatore@synapse.local", before_district + 1)
        check("district admin emailed about the overdue complaint", n_d > before_district, f"{n_d} mails, {before_district} before")
    r = requests.post(f"{API}/admin/sla/check", headers=HA, timeout=60)
    check("escalation happens once", r.status_code == 200 and r.json()["escalated"] == 0, r.text[:80])
    h = requests.get(f"{API}/health", timeout=20).json()
    check("health reports outbox, overdue and model latency", "outbox_pending" in h and "overdue_open" in h and "model_latency_ms" in h, json.dumps({k: h.get(k) for k in ("outbox_pending", "overdue_open", "model_latency_ms")}))

    print("\n== search, proof, rating, reopen, me-too, map, limits ==")
    water_id = ids[cases[0][0]]
    water_tid = requests.get(f"{API}/complaints/{water_id}", headers=HC, timeout=30).json()["tracking_id"]
    sq = requests.get(f"{API}/review/queue?view=all&q={water_tid}", headers=HA, timeout=30).json()
    check("queue search by tracking id", len(sq) == 1 and sq[0]["id"] == water_id, f"{len(sq)} items")
    sq = requests.get(f"{API}/review/queue?view=all&q=Demo Citizen", headers=HA, timeout=30).json()
    check("queue search by complainant name", len(sq) >= 3, f"{len(sq)} items")
    r = requests.post(f"{API}/review/{water_id}/attachments", headers=HA, files=[("files", ("after.jpg", img, "image/jpeg"))], timeout=60)
    check("office attaches resolution proof", r.status_code == 200 and r.json()["attachments"] == 1, r.text[:100])
    d = requests.get(f"{API}/complaints/{water_id}", headers=HC, timeout=30).json()
    check("citizen sees the proof photo marked as resolution", any(m.get("role") == "resolution" for m in d["media"]), str([m.get("role") for m in d["media"]]))
    r = requests.post(f"{API}/review/{water_id}/attachments", headers=HO_roads, files=[("files", ("x.jpg", img, "image/jpeg"))], timeout=60)
    check("proof upload outside scope rejected", r.status_code == 403, str(r.status_code))

    photo_id = ids["photo"]
    seen_citizen = mail_count("citizen@synapse.local") if mail_ok else 0
    r = requests.post(f"{API}/review/{photo_id}/decision", headers=HA, json={"action": "resolve", "reason": "Pothole filled and the road levelled on 15 October"}, timeout=30)
    check("resolve the photo complaint", r.status_code == 200 and r.json()["status"] == "resolved")
    r = requests.post(f"{API}/complaints/{photo_id}/feedback", headers=HC, json={"rating": 4, "note": "Fixed, thank you"}, timeout=30)
    check("citizen rates the resolution", r.status_code == 200 and r.json()["rating"] == 4, r.text[:100])
    d = requests.get(f"{API}/complaints/{photo_id}", headers=HC, timeout=30).json()
    check("rating stored with the feedback window", d.get("rating") == 4 and d.get("can_reopen_until") is not None)
    r = requests.post(f"{API}/complaints/{photo_id}/feedback", headers=HC, json={"reopen": True, "note": "The pothole is back after the rain"}, timeout=30)
    check("citizen reopens a resolved complaint", r.status_code == 200 and r.json()["status"] == "in_progress" and r.json()["reopen_count"] == 1, r.text[:100])
    tl = requests.get(f"{API}/complaints/{photo_id}/timeline", headers=HC, timeout=30).json()
    check("reopen recorded by the citizen in the timeline", any(e["actor_type"] == "complainant" and (e["note"] or "").startswith("reopened") for e in tl))
    r = requests.post(f"{API}/complaints/{photo_id}/feedback", headers=HC, json={"rating": 5}, timeout=30)
    check("feedback rejected while the complaint is open again", r.status_code == 409, str(r.status_code))
    if mail_ok:
        n_r = wait_mail("officer.roads@synapse.local", 1)
        check("roads admin emailed about the reopen", n_r >= 1, f"{n_r} mails")
        # The resolve reason was English; the Tamil-speaking citizen's status mail must carry it in Tamil.
        found = None
        for _ in range(45):
            msgs = requests.get(f"{MAIL}/api/v1/messages?limit=60", timeout=10).json()["messages"]
            for m in msgs:
                if any("citizen@synapse.local" == (t.get("Address") or "").lower() for t in m["To"]) and d["tracking_id"] in (m.get("Subject") or ""):
                    text = requests.get(f"{MAIL}/api/v1/message/{m['ID']}", timeout=10).json()["Text"]
                    if "resolved" in (m.get("Subject") or "") and "Pothole filled" not in text and re.search(r"[\u0B80-\u0BFF]", text):
                        found = text
                        break
            if found:
                break
            time.sleep(2)
        check("officer note translated into Tamil in the status mail", found is not None, (found or "")[:80])

    if H_new:
        here = {"lat": 11.0183, "lng": 76.9674}  # where the supporter stands: next to the water complaint
        r = requests.post(f"{API}/complaints/{water_id}/support", headers=H_new, json=here, timeout=30)
        check("another citizen supports the water complaint", r.status_code == 200 and r.json()["supporters"] == 1, r.text[:100])
        r = requests.post(f"{API}/complaints/{water_id}/support", headers=H_new, json=here, timeout=30)
        check("supporting twice does not double count", r.status_code == 200 and r.json()["supporters"] == 1)
        r = requests.post(f"{API}/complaints/{water_id}/support", headers=HC, json=here, timeout=30)
        check("the complainant cannot support their own complaint", r.status_code == 400, str(r.status_code))
        nb = requests.get(f"{API}/complaints/nearby?lat=11.0183&lng=76.9674&limit=20", headers=H_new, timeout=30).json()
        mine = next((i for i in nb if i["id"] == water_id), None)
        check("nearby list shows the supported complaint without personal data", mine is not None and mine["supported"] is True and "raw_text" not in mine, f"{len(nb)} nearby")
        sl = requests.get(f"{API}/complaints/supported", headers=H_new, timeout=30).json()
        check("supported list for the citizen", any(i["id"] == water_id for i in sl))
        qi = next((i for i in requests.get(f"{API}/review/queue?view=all&q={water_tid}", headers=HA, timeout=30).json() if i["id"] == water_id), None)
        check("supporters visible in the queue", qi is not None and qi.get("supporters") == 1)

    mp = requests.get(f"{API}/admin/map?view=all", headers=HA, timeout=30).json()
    check("map lists located complaints in scope", any(pt["id"] == water_id for pt in mp) and all("lat" in pt and "lng" in pt for pt in mp), f"{len(mp)} points")
    mp_roads = requests.get(f"{API}/admin/map?view=all", headers=HO_roads, timeout=30).json()
    check("map scoped for a department admin", all(pt["department"] == "roads" for pt in mp_roads), f"{len(mp_roads)} points")
    m2 = requests.get(f"{API}/admin/metrics", headers=HA, timeout=30).json()["totals"]
    check("metrics carry rating, reopen rate and supporters", "avg_rating" in m2 and "reopen_rate" in m2 and "supporters" in m2, json.dumps({k: m2.get(k) for k in ("avg_rating", "reopen_rate", "supporters")}))

    codes = [requests.post(f"{API}/auth/login", json={"email": "ratelimit.test@synapse.local", "password": "nope-Nope-1!"}, timeout=30).status_code for _ in range(12)]
    check("login rate limit after repeated failures", 429 in codes and codes[0] == 401, str(codes))

    print("\n== staff accounts and districts ==")
    stamp2 = str(int(time.time()))[-7:]
    r = requests.post(f"{API}/admin/users", headers=HA, json={"role": "district_admin", "district": "Madurai", "full_name": "Madurai Admin", "email": f"district.madurai.{stamp2}@synapse.local", "mobile": "8" + stamp2 + "01", "preferred_language": "ta"}, timeout=30)
    check("super admin creates a district admin", r.status_code == 201 and r.json()["user"]["role"] == "district_admin" and bool(r.json()["password"]), r.text[:120])
    HD = login(f"district.madurai.{stamp2}@synapse.local", r.json()["password"]) if r.status_code == 201 else HA
    r = requests.post(f"{API}/admin/users", headers=HD, json={"role": "district_admin", "district": "Chennai", "full_name": "Chennai Admin", "email": "x@synapse.local", "mobile": "9000000099"}, timeout=30)
    check("district admin cannot create another district admin", r.status_code == 403, str(r.status_code))
    r = requests.post(f"{API}/admin/users", headers=HD, json={"role": "dept_admin", "department_id": "water", "full_name": "Madurai Water Admin", "email": f"water.madurai.{stamp2}@synapse.local", "mobile": "8" + stamp2 + "02"}, timeout=30)
    check("district admin creates a department admin in own district", r.status_code == 201 and r.json()["user"]["district"] == "Madurai" and r.json()["user"]["department_id"] == "water", r.text[:120])
    if r.status_code == 201:
        new_id = r.json()["user"]["id"]
        HW = login(f"water.madurai.{stamp2}@synapse.local", r.json()["password"])
        mq = requests.get(f"{API}/review/queue?view=all", headers=HW, timeout=30).json()
        check("new department admin sees no Coimbatore complaints", mq == [], f"{len(mq)} items")
        r = requests.patch(f"{API}/admin/users/{new_id}", headers=HD, json={"is_active": False}, timeout=30)
        check("district admin can disable its department admin", r.status_code == 200 and r.json()["is_active"] is False, r.text[:100])
        r = requests.get(f"{API}/review/queue", headers=HW, timeout=30)
        check("disabled account is locked out", r.status_code in (401, 403), str(r.status_code))
    r = requests.get(f"{API}/admin/users", headers=HO_roads, timeout=30)
    check("department admin cannot list staff", r.status_code == 403, str(r.status_code))
    ds = requests.get(f"{API}/admin/districts", headers=HA, timeout=30).json()
    check("38 Tamil Nadu districts listed", len(ds) == 38, str(len(ds)))

    print("\n== admin ==")
    m = requests.get(f"{API}/admin/metrics", headers=HA, timeout=30).json()
    check("metrics: totals, by status, live accuracy", "totals" in m and "by_status" in m and "live_accuracy_by_language" in m, json.dumps(m["totals"])[:120])
    check("metrics: auto-closed is zero", m["totals"].get("auto_closed") == 0)
    t = requests.post(f"{API}/admin/rules/test", headers=HA, json={"text": "gas leak near school, தெருவிளக்கு வேலை செய்யவில்லை"}, timeout=30).json()
    check("rules test endpoint matches R1 and R5b", "R1" in t["matched"] and "R5b" in t["matched"] and t["urgency_floor"] == "critical", str(t["matched"]))
    t = requests.post(f"{API}/admin/rules/test", headers=HA, json={"text": "எங்கள் தெருவில் ஒரு குழந்தை கிணற்றில் விழுந்துவிட்டது, உடனே வாருங்கள்"}, timeout=30).json()
    check("rules test: child fallen into a well -> fire and safety, critical, human review", "R11" in t["matched"] and t.get("department") == "safety" and t.get("urgency_floor") == "critical" and bool(t.get("force_review")), str(t)[:120])
    t = requests.post(f"{API}/admin/rules/test", headers=HA, json={"text": "ghar ke andar saanp ghus gaya hai, bachche dar rahe hain"}, timeout=30).json()
    check("rules test: snake inside the house -> fire and safety", "R12" in t["matched"] and t.get("department") == "safety", str(t)[:120])
    t = requests.post(f"{API}/admin/rules/test", headers=HA, json={"text": "the borewell in our street is not working for a week, no water supply"}, timeout=30).json()
    check("rules test: a broken borewell stays a water complaint", "R11" not in t["matched"] and t.get("department") == "water", str(t)[:120])
    r = requests.put(f"{API}/admin/rules", headers=HA, json={"yaml": "rules: notalist"}, timeout=30)
    check("invalid rules YAML rejected", r.status_code == 400)
    r = requests.put(f"{API}/admin/rules", headers=HO_roads, json={"yaml": "rules: []"}, timeout=30)
    check("officer cannot edit rules", r.status_code == 403)
    r = requests.post(f"{API}/admin/models/reload", headers=HA, timeout=30)
    check("model reload endpoint", r.status_code == 200)

    print("\n== fixes from the A-to-Z pass (16 Oct) ==")
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(1)</script></svg>'
    r = requests.post(f"{API}/complaints", headers=HC, data={"text": "pothole photo attached, please check the road"}, files=[("files", ("x.svg", svg, "image/svg+xml"))], timeout=60)
    check("an SVG photo is refused (it can carry script)", r.status_code == 400, f"{r.status_code} {r.text[:80]}")
    r = requests.post(f"{API}/complaints", headers=HC, data={"text": "pothole photo attached, please check the road"}, files=[("files", ("x.png", b"plain text, not a picture", "image/png"))], timeout=60)
    check("a text file declared as PNG is refused (file signature checked)", r.status_code == 400, f"{r.status_code} {r.text[:80]}")
    for text, rid, label in (("எங்கள் தெருவில் குப்பை ஒரு வாரமாக எடுக்கவில்லை, பிரச்சனையை உடனே தீர்க்கவும்", "R4", "Tamil 'please solve' is not the fire rule"),
                             ("मेरे घर के आगे सड़क पर बड़ा गड्ढा है, आपसे आग्रह है कि ठीक करें", "R4", "Hindi 'in front of' / 'request' are not the fire rule"),
                             ("एक नागरिक होने के नाते शिकायत: स्ट्रीट लाइट बंद है", "R12", "Hindi 'citizen' is not the cobra rule")):
        t = requests.post(f"{API}/admin/rules/test", headers=HA, json={"text": text}, timeout=30).json()
        check(f"rules test: {label}", rid not in t["matched"], str(t["matched"]))
    t = requests.post(f"{API}/admin/rules/test", headers=HA, json={"text": "வீட்டில் தீ பிடித்தது, தீயில் பொருட்கள் எரிகின்றன"}, timeout=30).json()
    check("rules test: a real Tamil fire still matches the fire rule", "R4" in t["matched"] and t.get("department") == "safety", str(t["matched"]))
    tamil_addr = submit(HC, "எங்கள் தெருவில் மூன்று நாட்களாக குடிநீர் வரவில்லை", manual_address="கோயம்புத்தூர், காந்திபுரம் 5வது தெரு", location_source="manual")
    nowhere = submit(HC, "Garbage dumped near the park for a week, please clear it", lat=28.6139, lng=77.2090, location_source="browser")  # Delhi
    for acc in (tamil_addr, nowhere):
        wait_analysed(HC, acc["id"])
    d = requests.get(f"{API}/review/{tamil_addr['id']}", headers=HA, timeout=30).json()
    check("address typed in Tamil script resolves to its district, office and due time", d.get("district") == "Coimbatore" and bool(d.get("office_name")) and bool(d.get("due_at")), f"{d.get('district')} / {d.get('office_name')}")
    d = requests.get(f"{API}/review/{nowhere['id']}", headers=HA, timeout=30).json()
    reasons = " ".join((d.get("decision") or {}).get("reasons") or [])
    check("a complaint with no district goes to review with a due time (not routed into nobody's queue)",
          d.get("district") is None and d.get("status") == "under_review" and "district unknown" in reasons and bool(d.get("due_at")), f"{d.get('status')} / {d.get('district')} / {d.get('resolved_place')}")

    print("\n== fixes for the medium bugs (16 Oct) ==")
    # Filed first so the worker analyses it while the checks below run: a JPEG header with nothing readable behind it.
    unreadable = submit(HC, "The street light pole near the bus stand is bent and hanging over the road, photo attached", lat=11.0168, lng=76.9558,
                        location_source="browser", files=[("files", ("pole.jpg", b"\xff\xd8\xff\xe0" + b"not really a jpeg " * 60, "image/jpeg"))])
    mine = lambda: len(requests.get(f"{API}/complaints/mine", headers=HC, timeout=30).json())
    before = mine()
    codes = [requests.post(f"{API}/complaints", headers=HC, data={"text": "Garbage dumped near the park for a week, please clear it", "location_source": "browser", **ll}, timeout=30).status_code
             for ll in ({"lat": 999, "lng": 76.96}, {"lat": 11.0, "lng": 181}, {"lat": "nan", "lng": 76.96}, {"lat": 11.0})]
    check("coordinates off the globe, NaN or half a pair refused at intake (400), nothing stored", codes == [400] * 4 and mine() == before, f"{codes}, {mine() - before} stored")
    r = requests.post(f"{API}/complaints", headers=HC, data={"text": "pothole photos attached, please check the road"},
                      files=[("files", (f"p{i}.jpg", img, "image/jpeg")) for i in range(7)], timeout=60)
    r6 = requests.post(f"{API}/review/{water_id}/attachments", headers=HA, files=[("files", (f"after{i}.jpg", img, "image/jpeg")) for i in range(6)], timeout=60)
    check("seven files in one request refused (400) and nothing stored, six accepted", r.status_code == 400 and mine() == before and r6.status_code == 200 and r6.json().get("attachments") == 6,
          f"{r.status_code} {r.json().get('detail', '')[:50]} / six: {r6.status_code}")

    decide = lambda cid, action, **extra: requests.post(f"{API}/review/{cid}/decision", headers=HA, json={"action": action, "reason": "status machine check", **extra}, timeout=30)
    benches = ids[cases[2][0]]  # closed above; the duplicate is merged and the photo complaint is in progress again after the citizen's reopen
    codes = [decide(benches, "request_info").status_code, decide(ids["dup"], "reassign", department="roads").status_code, decide(photo_id, "reopen").status_code]
    check("request info on a closed case, reassign on a merged one, staff reopen of an in-progress one: all refused (409)", codes == [409, 409, 409], str(codes))
    r = decide(benches, "reopen")
    check("staff reopen of a closed case still allowed", r.status_code == 200 and r.json()["status"] == "under_review", r.text[:80])
    gas = ids[cases[3][0]]
    decide(gas, "resolve")
    codes = sorted(r.status_code for r in at_once(lambda: decide(gas, "close"), 2))
    tl = requests.get(f"{API}/complaints/{gas}/timeline", headers=HC, timeout=30).json()
    check("two simultaneous closes: one succeeds, the other gets 409, one closed entry", codes == [200, 409] and [e["to_status"] for e in tl].count("closed") == 1, str(codes))

    if H_new:
        res = at_once(lambda: requests.post(f"{API}/complaints/{ids['pii']}/support", headers=H_new, json={"lat": 11.03, "lng": 76.945}, timeout=30), 4)
        d = requests.get(f"{API}/review/{ids['pii']}", headers=HA, timeout=30).json()
        backed = [e for e in d["timeline"] if (e["note"] or "").startswith("supported by")]
        check("four simultaneous supports by one citizen: all answered, counted once", [r.status_code for r in res] == [200] * 4 and d["supporters"] == 1 and len(backed) == 1,
              f"{[r.status_code for r in res]} supporters={d['supporters']} events={len(backed)}")

    wait_analysed(HC, unreadable["id"])
    d = requests.get(f"{API}/review/{unreadable['id']}", headers=HA, timeout=30).json()
    a, reasons = d.get("analysis") or {}, (d.get("decision") or {}).get("reasons") or []
    check("a photo the model cannot decode: analysed from the text alone with a note, photo kept",
          bool(a.get("department")) and bool(a.get("urgency")) and any(r.startswith("photo could not be read") for r in reasons)
          and not any(r.startswith("awaiting analysis") for r in reasons) and len(d["media"]) == 1, f"{a.get('department')}/{a.get('urgency')} {reasons[:1]}")

    print("\n== fixes for the low-severity bugs (16 Oct) ==")
    near_km = float(env("NEARBY_KM", "2.0"))
    # 13: me-too support is for citizens, sent from near the complaint (the photo complaint sits at its EXIF point in Gandhipuram).
    r = requests.post(f"{API}/complaints/{photo_id}/support", headers=HO_water, json={"lat": 11.0183, "lng": 76.9675}, timeout=30)
    check("staff cannot add me-too support (403)", r.status_code == 403, f"{r.status_code} {r.text[:60]}")
    if H_new:
        none = requests.post(f"{API}/complaints/{photo_id}/support", headers=H_new, timeout=30)
        far = requests.post(f"{API}/complaints/{photo_id}/support", headers=H_new, json={"lat": 13.0827, "lng": 80.2707}, timeout=30)  # Chennai
        near = requests.post(f"{API}/complaints/{photo_id}/support", headers=H_new, json={"lat": 11.0273, "lng": 76.9675}, timeout=30)  # 1 km north
        check("support needs the citizen's location (400), refused from another city (403), counted from 1 km away",
              none.status_code == 400 and far.status_code == 403 and near.status_code == 200 and near.json()["supporters"] == 1,
              f"{none.status_code} {far.status_code} {near.status_code} {near.text[:60]}")

    # 14: a reviewer's accept on a routed case is refused; the department admin's starts the work.
    routed_before = [e["to_status"] for e in requests.get(f"{API}/complaints/{water_id}/timeline", headers=HC, timeout=30).json()].count("routed")
    r = decide(water_id, "accept")
    routed_after = [e["to_status"] for e in requests.get(f"{API}/complaints/{water_id}/timeline", headers=HC, timeout=30).json()].count("routed")
    check("reviewer accept on an already routed case refused (409), no second Routed entry", r.status_code == 409 and routed_after == routed_before, f"{r.status_code} routed entries {routed_before} -> {routed_after}")
    r = requests.post(f"{API}/review/{water_id}/decision", headers=HO_water, json={"action": "accept", "reason": "repair team on the way"}, timeout=30)
    check("department admin's accept on a routed case starts the work", r.status_code == 200 and r.json()["status"] == "in_progress", r.text[:80])

    # 15: the nearby list never reaches past NEARBY_KM or 20 items, whatever the caller asks for.
    r = requests.get(f"{API}/complaints/nearby?lat=11.0183&lng=76.9674&km=100000&limit=1000", headers=HA, timeout=30)
    nb = r.json() if r.status_code == 200 else []
    check(f"nearby with km=100000 and limit=1000 stays within {near_km:g} km and 20 items (the Delhi complaint is not listed)",
          r.status_code == 200 and len(nb) <= 20 and all(i["distance_km"] <= near_km for i in nb) and not any(i["id"] == nowhere["id"] for i in nb),
          f"{r.status_code}, {len(nb)} items, max {max([i['distance_km'] for i in nb], default=0)} km")
    codes = [requests.get(f"{API}/complaints/nearby?{q}", headers=HA, timeout=30).status_code for q in ("lat=11.0&lng=76.9&km=0", "lat=999&lng=76.9")]
    check("nearby refuses a zero radius or a latitude off the globe (422)", codes == [422, 422], str(codes))

    # 16: a maximum complaint length.
    before = mine()
    long_text = "Garbage has not been collected on our street for two weeks and it smells. " * 70  # 5,179 characters
    r = requests.post(f"{API}/complaints", headers=HC, data={"text": long_text, "location_source": "none"}, timeout=30)
    check("a complaint over 5,000 characters refused (400), nothing stored", r.status_code == 400 and mine() == before, f"{r.status_code} {r.text[:70]}")

    # 17: no account enumeration through verify-otp, reset or the tracking-ID lookup.
    ghost = f"nobody.{stamp}@synapse.local"
    real_email = new_email if mail_ok else "citizen@synapse.local"
    wrong = "000000"
    if mail_ok:  # a live reset code for the real account, so its wrong-code answer is compared with the unknown address
        seen = mail_count(new_email)
        requests.post(f"{API}/auth/forgot", json={"email": new_email}, timeout=60)
        wrong = "000000" if latest_otp(new_email, seen) != "000000" else "111111"
    real_v = requests.post(f"{API}/auth/verify-otp", json={"email": "citizen@synapse.local", "code": wrong}, timeout=30)
    ghost_v = requests.post(f"{API}/auth/verify-otp", json={"email": ghost, "code": wrong}, timeout=30)
    real_r = requests.post(f"{API}/auth/reset", json={"email": real_email, "code": wrong, "new_password": "Another@12345"}, timeout=30)
    ghost_r = requests.post(f"{API}/auth/reset", json={"email": ghost, "code": wrong, "new_password": "Another@12345"}, timeout=30)
    check("verify-otp and reset: an unknown email gets the same 400 and message as a wrong code for a real account",
          ghost_v.status_code == real_v.status_code == 400 and ghost_v.json() == real_v.json() and ghost_r.status_code == real_r.status_code == 400 and ghost_r.json() == real_r.json(),
          f"{ghost_v.status_code} {ghost_v.json().get('detail')} / {ghost_r.status_code} {ghost_r.json().get('detail')}")
    if H_new:
        other = requests.get(f"{API}/complaints/track/{water_tid}", headers=H_new, timeout=30)
        missing = requests.get(f"{API}/complaints/track/SYN-2026-999999", headers=H_new, timeout=30)
        outside = requests.get(f"{API}/complaints/track/{water_tid}", headers=HO_roads, timeout=30)
        own = requests.get(f"{API}/complaints/track/{water_tid}", headers=HC, timeout=30)
        check("tracking-ID lookup: another citizen's or another department's complaint answers 404 like a missing one; the owner gets it",
              other.status_code == missing.status_code == outside.status_code == 404 and other.json() == missing.json() and own.status_code == 200,
              f"{other.status_code} {missing.status_code} {outside.status_code} {own.status_code}")

    # 18: /health details only for staff or a caller on the API's own machine.
    proxied = {"X-Forwarded-For": "203.0.113.9"}  # as if from another machine through a proxy
    h_pub = requests.get(f"{API}/health", headers=proxied, timeout=20).json()
    h_cit = requests.get(f"{API}/health", headers={**proxied, **HC}, timeout=20).json()
    h_staff = requests.get(f"{API}/health", headers={**proxied, **HA}, timeout=20).json()
    check("/health from outside answers only the status, also to a citizen; staff get the details",
          h_pub == {"status": "ok"} and h_cit == {"status": "ok"} and {"queue_depth", "outbox_pending", "model_latency_ms", "models"} <= set(h_staff),
          f"{h_pub} {h_cit} staff keys {sorted(h_staff)[:6]}")

    # 22: a routine old-age pension complaint is not an at-risk case; elderly residents and sick children still are.
    got = {}
    for text in ("Old age pension not received for three months, please check my application",
                 "बुजुर्ग पेंशन तीन महीने से नहीं मिली", "முதியவர் உதவித்தொகை மூன்று மாதமாக வரவில்லை",
                 "No water for three days in our street, elderly residents are struggling", "kids are sick after drinking the tap water"):
        t = requests.post(f"{API}/admin/rules/test", headers=HA, json={"text": text}, timeout=30).json()
        got[text[:22]] = sorted({"R10", "R10b"} & set(t["matched"]))
    check("rules test: an old-age pension complaint (English, Hindi, Tamil) matches no at-risk rule; elderly residents and sick children still do",
          list(got.values()) == [[], [], [], ["R10b"], ["R10"]], json.dumps(got, ensure_ascii=False))

    print("\n== error codes for the app's languages (16 Oct) ==")
    # Every refusal carries a stable code and its parameters next to the English detail; the app shows apiErrors.<code>
    # from the en / ta / hi files. FastAPI's own 422 list is unchanged.
    max_chars = int(env("MAX_COMPLAINT_CHARS", "5000"))
    r = requests.post(f"{API}/complaints", headers=HC, data={"text": "x" * (max_chars + 1), "location_source": "none"}, timeout=30)
    check("a refusal keeps its English message in detail and adds its code and parameters",
          r.status_code == 400 and r.json().get("detail") == f"Please keep the complaint to {max_chars} characters or fewer"
          and r.json().get("code") == "complaint_too_long" and r.json().get("params") == {"max": max_chars}, r.text[:120])
    r = decide(ids["dup"], "resolve")  # merged above: no decision is taken from merged
    check("a refused decision sends the action and the status as ids (the app shows its own labels)",
          r.status_code == 409 and r.json().get("code") == "decision_not_allowed" and r.json().get("params") == {"action": "resolve", "status": "merged"}, r.text[:120])
    r = requests.post(f"{API}/auth/register", json={"mobile": "9123456781", "email": f"codes.{stamp}@synapse.local", "password": "weakpass",
                                                   "full_name": "Code Check", "aadhaar_last4": "1234"}, timeout=30)
    check("a weak password: the missing rules as ids in the parameters, in words in the English message",
          r.status_code == 400 and r.json().get("code") == "password_weak" and r.json().get("params") == {"missing": ["uppercase", "digit", "symbol"]}
          and r.json().get("detail") == "Password needs an uppercase letter, a digit, a symbol", r.text[:120])
    if H_new:
        r = requests.post(f"{API}/complaints/{photo_id}/support", headers=H_new, json={"lat": 13.0827, "lng": 80.2707}, timeout=30)  # Chennai
        check("support from too far: the distance limit as a parameter", r.status_code == 403 and r.json().get("code") == "support_too_far"
              and r.json().get("params") == {"km": near_km}, r.text[:120])
    rl = [requests.post(f"{API}/auth/login", json={"email": f"codes.{stamp}@synapse.local", "password": "nope-Nope-1!"}, timeout=30) for _ in range(11)]
    check("a failed login and the rate limit carry their codes; the limit keeps its Retry-After header",
          rl[0].status_code == 401 and rl[0].json().get("code") == "login_failed" and rl[-1].status_code == 429
          and rl[-1].json().get("code") == "too_many_attempts" and rl[-1].headers.get("Retry-After", "").isdigit(),
          f"{rl[0].status_code} {rl[0].json().get('code')} / {rl[-1].status_code} {rl[-1].json().get('code')} Retry-After {rl[-1].headers.get('Retry-After')}")
    r = requests.get(f"{API}/complaints/nearby?lat=11.0&lng=76.9&km=0", headers=HA, timeout=30)
    check("validation errors keep FastAPI's 422 list in detail, without a code", r.status_code == 422 and isinstance(r.json().get("detail"), list) and "code" not in r.json(), r.text[:100])
    # Static: every code the backend raises is in errors.MESSAGES and has text in the three language files, which share
    # their keys and placeholders, and a translation only uses parameters the API sends with that code.
    sys.path.insert(0, str(ROOT))
    from backend.app.errors import MESSAGES

    app_dir = ROOT / "backend" / "app"
    raised = {c for p in app_dir.rglob("*.py") for c in re.findall(r'ApiError\(\s*\d{3},\s*"([a-z_]+)"', p.read_text(encoding="utf-8"))}
    bare = [p.name for p in app_dir.rglob("*.py") if "raise HTTPException(" in p.read_text(encoding="utf-8")]
    langs = {lang: flat(json.loads((ROOT / "frontend" / "src" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))) for lang in ("en", "ta", "hi")}
    holes = lambda text: sorted(set(re.findall(r"\{\{\s*(\w+)", text)))
    fields = lambda template: {f for _, f, _, _ in string.Formatter().parse(template) if f}
    problems = [f"raised but not in MESSAGES: {c}" for c in sorted(raised - set(MESSAGES))] + [f"raise HTTPException in {p}" for p in bare]
    problems += [f"keys of {lang}.json differ from en.json" for lang in ("ta", "hi") if set(langs[lang]) != set(langs["en"])]
    problems += [f"no {lang} text for {c}" for c in MESSAGES for lang in langs if not langs[lang].get(f"apiErrors.{c}")]
    problems += [f"apiErrors.{k[10:]} is not an API code" for k in langs["en"] if k.startswith("apiErrors.") and k[10:] not in MESSAGES]
    problems += [f"placeholders differ in {k}" for k in langs["en"] if not holes(langs["en"][k]) == holes(langs["ta"].get(k, "")) == holes(langs["hi"].get(k, ""))]
    problems += [f"apiErrors.{c} uses a parameter the API does not send" for c in MESSAGES if not set(holes(langs["en"].get(f"apiErrors.{c}", ""))) <= fields(MESSAGES[c])]
    check(f"every error code ({len(MESSAGES)}) has English, Tamil and Hindi text using the API's parameters; the three files share their {len(langs['en'])} keys",
          not problems, "; ".join(problems)[:200])

    print("\n== notifications ==")
    n = mail_count("citizen@synapse.local")
    check("status emails logged for the citizen in Mailpit", n >= 8, f"{n} emails") if mail_ok else None

    passed = sum(1 for r in results if r["ok"])
    print(f"\n{passed}/{len(results)} checks passed")
    out = ROOT / "data" / "eval" / "e2e_report.json"
    out.write_text(json.dumps({"passed": passed, "total": len(results), "results": results, "ids": ids}, indent=2, ensure_ascii=False), encoding="utf-8")
    print("report:", out)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
