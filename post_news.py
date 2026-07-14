"""
TopTallyTales — evergreen "Did you know?" SPACE & SCIENCE fact Shorts.

Rotates through a curated pool of real, stable subjects (planets, stars,
phenomena, missions) — NO news, NO real people, NO fabrication risk. GPT writes
only true, well-established facts + an honest curiosity title. Each fact plays
over a relevant Pexels clip, with a colorful gradient fallback. Energetic neural
voice, perfectly synced, uploaded to YouTube.

Free stack: GPT + Pexels (free API) + edge-tts + Pillow + FFmpeg.

Env (secrets): OPENAI_API_KEY, PEXELS_API_KEY,
  YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN,
  (optional) GH_TOKEN + GITHUB_REPOSITORY for no-repeats.
"""

import os
import re
import json
import time
import base64
import asyncio
import subprocess
from datetime import datetime

import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont

# === CONFIG ===
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

GH_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("APPROVAL_TOKEN")
GH_REPO = os.environ.get("GITHUB_REPOSITORY")
POSTED_FILE = "posted_shorts.json"

BRAND = "TOP TALLY TALES"
VOICE = "en-US-AriaNeural"
SPEAKING_RATE = "+12%"
NUM_FACTS = 4

# Curated, evergreen space & science subjects — no news, no real people, no
# fabrication risk. The bot rotates through these and remembers what it posted.
SUBJECTS = [
    ("Black Holes", "black hole space"),
    ("The Sun", "sun solar"),
    ("Jupiter", "jupiter planet"),
    ("Saturn's Rings", "saturn planet"),
    ("Mars", "mars planet surface"),
    ("The Moon", "moon surface"),
    ("Neutron Stars", "star space"),
    ("The Milky Way", "galaxy milky way"),
    ("Supernovae", "supernova nebula"),
    ("The International Space Station", "space station orbit"),
    ("Venus", "venus planet"),
    ("Mercury", "planet space"),
    ("Neptune", "neptune planet"),
    ("Uranus", "planet space"),
    ("Pluto", "dwarf planet space"),
    ("Comets", "comet space"),
    ("Asteroids", "asteroid space"),
    ("The James Webb Telescope", "telescope space stars"),
    ("The Hubble Telescope", "telescope galaxy"),
    ("Nebulae", "nebula space"),
    ("Galaxies", "galaxy space"),
    ("The Big Bang", "universe stars"),
    ("Dark Matter", "universe galaxy"),
    ("Solar Eclipses", "solar eclipse"),
    ("The Northern Lights", "aurora northern lights"),
    ("Meteor Showers", "meteor night sky"),
    ("The Voyager Probes", "spacecraft space"),
    ("Rockets", "rocket launch"),
    ("Astronauts", "astronaut space"),
    ("Zero Gravity", "astronaut floating space"),
    ("The Speed of Light", "light space stars"),
    ("Exoplanets", "planet space stars"),
    ("The Kuiper Belt", "space stars"),
    ("Solar Flares", "sun solar flare"),
    ("Gravity", "space planet orbit"),
    ("The Andromeda Galaxy", "galaxy space"),
    ("Cosmic Radiation", "space stars universe"),
    ("Star Formation", "nebula stars"),
    ("Red Dwarfs", "star space"),
    ("White Dwarfs", "star space"),
    ("The Oort Cloud", "comet space"),
    ("Space Junk", "satellite earth orbit"),
    ("Satellites", "satellite orbit earth"),
    ("The Aurora on Other Planets", "aurora planet"),
    ("Titan (Saturn's Moon)", "moon space"),
    ("Europa (Jupiter's Moon)", "moon ice space"),
    ("The Sun's Corona", "sun corona"),
    ("Wormholes", "space time universe"),
    ("The Expanding Universe", "universe galaxy"),
    ("Quasars", "galaxy space"),
    ("Pulsars", "star space"),
    ("Cosmic Dust", "nebula space"),
    ("The Habitable Zone", "planet space"),
    ("Space Suits", "astronaut spacesuit"),
    ("Mars Rovers", "mars rover"),
    ("The Kármán Line", "earth atmosphere space"),
    ("Gas Giants", "jupiter planet"),
    ("Ice Giants", "neptune planet"),
    ("Solar Wind", "sun solar"),
    ("The Life Cycle of Stars", "stars nebula"),
]

W, H = 1080, 1920
FPS = 30
GAP = 0.28
TAIL = 0.6

VOICE_OUT = "voice.mp3"
VIDEO_OUT = "short.mp4"
CARD_DIR = "cards"
CLIP_DIR = "clips"

WHITE = (255, 255, 255, 255)
YELLOW = (255, 235, 120, 255)
PALETTE = [  # gradient fallback + number-badge accents
    ((104, 58, 183), (38, 16, 84)),
    ((33, 118, 214), (12, 40, 96)),
    ((0, 150, 136), (0, 55, 66)),
    ((233, 106, 20), (96, 30, 8)),
    ((214, 51, 132), (78, 12, 58)),
    ((46, 160, 90), (12, 58, 34)),
]


# ---------- Fonts / text ----------
def _font(size, bold=True):
    for p in ("oswald.ttf", "Oswald.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    base = "/usr/share/fonts/truetype/dejavu/"
    try:
        return ImageFont.truetype(base + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), size)
    except Exception:
        return ImageFont.load_default()


def _shadow_text(draw, xy, text, font, fill):
    x, y = xy
    draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 180))
    draw.text((x, y), text, font=font, fill=fill)


def _wrap(draw, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _center_shadow(draw, y, text, font, fill, maxw):
    for ln in _wrap(draw, text, font, maxw):
        lw = draw.textlength(ln, font=font)
        _shadow_text(draw, ((W - lw) / 2, y), ln, font, fill)
        y += font.size + 14
    return y


def _clean_html(t):
    return " ".join(re.sub(r"<[^>]+>", "", t or "").split())


def _clean_title(t):
    return re.sub(r"\s+-\s+[^-]+$", "", t or "").strip()


# ---------- Gradients / scrim ----------
def _vgrad_rgb(top, bottom):
    g = Image.new("RGB", (1, H))
    for y in range(H):
        f = y / (H - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * f) for i in range(3)))
    return g.resize((W, H))


def _vgrad_rgba(top, bottom):
    g = Image.new("RGBA", (1, H))
    for y in range(H):
        f = y / (H - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * f) for i in range(4)))
    return g.resize((W, H))


def _scrim():
    """Semi-dark overlay so white text stays readable over any footage."""
    base = Image.new("RGBA", (W, H), (0, 0, 0, 105))
    base = Image.alpha_composite(base, _vgrad_rgba((0, 0, 0, 40), (0, 0, 0, 170)))
    return base


# ---------- Pick next space subject (rotates, no repeats) ----------
def pick_subject(posted_keys):
    import random
    remaining = [(name, q) for (name, q) in SUBJECTS
                 if _subject_key(name) not in posted_keys]
    pool = remaining if remaining else SUBJECTS  # if all used, start over
    name, base_query = random.choice(pool)
    print(f"🪐 Subject: {name}")
    return {"topic": name, "topic_query": base_query, "key": _subject_key(name)}


def _subject_key(name):
    return " ".join(re.findall(r"[a-z0-9]+", name.lower())[:4])


# ---------- History ----------
def _gh_headers():
    return {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json"}


def load_posted():
    if not GH_TOKEN or not GH_REPO:
        return [], None
    try:
        owner, repo = GH_REPO.split("/")
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{POSTED_FILE}"
        r = requests.get(url, headers=_gh_headers())
        if r.status_code == 200:
            d = r.json()
            return json.loads(base64.b64decode(d["content"]).decode()), d["sha"]
    except Exception as e:
        print(f"⚠️ history load failed: {e}")
    return [], None


def save_posted(links, sha):
    if not GH_TOKEN or not GH_REPO:
        return
    try:
        owner, repo = GH_REPO.split("/")
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{POSTED_FILE}"
        content = base64.b64encode(json.dumps(links[-300:], indent=2).encode()).decode()
        payload = {"message": "Update posted shorts", "content": content}
        if sha:
            payload["sha"] = sha
        requests.put(url, headers=_gh_headers(), json=payload)
    except Exception as e:
        print(f"⚠️ history save failed: {e}")


# ---------- GPT: honest space facts + visual search terms ----------
def make_facts(subject):
    print("🤖 Generating facts...")
    topic = subject["topic"]
    base_q = subject["topic_query"]
    fb = {"topic": topic, "topic_query": base_q,
          "hook": f"Here's what makes {topic} incredible.",
          "facts": [f"{topic} is one of the most fascinating things in the universe."],
          "queries": [base_q],
          "title": f"Mind-Blowing Facts About {topic} #Shorts"}
    if not OPENAI_API_KEY:
        return fb
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": [
                {"role": "system", "content": (
                    "You make accurate, engaging 'Did you know?' space & science fact Shorts. "
                    "CRITICAL: every fact must be TRUE and well-established science — never invent, exaggerate, "
                    "or state anything uncertain as fact. If unsure, choose a safer, well-known fact. "
                    "Respond ONLY with valid JSON: "
                    '{"hook":"...","facts":["..."],"queries":["..."],"title":"..."}. '
                    "hook: one spoken scroll-stopping sentence about the subject (no greetings). "
                    f"facts: EXACTLY {NUM_FACTS} short, punchy, TRUE sentences (max ~16 words each), "
                    "each a genuinely surprising well-established fact about the subject. "
                    f'queries: EXACTLY {NUM_FACTS} items (parallel to facts); each a 1-2 word concrete space '
                    "stock-video search term (e.g. 'galaxy', 'nebula', 'planet', 'rocket', 'stars'). "
                    "title: honest, curiosity-driven YouTube Short title under 90 chars that matches the facts, "
                    "ending with #Shorts. Do NOT sensationalise or mislead. "
                    "No emojis/hashtags inside hook/facts, no URLs."
                )},
                {"role": "user", "content": f"Subject: {topic}"},
            ]},
            timeout=45,
        )
        if r.status_code == 200:
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()
            d = json.loads(raw)
            facts = [str(x).strip() for x in d.get("facts", []) if str(x).strip()][:NUM_FACTS]
            queries = [str(x).strip() for x in d.get("queries", [])][:NUM_FACTS]
            if d.get("hook") and len(facts) >= 3 and d.get("title"):
                while len(queries) < len(facts):
                    queries.append(base_q)
                return {"topic": topic, "topic_query": base_q, "hook": d["hook"],
                        "facts": facts, "queries": queries, "title": d["title"]}
        print(f"⚠️ Facts JSON off ({r.status_code}); fallback.")
    except Exception as e:
        print(f"⚠️ Facts failed ({e}); fallback.")
    return fb


# ---------- Pexels footage ----------
def pexels_clip(query, out_path):
    if not PEXELS_API_KEY or not query:
        return None
    try:
        r = requests.get("https://api.pexels.com/videos/search",
                         headers={"Authorization": PEXELS_API_KEY},
                         params={"query": query, "orientation": "portrait",
                                 "per_page": 5, "size": "medium"}, timeout=25)
        if r.status_code != 200:
            print(f"   ⚠️ Pexels {query}: HTTP {r.status_code}")
            return None
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", [])
                     if f.get("file_type") == "video/mp4" and f.get("link")]
            if not files:
                continue
            files.sort(key=lambda f: abs((f.get("height") or 0) - 1920))
            link = files[0]["link"]
            data = requests.get(link, timeout=90)
            if data.status_code == 200 and data.content:
                with open(out_path, "wb") as fh:
                    fh.write(data.content)
                print(f"   🎬 clip for '{query}'")
                return out_path
    except Exception as e:
        print(f"   ⚠️ Pexels {query}: {e}")
    return None


# ---------- Overlays (transparent text layers) ----------
def _fit_font(draw, text, maxw, start, min_size=44):
    """Largest font (from start size) that fits text on ONE line within maxw."""
    size = start
    while size > min_size:
        f = _font(size)
        if draw.textlength(text, font=f) <= maxw:
            return f
        size -= 4
    return _font(min_size)


def make_hook_overlay(topic, path):
    ov = _scrim()
    draw = ImageDraw.Draw(ov)
    _shadow_text(draw, (44, 70), BRAND, _font(42), WHITE)
    margin = 80
    maxw = W - margin * 2
    kf = _font(56)
    # topic auto-fits width (single line), wrapping only if still too long at min size
    tf = _fit_font(draw, topic.upper(), maxw, 140, min_size=60)
    topic_lines = _wrap(draw, topic.upper(), tf, maxw)
    sf = _fit_font(draw, f"{NUM_FACTS} FACTS THAT WILL SURPRISE YOU", maxw, 52, min_size=34)
    block = kf.size + 40 + (tf.size + 12) * len(topic_lines) + 40 + sf.size
    y = (H - block) // 2
    kw = draw.textlength("DID YOU KNOW?", font=kf)
    _shadow_text(draw, ((W - kw) / 2, y), "DID YOU KNOW?", kf, YELLOW)
    y += kf.size + 40
    y = _center_shadow(draw, y, topic.upper(), tf, WHITE, maxw)
    y += 26
    sub = f"{NUM_FACTS} FACTS THAT WILL SURPRISE YOU"
    sw = draw.textlength(sub, font=sf)
    _shadow_text(draw, ((W - sw) / 2, y), sub, sf, WHITE)
    ov.save(path)
    return path


def make_fact_overlay(n, total, fact, path, accent):
    ov = _scrim()
    draw = ImageDraw.Draw(ov)
    _shadow_text(draw, (44, 70), BRAND, _font(42), WHITE)
    r = 92
    cx, cy = W // 2, 470
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(accent[0], accent[1], accent[2], 255))
    nf = _font(100)
    ns = str(n)
    nw = draw.textlength(ns, font=nf)
    draw.text((cx - nw / 2, cy - nf.size / 2 - 8), ns, font=nf, fill=WHITE)
    ff = _font(82)
    y = cy + r + 80
    for ln in _wrap(draw, fact, ff, W - 160):
        lw = draw.textlength(ln, font=ff)
        _shadow_text(draw, ((W - lw) / 2, y), ln, ff, WHITE)
        y += ff.size + 16
    # progress dots
    dot, gp = 20, 34
    tw = total * dot + (total - 1) * gp
    x = (W - tw) // 2
    for i in range(total):
        draw.ellipse([x, H - 150, x + dot, H - 150 + dot],
                     fill=YELLOW if i < n else (255, 255, 255, 150))
        x += dot + gp
    ov.save(path)
    return path


def make_outro_overlay(path):
    ov = _scrim()
    draw = ImageDraw.Draw(ov)
    _shadow_text(draw, (44, 70), BRAND, _font(42), WHITE)
    bf, sf = _font(120), _font(50)
    lines = _wrap(draw, "FOLLOW FOR MORE", bf, W - 120)
    block = (bf.size + 10) * len(lines) + 40 + sf.size
    y = (H - block) // 2
    y = _center_shadow(draw, y, "FOLLOW FOR MORE", bf, WHITE, W - 120)
    y += 24
    sub = "MIND-BLOWING FACTS DAILY"
    sw = draw.textlength(sub, font=sf)
    _shadow_text(draw, ((W - sw) / 2, y), sub, sf, YELLOW)
    ov.save(path)
    return path


# ---------- Voice ----------
async def _synth(text, path):
    await edge_tts.Communicate(text, VOICE, rate=SPEAKING_RATE).save(path)


def audio_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", path],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except Exception:
        return 4.0


def build_narration(segment_texts):
    print(f"🎙️ Synthesizing {len(segment_texts)} segments...")
    seg_files, durs = [], []
    for i, t in enumerate(segment_texts):
        p = f"seg_{i}.mp3"
        asyncio.run(_synth(t, p))
        seg_files.append(p)
        durs.append(audio_duration(p))
    for name, dur in (("sil.mp3", GAP), ("tail.mp3", TAIL)):
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                        "-t", str(dur), "-ar", "24000", "-ac", "1", "-b:a", "48k", name],
                       check=True, capture_output=True)
    order = []
    for i, sf in enumerate(seg_files):
        order.append(sf)
        order.append("sil.mp3" if i < len(seg_files) - 1 else "tail.mp3")
    with open("audio_list.txt", "w") as f:
        for p in order:
            f.write(f"file '{p}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "audio_list.txt",
                    "-c", "copy", VOICE_OUT], check=True, capture_output=True)
    card_durations = [d + (GAP if i < len(durs) - 1 else TAIL) for i, d in enumerate(durs)]
    print(f"✅ Narration {sum(card_durations):.1f}s")
    return VOICE_OUT, card_durations


# ---------- Build one clip: footage (or gradient) + text overlay ----------
def build_clip(bg_video, gradient_png, overlay_png, duration, out_path):
    if bg_video and os.path.exists(bg_video):
        vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
              "crop=1080:1920,setsar=1,eq=brightness=-0.06[bg];"
              "[bg][1:v]overlay=0:0,format=yuv420p[v]")
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", bg_video, "-i", overlay_png,
               "-filter_complex", vf, "-map", "[v]", "-an", "-r", str(FPS),
               "-t", f"{duration:.3f}", "-preset", "veryfast", out_path]
    else:
        vf = "[0:v][1:v]overlay=0:0,format=yuv420p[v]"
        cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{duration:.3f}", "-i", gradient_png,
               "-i", overlay_png, "-filter_complex", vf, "-map", "[v]", "-an",
               "-r", str(FPS), "-preset", "veryfast", out_path]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def assemble(clips, audio, out):
    with open("video_list.txt", "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "video_list.txt",
                    "-c", "copy", "silent.mp4"], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-i", "silent.mp4", "-i", audio,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "192k", "-shortest", out], check=True, capture_output=True)
    print(f"✅ {out}")
    return out


# ---------- YouTube ----------
def upload_to_youtube(video_path, title, description, topic="Space"):
    print("📤 Uploading to YouTube...")
    if not YOUTUBE_REFRESH_TOKEN or not YOUTUBE_CLIENT_ID:
        print("❌ YouTube credentials not configured!")
        return False
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        creds = Credentials(None, refresh_token=YOUTUBE_REFRESH_TOKEN,
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET)
        yt = build("youtube", "v3", credentials=creds)
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        tags = [topic, "space", "astronomy", "science", "space facts",
                "universe", "did you know", "shorts"]
        req = yt.videos().insert(
            part="snippet,status",
            body={"snippet": {"title": title[:100], "description": description[:4900],
                              "categoryId": "27",  # Education
                              "tags": tags},
                  "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}},
            media_body=media)
        resp = req.execute()
        print(f"✅ Uploaded: https://youtu.be/{resp['id']}")
        return True
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return False


# ---------- Main ----------
def main():
    print("🚀 TopTallyTales — Did You Know Shorts (with footage)")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    os.makedirs(CARD_DIR, exist_ok=True)
    os.makedirs(CLIP_DIR, exist_ok=True)

    posted, sha = load_posted()
    posted_keys = set(posted)

    subject = pick_subject(posted_keys)
    data = make_facts(subject)
    topic, hook, facts, queries = data["topic"], data["hook"], data["facts"], data["queries"]

    segments = [hook] + facts + ["Follow for more space facts every day."]
    voice, durations = build_narration(segments)

    # Segment plan: (overlay, gradient_color, search_query)
    plan = [("hook", PALETTE[0], data.get("topic_query", topic))]
    for i, fact in enumerate(facts):
        plan.append((f"fact_{i}", PALETTE[(i + 1) % len(PALETTE)], queries[i] if i < len(queries) else data["topic_query"]))
    plan.append(("outro", PALETTE[(len(facts) + 1) % len(PALETTE)], data.get("topic_query", topic)))

    clips = []
    for idx, (name, color, query) in enumerate(plan):
        overlay = os.path.join(CARD_DIR, f"{name}.png")
        if name == "hook":
            make_hook_overlay(topic, overlay)
        elif name == "outro":
            make_outro_overlay(overlay)
        else:
            fnum = int(name.split("_")[1])
            make_fact_overlay(fnum + 1, len(facts), facts[fnum], overlay, color[0])

        gradient = os.path.join(CARD_DIR, f"{name}_grad.png")
        _vgrad_rgb(color[0], color[1]).save(gradient)

        bg = (pexels_clip(query, os.path.join(CLIP_DIR, f"{name}.mp4"))
              or pexels_clip("space", os.path.join(CLIP_DIR, f"{name}.mp4")))
        clip = build_clip(bg, gradient, overlay, durations[idx], f"clip_{idx}.mp4")
        clips.append(clip)

    assemble(clips, voice, VIDEO_OUT)

    # Niche-specific tags + honest description
    topic_tag = "#" + re.sub(r"[^A-Za-z0-9]", "", topic)
    description = (f"{hook}\n\n"
                   f"{topic_tag} #space #astronomy #science #spacefacts #universe #Shorts")
    ok = upload_to_youtube(VIDEO_OUT, data["title"], description, topic)

    if ok:
        posted.append(subject["key"])
        save_posted(posted, sha)


if __name__ == "__main__":
    main()
