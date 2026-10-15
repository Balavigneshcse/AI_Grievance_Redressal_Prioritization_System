"""Demo data for the jury review.

  python scripts/demo_data.py --reset           wipe every complaint (media, analyses, decisions, events,
                                                notifications) and the accounts created by the test suites
  python scripts/demo_data.py --staff           add district admins for Chennai and Madurai and a Chennai
                                                electricity department admin (password = SEED_PASSWORD)
  python scripts/demo_data.py --seed            file ten showcase complaints as the demo citizen through the
                                                API (the real pipeline runs), then act on a few as staff so
                                                every queue view has something in it
  python scripts/demo_data.py --reset --staff --seed     the full demo set in one go

--reset talks to Postgres directly; --staff and --seed need the API on :8000 with Ollama.
Seed accounts (backend/seed.py) are never removed.
"""
from __future__ import annotations

import argparse
import io
import shutil
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
API = "http://127.0.0.1:8000"


def env(key: str, default: str = "") -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return default


def login(email: str, password: str) -> dict:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def pothole_image() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 480), (122, 122, 118))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 290, 640, 480), fill=(95, 95, 92))
    d.ellipse((210, 230, 450, 360), fill=(32, 30, 28))
    d.ellipse((240, 250, 420, 340), fill=(18, 17, 16))
    d.line((0, 300, 640, 300), fill=(200, 200, 200), width=4)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


# text, location, extras   (location: GPS inside the geocoder's known districts, or an address)
SHOWCASE = [
    ("எங்கள் தெருவில் நான்கு நாட்களாக குடிநீர் வரவில்லை. வீட்டில் வயதான பெற்றோர் இருக்கிறார்கள், தண்ணீர் வாங்க பணம் இல்லை. காந்திபுரம் 5வது தெரு.",
     {"lat": 11.0183, "lng": 76.9674, "location_source": "browser"}, {}),
    ("अन्ना नगर में कल रात से बिजली नहीं है और ट्रांसफार्मर से चिंगारी निकल रही है। पास में स्कूल है, बहुत खतरनाक है।",
     {"lat": 13.0850, "lng": 80.2101, "location_source": "browser"}, {}),
    ("Deep pothole near the Meenakshi temple east gate. Two-wheelers are skidding every evening and an auto overturned yesterday.",
     {"lat": 9.9195, "lng": 78.1193, "location_source": "browser"}, {"photo": True}),
    ("Garbage 1 week ah edukkala Saibaba Colony 3rd street la, romba naatham varudhu, kids ku fever vandhuduchu. Please clear pannunga.",
     {"lat": 11.0255, "lng": 76.9460, "location_source": "browser"}, {}),
    ("Hamari gali ki street light 10 din se band hai, raat ko bahut andhera rehta hai aur ladies ko ghar aane me dar lagta hai. Fairlands, Salem.",
     {"lat": 11.6643, "lng": 78.1460, "location_source": "browser"}, {}),
    ("தெரு நாய்கள் கூட்டமாக சுற்றுகின்றன, நேற்று ஸ்ரீரங்கம் பள்ளி அருகே ஒரு குழந்தையை கடித்துவிட்டது. உடனே நடவடிக்கை எடுக்கவும்.",
     {"lat": 10.8627, "lng": 78.6964, "location_source": "browser"}, {}),
    ("Property tax for door no 45, Peelamedu was paid in June through the portal but the receipt still shows pending and I received a penalty notice.",
     {"manual_address": "Peelamedu, Coimbatore", "location_source": "manual"}, {}),
    ("கழிவுநீர் சாலையில் ஓடுகிறது, துர்நாற்றம் தாங்க முடியவில்லை, கொசுக்கள் அதிகம். ராம்நகர் 2வது தெரு, கோயம்புத்தூர்.",
     {"lat": 11.0070, "lng": 76.9660, "location_source": "browser"}, {}),
    ("A shop near Gandhipuram bus stand keeps gas cylinders on the footpath right next to a tea stall stove. Serious fire risk for the whole market.",
     {"lat": 11.0168, "lng": 76.9558, "location_source": "browser"}, {}),
    ("सरकारी अस्पताल के बाहर एक हफ्ते से गंदा पानी जमा है, मच्छर बहुत हो गए हैं और बच्चों को बुखार आ रहा है। गांधीपुरम।",
     {"lat": 11.0200, "lng": 76.9700, "location_source": "browser"}, {}),
]

STAFF = [
    ("district_admin", "Chennai", None, "Chennai District Admin", "district.chennai@synapse.local", "9000000006", "ta"),
    ("district_admin", "Madurai", None, "Madurai District Admin", "district.madurai@synapse.local", "9000000007", "ta"),
    ("dept_admin", "Chennai", "electricity", "Electricity Admin, Chennai", "officer.electricity.chennai@synapse.local", "9000000008", "hi"),
]


def reset() -> None:
    import psycopg

    url = env("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5434/synapse").replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        n = conn.execute("select count(*) from complaints").fetchone()[0]
        for sql in (
            "delete from overrides",
            "delete from decisions",
            "delete from analyses",
            "delete from status_events",
            "delete from notifications where complaint_id is not null",
            "delete from media",
            "delete from complaints",
            "delete from otps where user_id in (select id from users where email like 'e2e.%' or email like 'citizen.test%' or email like '%.madurai.%@synapse.local' or email = 'x@synapse.local')",
            "delete from notifications where user_id in (select id from users where email like 'e2e.%' or email like 'citizen.test%' or email like '%.madurai.%@synapse.local' or email = 'x@synapse.local')",
            "delete from users where email like 'e2e.%' or email like 'citizen.test%' or email like '%.madurai.%@synapse.local' or email = 'x@synapse.local'",
        ):
            conn.execute(sql)
        conn.commit()
    media = ROOT / env("MEDIA_DIR", "media")
    if media.exists():
        for child in media.iterdir():
            shutil.rmtree(child, ignore_errors=True)
    print(f"reset: removed {n} complaints, their media, and the test accounts")


def add_staff(pw: str) -> None:
    HA = login("admin@synapse.local", pw)
    for role, district, dept, name, email, mobile, lang in STAFF:
        body = {"role": role, "district": district, "department_id": dept, "full_name": name, "email": email, "mobile": mobile, "preferred_language": lang, "password": pw}
        r = requests.post(f"{API}/admin/users", headers=HA, json=body, timeout=30)
        print(f"staff {email}: {'created' if r.status_code == 201 else r.json().get('detail', r.status_code)}")


def seed(pw: str) -> None:
    HC = login("citizen@synapse.local", pw)
    ids = []
    for i, (text, loc, extra) in enumerate(SHOWCASE, 1):
        files = [("files", ("pothole.jpg", pothole_image(), "image/jpeg"))] if extra.get("photo") else None
        data = {"text": text, "complainant_name": "Demo Citizen", "aadhaar_last4": "4321", **loc}
        r = requests.post(f"{API}/complaints", headers=HC, data=data, files=files, timeout=120)
        if r.status_code != 202:
            print(f"[{i}] submit failed: {r.status_code} {r.text[:120]}")
            continue
        ids.append(r.json()["id"])
        print(f"[{i}] {r.json()['tracking_id']} queued")
    print("waiting for analysis", end="", flush=True)
    t0 = time.time()
    while time.time() - t0 < 900:
        pending = 0
        for cid in ids:
            d = requests.get(f"{API}/complaints/{cid}", headers=HC, timeout=30).json()
            if d["status"] in ("received", "analysing"):
                pending += 1
        if pending == 0:
            break
        print(".", end="", flush=True)
        time.sleep(5)
    print(f" done in {int(time.time() - t0)} s")
    for cid in ids:
        d = requests.get(f"{API}/complaints/{cid}", headers=HC, timeout=30).json()
        dep = d["department"]["id"] if d.get("department") else "-"
        print(f"  {d['tracking_id']}: {d['status']:<13} {dep:<12} {d.get('urgency') or '-':<9} {d.get('district') or '?'}")

    # A few staff actions so the queues show every state.
    HA = login("admin@synapse.local", pw)
    HW = login("officer.water@synapse.local", pw)
    detail = {cid: requests.get(f"{API}/complaints/{cid}", headers=HC, timeout=30).json() for cid in ids}
    water = [cid for cid, d in detail.items() if d.get("department", {}) and d["department"]["id"] == "water" and d["district"] == "Coimbatore" and d["status"] == "routed"]
    if water:
        requests.post(f"{API}/review/{water[0]}/decision", headers=HW, json={"action": "accept", "reason": "Tanker scheduled for this evening, repair team assigned"}, timeout=30)
        print("  water admin accepted one complaint -> in progress")
    reviews = [cid for cid, d in detail.items() if d["status"] == "under_review"]
    if reviews:
        requests.post(f"{API}/review/{reviews[0]}/decision", headers=HA, json={"action": "accept", "reason": "Routing confirmed after review"}, timeout=30)
        print("  super admin confirmed one reviewed complaint -> routed")
    if len(reviews) > 1:
        requests.post(f"{API}/review/{reviews[1]}/decision", headers=HA, json={"action": "request_info", "reason": "Please share the exact door number or a landmark"}, timeout=30)
        print("  super admin asked the citizen for a landmark -> awaiting info")
    routed = [cid for cid, d in detail.items() if d["status"] == "routed" and cid not in water[:1]]
    if routed:
        requests.post(f"{API}/review/{routed[-1]}/decision", headers=HA, json={"action": "resolve", "reason": "Work completed and verified on site"}, timeout=30)
        print("  super admin resolved one complaint")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--staff", action="store_true")
    ap.add_argument("--seed", action="store_true")
    args = ap.parse_args()
    if not (args.reset or args.staff or args.seed):
        ap.print_help()
        return
    pw = env("SEED_PASSWORD", "Synapse@123")
    if args.reset:
        reset()
    if args.staff:
        add_staff(pw)
    if args.seed:
        seed(pw)


if __name__ == "__main__":
    main()
