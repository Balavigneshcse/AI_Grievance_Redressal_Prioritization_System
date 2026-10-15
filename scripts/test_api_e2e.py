"""End-to-end test of the running API and the AI pipeline. Exercises every
feature built up to Checkpoint 4 against the live server:

  languages (Tamil script, Devanagari, Tanglish, Hinglish, English), urgency,
  rules (gas leak, oxygen, repeat, child), photo with EXIF GPS, duplicates,
  PII masking and role visibility, district office and due time, officer
  decisions (reassign, merge, request info, resolve, close), admin metrics,
  rules test and model reload, auth (wrong password, register with OTP,
  forgot/reset invalidating old tokens), media access control, email logging.

Needs: API on :8000, Postgres, Ollama with gemma3:4b and bge-m3, Mailpit on :8025
(SMTP_HOST=localhost in .env, so OTPs can be read back).

Run from the project root:  python scripts/test_api_e2e.py
Writes data/eval/e2e_report.json. Exit code 1 if any check fails.
"""
from __future__ import annotations

import io
import os
import json
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
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
        msgs = requests.get(f"{MAIL}/api/v1/messages?limit=50", timeout=10).json()["messages"]
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
    msgs = requests.get(f"{MAIL}/api/v1/messages?limit=200", timeout=10).json()["messages"]
    return sum(1 for m in msgs if any(email == (t.get("Address") or "").lower() for t in m["To"]))


def submit(H: dict, text: str, **fields) -> dict:
    files = fields.pop("files", None)
    fields.setdefault("complainant_name", "Demo Citizen")
    fields.setdefault("aadhaar_last4", "4321")
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
    r = requests.post(f"{API}/complaints", headers=HC, data={"text": "water not coming since morning in our street"}, timeout=60)
    check("complaint without name and Aadhaar digits rejected", r.status_code in (400, 422), str(r.status_code))

    mail_ok = env("SMTP_HOST", "localhost") == "localhost"
    stamp = int(time.time())
    new_email = f"e2e.{stamp}@synapse.local"
    new_mobile = "9" + str(stamp)[-9:]  # unique per run; mobiles are unique in the users table
    if mail_ok:
        r = requests.post(f"{API}/auth/register", json={"mobile": new_mobile, "email": new_email, "password": "Weak", "preferred_language": "hi"}, timeout=30)
        check("weak password rejected", r.status_code == 400, r.json().get("detail", "")[:60])
        r = requests.post(f"{API}/auth/register", json={"mobile": new_mobile, "email": new_email, "password": "Strong@12345", "preferred_language": "hi"}, timeout=60)
        check("register accepted", r.status_code == 201, r.text[:80] if r.status_code != 201 else "")
        r = requests.post(f"{API}/auth/login", json={"email": new_email, "password": "Strong@12345"}, timeout=30)
        check("login blocked until verified", r.status_code == 403)
        code = latest_otp(new_email)
        r = requests.post(f"{API}/auth/verify-otp", json={"email": new_email, "code": "000000" if code != "000000" else "111111"}, timeout=30)
        check("wrong OTP rejected", r.status_code == 400)
        r = requests.post(f"{API}/auth/verify-otp", json={"email": new_email, "code": code}, timeout=30)
        check("correct OTP verifies and logs in", r.status_code == 200)
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
        check(f"  complainant name and Aadhaar digits stored", d.get("complainant_name") == "Demo Citizen" and d.get("aadhaar_last4") == "4321")

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
    pii_text = "my aadhaar is 4321 8765 1234 and phone 9876501234, water bill wrong for house 12, Saibaba Colony"
    acc = submit(HC, pii_text, lat=11.03, lng=76.945, location_source="browser")
    d = wait_analysed(HC, acc["id"])
    ids["pii"] = acc["id"]
    off = requests.get(f"{API}/review/{acc['id']}", headers=HA, timeout=30).json()["analysis"]
    check("PII hidden from complainant", d["analysis"].get("pii_map") in (None, {}))
    check("PII masked and mapped for staff", off.get("pii_map") and any(k.startswith("[PHONE") for k in off["pii_map"]) and any(k.startswith("[AADHAAR") for k in off["pii_map"]) and "9876501234" not in (off.get("masked_text") or ""), str(list((off.get("pii_map") or {}).keys())))

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
        r = requests.post(f"{API}/complaints/{water_id}/support", headers=H_new, timeout=30)
        check("another citizen supports the water complaint", r.status_code == 200 and r.json()["supporters"] == 1, r.text[:100])
        r = requests.post(f"{API}/complaints/{water_id}/support", headers=H_new, timeout=30)
        check("supporting twice does not double count", r.status_code == 200 and r.json()["supporters"] == 1)
        r = requests.post(f"{API}/complaints/{water_id}/support", headers=HC, timeout=30)
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
    r = requests.put(f"{API}/admin/rules", headers=HA, json={"yaml": "rules: notalist"}, timeout=30)
    check("invalid rules YAML rejected", r.status_code == 400)
    r = requests.put(f"{API}/admin/rules", headers=HO_roads, json={"yaml": "rules: []"}, timeout=30)
    check("officer cannot edit rules", r.status_code == 403)
    r = requests.post(f"{API}/admin/models/reload", headers=HA, timeout=30)
    check("model reload endpoint", r.status_code == 200)

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
