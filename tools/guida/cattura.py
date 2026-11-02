"""Crea immagini e video della Guida dal programma vero, con i dati di esempio.

Requisiti: backend avviato con i dati di esempio (MONGO_URL=mock://, appena riavviato) su http://localhost:8001,
frontend compilato e servito su http://localhost:3000, Playwright con Chromium, ffmpeg.

    python tools/guida/cattura.py                 # tutte le guide
    python tools/guida/cattura.py estratti carte  # solo alcune (per id)

Il testo delle guide è in frontend/src/guide/guides.json: ogni passo dice dove andare ("do") e cosa evidenziare
("highlight"). Lo script salva le immagini in frontend/public/guida/, monta i video (una scena per passo con la
didascalia) e scrive frontend/src/guide/media.json. Dopo una modifica all'interfaccia basta rilanciarlo.
"""
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ROOT / "frontend" / "src" / "guide" / "guides.json"
MEDIA = ROOT / "frontend" / "src" / "guide" / "media.json"
OUT = ROOT / "frontend" / "public" / "guida"
EXAMPLES = ROOT / "esempi"
BASE = "http://localhost:3000"
API = "http://localhost:8001/api"
USERS = {"titolare": "titolare@demo.it", "amministrazione": "amministrazione@demo.it", "commercialista": "commercialista@demo.it"}
PASSWORD = os.environ["DEMO_PASSWORD"]
W, H = 1280, 720
ACCENT = "#E8772E"

CAPTION_JS = """([label, title, text]) => {
  const d = document.createElement('div');
  d.id = '__guide_caption';
  d.style.cssText = 'position:fixed;left:24px;right:24px;bottom:20px;z-index:2147483647;background:rgba(21,23,28,.94);color:#fff;' +
    'border-radius:14px;padding:16px 22px;font:16px/1.45 Inter,system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.35)';
  d.innerHTML = '<div style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#F4A36B;font-weight:700;margin-bottom:4px">' +
    label + '</div><div style="font-size:19px;font-weight:700;margin-bottom:4px">' + title + '</div><div>' + text + '</div>';
  document.body.appendChild(d);
}"""

TITLE_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;width:{w}px;height:{h}px;display:flex;flex-direction:column;justify-content:center;padding:0 110px;box-sizing:border-box;
background:#15171C;color:#fff;font-family:Inter,system-ui,sans-serif}}
.k{{color:#F4A36B;font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:18px}}
h1{{font-size:52px;line-height:1.1;margin:18px 0 18px;letter-spacing:-.02em}}
p{{font-size:24px;color:#C3C8D2;margin:0;max-width:900px;line-height:1.4}}
.b{{position:absolute;left:110px;bottom:60px;color:#8A90A0;font-size:18px}}
</style></head><body><div class="k">Guida · {section}</div><h1>{title}</h1><p>{summary}</p><div class="b">Tesoreria di gruppo</div></body></html>"""


def log(msg):
    print(msg, flush=True)


def login(page, who):
    page.goto(BASE + "/login")
    page.evaluate("localStorage.clear()")
    page.goto(BASE + "/login")
    page.fill("#email", USERS[who])
    page.fill("#password", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_url(BASE + "/", timeout=15000)
    page.wait_for_timeout(800)


def company_id(page, name):
    token = page.evaluate("localStorage.getItem('tesoreria_token')")
    req = urllib.request.Request(f"{API}/companies", headers={"Authorization": f"Bearer {token}"})
    return next(c["id"] for c in json.load(urllib.request.urlopen(req)) if c["name"] == name)


def run_action(page, a, who):
    if "goto" in a:
        page.goto(BASE + a["goto"])
        page.wait_for_load_state("networkidle")
    elif "company" in a:
        sel = page.locator("#company-picker")
        if sel.count():
            sel.select_option(label=a["company"])
            page.wait_for_load_state("networkidle")
    elif "company_page" in a:
        page.goto(f"{BASE}/aziende/{company_id(page, a['company_page'])}")
        page.wait_for_load_state("networkidle")
    elif "click" in a:
        page.locator(a["click"]).first.click(timeout=8000)
    elif "fill" in a:
        page.locator(a["fill"][0]).first.fill(a["fill"][1], timeout=8000)
    elif "select" in a:
        page.locator(a["select"][0]).first.select_option(label=a["select"][1], timeout=8000)
    elif "upload" in a:
        with page.expect_file_chooser(timeout=8000) as fc:
            page.locator(a["upload"][0]).first.click()
        fc.value.set_files(str(EXAMPLES / a["upload"][1]))
        page.wait_for_timeout(1500)
    elif "key" in a:
        page.keyboard.press(a["key"])
    elif "scroll" in a:
        page.locator(a["scroll"]).first.scroll_into_view_if_needed(timeout=8000)
    elif "wait" in a:
        page.wait_for_timeout(a["wait"])
    elif "logout" in a:
        page.evaluate("localStorage.clear()")
    elif "login" in a:
        login(page, a["login"])
    page.wait_for_timeout(500)


def highlight(page, selector):
    if not selector:
        return None
    loc = page.locator(selector).first
    try:
        loc.wait_for(state="visible", timeout=5000)
        loc.evaluate("el => el.scrollIntoView({block: 'center', inline: 'nearest'})")
        page.wait_for_timeout(300)
        loc.evaluate(f"""el => {{ el.dataset.guideOld = el.style.cssText;
            el.style.outline = '3px solid {ACCENT}'; el.style.outlineOffset = '3px';
            el.style.boxShadow = '0 0 0 9px rgba(232,119,46,.22)'; }}""")
        return loc
    except PWTimeout:
        log(f"   ! da evidenziare non trovato: {selector}")
        return None


def scene(frames: list[tuple[Path, float]], out: Path, tmp: Path):
    """Un file per scena (immagine ferma con dissolvenza), poi unione senza ricodifica."""
    parts = []
    for n, (img, dur) in enumerate(frames):
        part = tmp / f"part{n:02d}.mp4"
        tmp_out = tmp / f"part{n:02d}.tmp.mp4"
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x15171C,"
              f"format=yuv420p,loop=-1:1,trim=duration={dur:.2f},fade=t=in:st=0:d=0.35,fade=t=out:st={dur - 0.35:.2f}:d=0.35")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-i", str(img), "-vf", vf, "-r", "30",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p", str(tmp_out)], check=True)
        tmp_out.rename(part)
        parts.append(part)
    listing = tmp / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    tmp_final = out.with_name(out.stem + ".tmp.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
                    "-movflags", "+faststart", str(tmp_final)], check=True)
    tmp_final.replace(out)
    return sum(d for _, d in frames)


def main():
    data = json.loads(GUIDES.read_text(encoding="utf-8"))
    only = set(sys.argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    media = json.loads(MEDIA.read_text()) if MEDIA.exists() and only else {"images": {}, "videos": {}}
    sections = {s["id"]: s["title"] for s in data["sections"]}
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for g in data["guides"]:
            if only and g["id"] not in only:
                continue
            log(f"== {g['id']}")
            ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, locale="it-IT")
            page = ctx.new_page()
            who = g.get("user", "titolare")
            login(page, who)
            tmp = Path(tempfile.mkdtemp(prefix=f"guida-{g['id']}-"))
            frames = []
            if g.get("video"):
                page.set_content(TITLE_HTML.format(w=W, h=H, section=html.escape(sections[g["section"]]), title=html.escape(g["title"]),
                                                   summary=html.escape(g["summary"])))
                t = tmp / "title.jpg"
                page.screenshot(path=str(t), type="jpeg", quality=92)
                frames.append((t, 3.5))
                page.goto(BASE + "/")
            for i, s in enumerate(g["steps"], start=1):
                key = f"{g['id']}-{i}"
                try:
                    for a in s.get("do", []):
                        run_action(page, a, who)
                    page.wait_for_timeout(700)
                except Exception as e:  # noqa: BLE001 - si continua con i passi successivi
                    problems.append(f"{key}: {str(e).splitlines()[0]}")
                    log(f"   ! passo {i}: {str(e).splitlines()[0]}")
                loc = highlight(page, s.get("highlight"))
                img = OUT / f"{key}.jpg"
                page.screenshot(path=str(img), type="jpeg", quality=80)
                media["images"][key] = img.name
                if g.get("video"):
                    page.evaluate(CAPTION_JS, [f"Passo {i} di {len(g['steps'])}", html.escape(s["title"]), html.escape(s["text"])])
                    f = tmp / f"{i:02d}.jpg"
                    page.screenshot(path=str(f), type="jpeg", quality=92)
                    page.evaluate("() => document.getElementById('__guide_caption')?.remove()")
                    frames.append((f, min(11.0, max(4.5, 2.5 + len(s["text"]) / 22))))
                if loc:
                    try:
                        loc.evaluate("el => { el.style.cssText = el.dataset.guideOld || ''; }")
                    except Exception:  # noqa: BLE001
                        pass
            if frames:
                out = OUT / f"{g['id']}.mp4"
                dur = scene(frames, out, tmp)
                media["videos"][g["id"]] = {"file": out.name, "duration": f"{int(dur // 60)}:{int(dur % 60):02d}"}
                log(f"   video {out.name} {dur:.0f}s")
            shutil.rmtree(tmp, ignore_errors=True)
            ctx.close()
        browser.close()
    MEDIA.write_text(json.dumps(media, indent=1, ensure_ascii=False))
    log(f"Fatto: {len(media['images'])} immagini, {len(media['videos'])} video.")
    if problems:
        log("Passi da controllare:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    main()
