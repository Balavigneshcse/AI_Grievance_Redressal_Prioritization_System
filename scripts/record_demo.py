"""Record the Vindex demo walkthrough as a video, then render it twice: with burned-in subtitles
and without. Every feature is driven through the real UI by Playwright in Chrome.

Needs, all local: the API on :8000 pointed at Mailpit (SMTP_HOST=localhost), the Vite app on :5173,
Mailpit on :8025, Ollama, and fresh demo data (python scripts/demo_data.py --reset --districts --staff --seed).
Playwright for Python with Google Chrome installed; ffmpeg comes from the imageio-ffmpeg package.

  python scripts/record_demo.py              record, then render docs/demo/vindex_demo.mp4,
                                             vindex_demo_subtitled.mp4 and vindex_demo.srt
  python scripts/record_demo.py --render     re-render the MP4s from the last recording only
  python scripts/record_demo.py --headed     watch the browser while it records
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "demo"
RAW = OUT / "raw"
APP = "http://localhost:5173"
API = "http://127.0.0.1:8000"
MAIL = "http://localhost:8025"
GPS = {"latitude": 11.0183, "longitude": 76.9674}  # Gandhipuram, Coimbatore
CITIZEN = {"full_name": "Priya Raman", "email": "priya.raman@synapse.local", "mobile": "9876501234",
           "aadhaar_last4": "5678", "password": "Demo@12345", "preferred_language": "ta"}
COMPLAINT = "Thanni 3 days ah varala Gandhipuram 5th street la. Veetla 2 kids vomiting, kudikka thanni illa. Please help seekiram."


def env(key: str, default: str = "") -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return default


SEED_PW = env("SEED_PASSWORD", "Synapse@123")


# ---------------------------------------------------------------- small helpers
def api_login(email: str, password: str) -> dict:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def mail_messages(to: str) -> list[dict]:
    msgs = requests.get(f"{MAIL}/api/v1/search", params={"query": f"to:{to}", "limit": 20}, timeout=10).json()["messages"]
    return [m for m in msgs if any(to == (t.get("Address") or "").lower() for t in m["To"])]


def otp_for(email: str, seen: int, timeout: float = 90) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout:
        msgs = mail_messages(email)
        if len(msgs) > seen:
            body = requests.get(f"{MAIL}/api/v1/message/{msgs[0]['ID']}", timeout=10).json()
            m = re.search(r"\b(\d{6})\b", body.get("Text") or body.get("HTML") or "")
            if m:
                return m.group(1)
        time.sleep(1.5)
    raise RuntimeError(f"no OTP mail for {email}")


def picture(kind: str) -> Path:
    """Evidence and proof photos drawn with PIL, so the recording needs no external files."""
    from PIL import Image, ImageDraw

    p = RAW / f"{kind}.jpg"
    img = Image.new("RGB", (960, 720), (118, 116, 110))
    d = ImageDraw.Draw(img)
    if kind == "evidence":  # a dry public tap on a street
        d.rectangle((0, 460, 960, 720), fill=(92, 90, 86))
        d.rectangle((400, 240, 470, 470), fill=(70, 70, 75))
        d.rectangle((470, 300, 560, 330), fill=(60, 60, 66))
        d.ellipse((520, 330, 600, 410), fill=(150, 140, 120))
        d.text((40, 40), "No water, day 3 - Gandhipuram 5th street", fill=(255, 255, 255))
    elif kind == "reply":  # the door number the office asked for
        d.rectangle((0, 0, 960, 720), fill=(176, 148, 110))
        d.rectangle((330, 160, 630, 720), fill=(96, 62, 36))
        d.rectangle((420, 230, 540, 300), fill=(230, 220, 200))
        d.text((445, 255), "No. 12", fill=(20, 20, 20))
        d.text((40, 40), "Door no 12, Gandhipuram 5th street", fill=(255, 255, 255))
    else:  # proof: water running from the repaired tap
        d.rectangle((0, 460, 960, 720), fill=(92, 90, 86))
        d.rectangle((400, 240, 470, 470), fill=(70, 70, 75))
        d.rectangle((470, 300, 560, 330), fill=(60, 60, 66))
        d.polygon([(540, 330), (560, 330), (585, 470), (515, 470)], fill=(120, 170, 220))
        d.ellipse((470, 440, 640, 500), fill=(110, 160, 210))
        d.text((40, 40), "Supply restored - repaired pipeline", fill=(255, 255, 255))
    img.save(p, "JPEG", quality=88)
    return p


def remove_demo_citizen() -> None:
    """Start from a blank slate for the citizen the video registers. Only works when the account has
    no complaints (run demo_data.py --reset first); otherwise the video logs in instead of registering."""
    import psycopg

    url = env("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5434/synapse").replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        try:
            uid = conn.execute("select id from users where email = %s", (CITIZEN["email"],)).fetchone()
            if uid:
                cids = [r[0] for r in conn.execute("select id from complaints where user_id = %s", (uid[0],)).fetchall()]
                if cids:  # a previous recording's complaint and everything hanging off it
                    for table in ("overrides", "decisions", "analyses", "status_events", "media", "supports", "notifications"):
                        try:
                            with conn.transaction():
                                conn.execute(f"delete from {table} where complaint_id = any(%s)", (cids,))
                        except Exception:
                            pass  # table without a complaint_id column
                    conn.execute("delete from complaints where id = any(%s)", (cids,))
                for sql in ("delete from supports where user_id = %s", "delete from otps where user_id = %s",
                            "delete from notifications where user_id = %s", "delete from users where id = %s"):
                    conn.execute(sql, (uid[0],))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print("demo citizen kept:", str(e)[:100])


# ---------------------------------------------------------------- the walkthrough
class Demo:
    def __init__(self, page, t0: float):
        self.page = page
        self.t0 = t0
        self.captions: list[tuple[float, str]] = []

    def cap(self, text: str, hold: float = 3.5) -> None:
        self.captions.append((time.monotonic() - self.t0, text))
        print(f"[{time.monotonic() - self.t0:6.1f}s] {text}")
        self.page.wait_for_timeout(int(hold * 1000))

    def wait(self, s: float) -> None:
        self.page.wait_for_timeout(int(s * 1000))

    def goto(self, path: str) -> None:
        self.page.goto(path if path.startswith("http") else APP + path)
        self.page.wait_for_load_state("networkidle")
        self.wait(0.8)

    def login(self, email: str, password: str, who: str) -> None:
        p = self.page
        if "/login" not in p.url:
            self.goto("/login")
        p.get_by_label("Email").fill(email)
        p.get_by_label("Password", exact=True).fill(password)
        self.cap(f"Logging in as the {who}.", 1.2)
        p.locator("form").get_by_role("button", name="Log in").click()  # the header has one too
        p.wait_for_url(lambda u: "/login" not in u, timeout=20000)
        self.wait(1)

    def logout(self) -> None:
        p = self.page
        p.get_by_role("button", name="Account", exact=True).click()
        p.get_by_role("menuitem", name="Log out").click()
        p.wait_for_url(lambda u: "/login" in u, timeout=15000)
        self.wait(0.6)

    def scroll(self, px: int, settle: float = 1.2) -> None:
        self.page.mouse.wheel(0, px)
        self.wait(settle)

    def pick(self, trigger, option: str) -> None:
        trigger.click()
        self.page.get_by_role("option", name=option).click()

    def decide(self, action: str, reason: str, via_more: bool = False) -> None:
        p = self.page
        if via_more:
            p.get_by_role("button", name="More").click()
            p.get_by_role("menuitem", name=action).click()
        else:
            p.get_by_role("button", name=action, exact=True).click()
        p.locator("#decision-reason").fill(reason)
        self.wait(1.2)
        p.get_by_role("dialog").get_by_role("button", name="Confirm").click()
        p.get_by_role("dialog").wait_for(state="hidden", timeout=20000)
        self.wait(1.5)

    # ------------------------------------------------------------ scenes
    def run(self) -> None:
        p = self.page
        seen = len(mail_messages(CITIZEN["email"]))

        # 1. Registration ------------------------------------------------------------------
        self.goto("/login")
        self.cap("Vindex: AI grievance triage for Tamil Nadu. Everything runs on one laptop, Gemma 3 on the local GPU, no cloud AI.", 4.5)
        p.get_by_role("link", name="Create an account").click()
        self.wait(1)
        self.cap("A citizen registers once: name, mobile, email and the last 4 Aadhaar digits. They go on every complaint; the AI never sees them.", 3)
        p.get_by_label("Full name").type(CITIZEN["full_name"], delay=40)
        p.get_by_label("Mobile number").type(CITIZEN["mobile"], delay=40)
        p.get_by_label("Email").type(CITIZEN["email"], delay=30)
        p.get_by_label("Aadhaar: last 4 digits").type(CITIZEN["aadhaar_last4"], delay=80)
        p.get_by_label("Password", exact=True).type(CITIZEN["password"], delay=40)
        self.pick(p.locator("#preferred_language"), "தமிழ்")
        self.cap("Preferred language Tamil: every email to this citizen will be in Tamil.", 2.5)
        registered = True
        with p.expect_response(lambda r: "/auth/register" in r.url) as resp:
            p.get_by_role("button", name="Register").click()
        if resp.value.status != 201:
            registered = False
            print("registration not accepted:", resp.value.status, resp.value.text()[:100])
        if registered:
            p.wait_for_url(lambda u: "/verify" in u, timeout=15000)
            self.cap("The 6-digit code goes out by email. For this demo the mail server is Mailpit, running on the same laptop.", 3)

            # 2. OTP mail ---------------------------------------------------------------------
            code = otp_for(CITIZEN["email"], seen)
            self.goto(MAIL)
            self.cap("Mailpit: the OTP mail, in Tamil, the citizen's preferred language.", 3.5)
            try:
                p.locator("a[href*='/view/'], .message").first.click(timeout=5000)
                self.wait(3)
            except Exception:
                pass
            self.goto(f"/verify?email={CITIZEN['email']}")
            otp = p.locator("#otp, input[autocomplete='one-time-code']").first
            otp.click()
            self.cap("Enter the code: the account is verified and the citizen is logged in.", 1)
            p.keyboard.type(code, delay=120)
            p.wait_for_url(lambda u: u.rstrip("/") == APP, timeout=20000)
        else:
            self.goto("/login")
            self.login(CITIZEN["email"], CITIZEN["password"], "citizen")
        self.wait(1.5)
        self.cap("My complaints: empty for a new citizen.", 2.5)

        # 3. New complaint ----------------------------------------------------------------
        p.get_by_role("button", name="New complaint").first.click()
        p.wait_for_url(lambda u: u.endswith("/new"), timeout=15000)
        self.wait(1)
        self.cap("The complaint form. 'Filing as' carries the name and Aadhaar digits from the account, never retyped.", 3.5)
        box = p.get_by_placeholder("Describe the issue: what, where, since when")
        box.click()
        self.cap("Any language, any script. This one is Tanglish: Tamil written in English letters.", 1)
        box.type(COMPLAINT, delay=28)
        self.wait(1.5)
        self.scroll(260)
        p.get_by_role("button", name="Camera / video").click()
        p.get_by_role("dialog").wait_for()
        self.wait(1.2)
        p.get_by_role("dialog").get_by_role("button", name="Video").click()
        self.cap("In-app camera: a photo, or a video of up to 5 minutes as evidence for the office. Here Chrome's test camera.", 2)
        p.get_by_role("button", name="Start recording").click()
        self.wait(4)
        p.get_by_role("button", name="Stop").click()
        p.get_by_role("dialog").wait_for(state="hidden", timeout=15000)
        self.wait(1.2)
        p.locator("input[type=file]").first.set_input_files(str(picture("evidence")))
        self.cap("A photo upload too. The vision model checks whether the picture matches the text.", 3)
        self.scroll(420)
        p.get_by_role("button", name="Use current location").click()
        p.get_by_text("km away").first.wait_for(timeout=20000)
        self.cap("GPS from the device, resolved offline to Gandhipuram, Coimbatore. No map API key, no cloud.", 3)
        self.scroll(380)
        self.cap("Open complaints nearby are listed: a neighbour can support one instead of filing a duplicate.", 3.5)
        self.scroll(600)
        with p.expect_response(lambda r: r.url.endswith("/complaints") and r.request.method == "POST") as resp:
            p.get_by_role("button", name="Submit complaint").click()
        created = resp.value.json()
        tid, cid = created["tracking_id"], created["id"]
        p.get_by_text("Complaint received").wait_for(timeout=30000)
        self.cap(f"Tracking ID {tid} in under a second. The analysis starts in the background.", 3.5)
        p.get_by_role("button", name="Track it").click()
        p.wait_for_url(lambda u: u.endswith(f"/c/{cid}"), timeout=15000)

        # 4. Tracking and AI analysis --------------------------------------------------------
        self.cap("Analysing: Gemma 3 4B on the laptop GPU reads the text and the photo. 12 to 20 seconds, fully local.", 2)
        H = api_login(CITIZEN["email"], CITIZEN["password"])
        t0 = time.time()
        while time.time() - t0 < 150:
            d = requests.get(f"{API}/complaints/{cid}", headers=H, timeout=30).json()
            if d["status"] not in ("received", "analysing"):
                break
            self.wait(2)
        self.wait(2.5)
        dept = (d.get("department") or {}).get("name_en") or "the department"
        urg = (d.get("urgency") or "").capitalize()
        self.cap(f"Result: {dept}, {urg}, language Tamil-English. Rules forced a human review because children are ill.", 4.5)
        self.scroll(420)
        self.cap("Evidence quoted from the original text, the rules that matched, the second-opinion classifier, the office and its due time.", 4.5)
        self.scroll(600)
        self.cap("The timeline: every step is a status event. The video and the photo are kept for the office.", 4)

        # 5. Citizen mails ------------------------------------------------------------------
        self.goto(MAIL)
        self.cap("Two mails already: the acknowledgement with the tracking ID, then 'under review'. Both in Tamil.", 4.5)

        # 6. District admin reviews ---------------------------------------------------------
        self.goto("/")
        self.logout()
        self.login("district.coimbatore@synapse.local", SEED_PW, "Coimbatore district admin")
        self.goto("/officer/queue")
        self.cap("The district admin's review queue: critical, low-confidence or disagreeing cases. Nothing closes without a human.", 4.5)
        p.locator("tr", has_text=tid).first.click()
        p.wait_for_url(lambda u: "/officer/c/" in u, timeout=15000)
        self.wait(1.5)
        self.cap("Staff see the masked text with the PII map, the model's reasoning, the second opinion and the evidence.", 4)
        self.scroll(500)
        self.wait(1.5)
        self.scroll(-500)
        p.get_by_role("button", name="Accept", exact=True).click()
        self.wait(2.5)
        self.cap("Accepted: routed to the Coimbatore water office with its SLA. The department admin is emailed.", 4)

        # 7. Department admin works the case ------------------------------------------------
        self.logout()
        self.login("officer.water@synapse.local", SEED_PW, "water department admin")
        self.goto("/officer/queue")
        p.get_by_role("tab", name="Active work").click()
        self.wait(1.5)
        self.cap("The water department admin sees only water complaints of Coimbatore, with due times.", 4)
        p.locator("tr", has_text=tid).first.click()
        p.wait_for_url(lambda u: "/officer/c/" in u, timeout=15000)
        self.wait(1.5)
        p.get_by_role("button", name="Start work", exact=True).click()
        self.wait(2)
        self.cap("Start work: status In progress. The bar only offers what the status allows.", 2.5)
        self.decide("Request info", "Please share the door number and the best time for the repair team to visit.")
        self.cap("Request info: the question is emailed to the citizen in Tamil and the case waits for the reply.", 4)
        officer_url = p.url

        # 8. Me-too support by another citizen ----------------------------------------------
        self.logout()
        self.login("citizen@synapse.local", SEED_PW, "second citizen, same street")
        self.goto("/new")
        self.scroll(700)
        p.get_by_role("button", name="Use current location").click()
        p.get_by_text("km away").first.wait_for(timeout=20000)
        self.scroll(400)
        self.cap("Same street, same problem: the nearby list shows Priya's complaint. One tap to support it instead of a duplicate.", 4)
        p.locator("li", has_text=tid).get_by_role("button", name="Support").click()
        self.wait(2.5)
        self.cap("Supporters raise the priority: at five, the urgency goes up one level and the queue flags it as popular.", 4)

        # 9. Citizen replies ----------------------------------------------------------------
        self.logout()
        self.login(CITIZEN["email"], CITIZEN["password"], "citizen")
        self.goto(f"/c/{cid}")
        self.cap("'The office needs more information': the question is shown on the tracking page.", 3.5)
        self.scroll(500)
        reply = p.get_by_placeholder("Your reply")
        reply.click()
        reply.type("Door no 12, Gandhipuram 5th street. Anytime after 4 pm.", delay=30)
        p.locator("input[type=file]").first.set_input_files(str(picture("reply")))
        self.wait(1)
        p.get_by_role("button", name="Send reply").click()
        self.wait(3)
        self.cap("Reply sent with a photo. It goes straight to the department and the case continues as In progress.", 4)

        # 10. Resolution with proof ---------------------------------------------------------
        self.logout()
        self.login("officer.water@synapse.local", SEED_PW, "water department admin")
        self.goto(officer_url)
        self.scroll(500)
        self.cap("Work done. The admin attaches a resolution photo as proof.", 2.5)
        p.locator("input[type=file]").first.set_input_files(str(picture("proof")))
        self.wait(3)
        self.scroll(-500)
        self.decide("Resolve", "Pipeline repaired and supply restored this morning. Thank you for the door number.", via_more=True)
        self.cap("Resolved with a note. The note is translated into Tamil for the citizen's status mail.", 4)

        # 11. Rating ------------------------------------------------------------------------
        self.logout()
        self.login(CITIZEN["email"], CITIZEN["password"], "citizen")
        self.goto(f"/c/{cid}")
        self.cap("The citizen sees the proof photo and closes the loop: rate it, or reopen if it is not fixed.", 3.5)
        self.scroll(500)
        p.get_by_role("radio", name="5").click()
        self.wait(1.2)
        p.get_by_role("button", name="Confirm it is fixed").click()
        self.wait(2.5)
        self.cap("Rated 5 of 5. 'Not fixed, reopen' would send it back to the department with a note.", 4)

        # 12. Super admin ---------------------------------------------------------------------
        self.logout()
        self.login("admin@synapse.local", SEED_PW, "super admin")
        self.goto("/officer/queue")
        p.get_by_role("tab", name="All complaints").click()
        self.wait(1.5)
        search = p.get_by_placeholder("Search tracking ID, name or words from the complaint")
        search.type("Priya", delay=60)
        self.wait(2.5)
        self.cap("Super admin: every district. Search by tracking ID, name or words from the complaint.", 3.5)
        search.fill("")
        self.wait(2)
        self.cap("The Overdue badge: a seeded case passed its due time and was escalated to the district admin by email.", 4)
        self.goto("/admin/map")
        self.wait(3)
        self.cap("District map: markers by urgency, a red ring for overdue, size grows with supporters.", 5)
        self.goto("/admin")
        self.cap("Staff and districts: a district admin for each of the 38 districts, department admins under them, complaints per district.", 4)
        self.scroll(500)
        self.wait(2)
        self.scroll(-500)
        p.get_by_role("button", name="Add account").first.click()
        dialog = p.get_by_role("dialog")
        dialog.wait_for()
        self.pick(dialog.locator("[aria-label='Role']"), "Department admin")
        self.pick(dialog.locator("[aria-label='District']"), "Chennai")
        self.pick(dialog.locator("[aria-label='Department']"), "Roads")
        dialog.locator("#staff-name").type("Chennai Roads Admin", delay=30)
        dialog.locator("#staff-email").type("officer.roads.chennai@synapse.local", delay=20)
        dialog.locator("#staff-mobile").type("9000000019", delay=40)
        self.cap("A new department admin for Chennai roads, created by the super admin.", 1.5)
        dialog.get_by_role("button", name="Add account").click()
        self.wait(3)
        self.cap("Created: the password is shown once and a welcome mail goes out. District admins can do the same for their district.", 4.5)
        self.goto("/admin/metrics")
        self.cap("Metrics: accuracy per language, ratings, reopen rate, model latency and live health.", 4)
        self.scroll(500)
        self.wait(3)
        self.goto("/admin/rules")
        self.cap("Rules win over the model and are editable without a redeploy. Paste a text to see which rules match.", 3)
        tester = p.get_by_placeholder("Paste a complaint text to see which rules match")
        tester.type("gas leak near the school, children inside", delay=30)
        p.get_by_role("button", name="Test", exact=True).click()
        self.wait(2.5)
        self.cap("Matched: gas leak forces Critical and a human review, whatever the model says.", 4)
        p.get_by_role("button", name="Reload classifier").click()
        self.wait(2.5)
        self.cap("The retrained second-opinion classifier reloads with one click.", 3)

        # 13. Tamil interface -----------------------------------------------------------------
        self.goto("/officer/queue")
        lang_button = p.locator("button:has(svg.lucide-languages)").first  # its label follows the UI language
        lang_button.click()
        p.get_by_role("menuitem", name="தமிழ்").click()
        self.wait(2)
        self.cap("The whole interface in Tamil, or Hindi, with one switch.", 4)
        lang_button.click()
        p.get_by_role("menuitem", name="English").click()
        self.wait(1)

        # 14. The mail trail ------------------------------------------------------------------
        self.goto(MAIL)
        self.cap("Every step mailed: the citizen, the department admin and the district admin. Status notes translated into Tamil.", 5)
        try:
            p.locator("a[href*='/view/'], .message").first.click(timeout=5000)
            self.wait(4)
        except Exception:
            pass

        # 15. Close -----------------------------------------------------------------------------
        self.goto("/officer/queue")
        self.cap("Vindex: 118 automated checks, Tamil, Hindi, English, Tanglish and Hinglish, every decision explained, nothing auto-closed.", 6)


# ---------------------------------------------------------------- recording and rendering
def srt_time(s: float) -> str:
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(captions: list[tuple[float, str]], path: Path, total: float) -> None:
    lines = []
    for i, (start, text) in enumerate(captions, 1):
        end = captions[i][0] - 0.2 if i < len(captions) else min(start + 7, total)
        lines += [str(i), f"{srt_time(start)} --> {srt_time(max(end, start + 1))}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def render(webm: Path) -> None:
    ff = ffmpeg_exe()
    base = ["-y", "-i", str(webm), "-r", "25", "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an"]
    subprocess.run([ff, *base, str(OUT / "vindex_demo.mp4")], check=True, cwd=OUT, capture_output=True)
    style = "FontName=Segoe UI,FontSize=15,PrimaryColour=&H00FFFFFF,BackColour=&H50000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=22,MarginL=40,MarginR=40,WrapStyle=0"
    subprocess.run([ff, *base[:3], "-vf", f"subtitles=vindex_demo.srt:force_style='{style}'", *base[3:], str(OUT / "vindex_demo_subtitled.mp4")],
                   check=True, cwd=OUT, capture_output=True)
    for f in ("vindex_demo.mp4", "vindex_demo_subtitled.mp4"):
        print(f"  {f}: {(OUT / f).stat().st_size // 1024 // 1024} MB")


def record(headed: bool) -> None:
    from playwright.sync_api import sync_playwright

    RAW.mkdir(parents=True, exist_ok=True)
    for old in RAW.glob("*.webm"):
        old.unlink()
    remove_demo_citizen()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=not headed,
                                     args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        context = browser.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(RAW),
                                      record_video_size={"width": 1280, "height": 720}, geolocation=GPS,
                                      permissions=["geolocation", "camera", "microphone"], locale="en-IN", timezone_id="Asia/Kolkata")
        page = context.new_page()
        page.set_default_timeout(20000)
        t0 = time.monotonic()
        demo = Demo(page, t0)
        try:
            demo.run()
        finally:
            total = time.monotonic() - t0
            video = page.video
            context.close()
            browser.close()
            webm = Path(video.path())
            write_srt(demo.captions, OUT / "vindex_demo.srt", total)
            (RAW / "captions.json").write_text(json.dumps([{"t": round(t, 1), "text": x} for t, x in demo.captions], ensure_ascii=False, indent=1), encoding="utf-8")
            shutil.move(str(webm), str(RAW / "vindex_demo.webm"))
            print(f"recorded {total:.0f} s, {len(demo.captions)} captions -> {RAW / 'vindex_demo.webm'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--render", action="store_true", help="only re-render the MP4s from the last recording")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.render:
        record(args.headed)
    print("rendering MP4s")
    render(RAW / "vindex_demo.webm")


if __name__ == "__main__":
    main()
