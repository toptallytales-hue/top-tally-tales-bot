"""
TopTallyTales — long-form (3-4 min) 16:9 SPACE deep-dive.

Picks one space subject, GPT writes an accurate ~550-650 word narration split into
an intro + 4 chapters + outro. Each chapter has several beats, each beat over its own
relevant Pexels clip (landscape). Chapter title cards give rhythm. Neural voice,
perfectly synced, uploaded to the same channel as a regular (non-Short) video.

Reuses the same free stack: GPT + Pexels + edge-tts + Pillow + FFmpeg.

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
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# === CONFIG ===
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

GH_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("APPROVAL_TOKEN")
GH_REPO = os.environ.get("GITHUB_REPOSITORY")
POSTED_FILE = "posted_longform.json"

BRAND = "TOP TALLY TALES"
VOICE = "en-US-AriaNeural"
SPEAKING_RATE = "+6%"          # a touch calmer than Shorts for long-form
NUM_CHAPTERS = 4

W, H = 1920, 1080              # 16:9 landscape
FPS = 30
GAP = 0.30
TAIL = 0.8

VOICE_OUT = "voice.mp3"
VIDEO_OUT = "long.mp4"
CARD_DIR = "cards"
CLIP_DIR = "clips"

WHITE = (255, 255, 255, 255)
YELLOW = (255, 235, 120, 255)
PALETTE = [
    ((104, 58, 183), (24, 12, 60)),
    ((33, 118, 214), (10, 30, 72)),
    ((0, 150, 136), (0, 42, 52)),
    ((214, 51, 132), (60, 10, 46)),
    ((233, 106, 20), (72, 24, 8)),
    ((46, 160, 90), (10, 46, 28)),
]

# Curated space subjects (same spirit as the Shorts pool)
SUBJECTS = [
    ("Black Holes", "black hole"), ("The Sun", "sun"), ("Jupiter", "jupiter"),
    ("Saturn's Rings", "saturn"), ("Mars", "mars"), ("The Moon", "moon"),
    ("The Milky Way", "galaxy"), ("Neutron Stars", "neutron star"),
    ("Supernovae", "supernova"), ("The Big Bang", "universe"),
    ("Voyager Probes", "spacecraft"), ("The James Webb Telescope", "telescope"),
    ("Comets", "comet"), ("The International Space Station", "space station"),
    ("Exoplanets", "exoplanet"), ("Nebulae", "nebula"), ("Dark Matter", "galaxy"),
    ("The Kuiper Belt", "asteroid"), ("Pulsars", "pulsar"), ("The Andromeda Galaxy", "galaxy"),
    ("Mercury", "planet"), ("Venus", "planet"), ("Uranus", "planet"), ("Neptune", "planet"),
    ("Pluto", "pluto"), ("The Apollo Missions", "moon landing"), ("Solar Flares", "sun"),
    ("Auroras", "aurora"), ("Meteor Showers", "meteor"), ("The Oort Cloud", "space"),
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


def _shadow(draw, xy, text, font, fill):
    x, y = xy
    draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 190))
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
        payload = {"message": "Update posted longform", "content": content}
        if sha:
            payload["sha"] = sha
        requests.put(url, headers=_gh_headers(), json=payload)
    except Exception as e:
        print(f"⚠️ history save failed: {e}")


def pick_subject(posted_keys):
    import random
    remaining = [(n, q) for (n, q) in SUBJECTS if _subject_key(n) not in posted_keys]
    pool = remaining if remaining else SUBJECTS
    n, q = random.choice(pool)
    print(f"🪐 Subject: {n}")
    return {"topic": n, "topic_query": q, "key": _subject_key(n)}


# ---------- GPT: deep-dive script ----------
def generate_script(subject):
    print("🤖 Writing deep-dive script...")
    topic, base_q = subject["topic"], subject["topic_query"]
    fb = {
        "title": f"The Complete Story of {topic}",
        "intro": f"{topic} is one of the most fascinating subjects in all of space.",
        "chapters": [{
            "heading": topic,
            "beats": [{"say": f"{topic} continues to amaze scientists.", "query": base_q}],
        }],
        "outro": "Subscribe for more deep dives into space and science.",
    }
    if not OPENAI_API_KEY:
        return fb
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": [
                {"role": "system", "content": (
                    "You write accurate, engaging long-form YouTube narration about space & science. "
                    "CRITICAL: everything must be TRUE, well-established science — never invent, exaggerate, or "
                    "state anything uncertain as fact. If unsure, use a safer well-known point. "
                    "Write a 3-4 minute deep-dive (about 550-650 words total of spoken narration). "
                    "Open with a strong hook (no greetings). "
                    "Respond ONLY with valid JSON: "
                    '{"title":"...","intro":"...","chapters":[{"heading":"...","beats":[{"say":"...","query":"..."}]}],"outro":"..."}. '
                    f"chapters: EXACTLY {NUM_CHAPTERS}, each with a short heading (2-4 words) and 3-4 beats. "
                    "Each beat: say = one spoken sentence (max ~22 words); query = 1-2 word concrete space "
                    "stock-video term (e.g. 'galaxy','black hole','rocket','nebula'). "
                    "intro and outro are single spoken sentences. "
                    "title: honest, curiosity-driven, no #Shorts, no misleading claims. "
                    "No emojis/hashtags in narration, no URLs."
                )},
                {"role": "user", "content": f"Subject: {topic}"},
            ]},
            timeout=60,
        )
        if r.status_code == 200:
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()
            d = json.loads(raw)
            chapters = []
            for c in d.get("chapters", []):
                beats = []
                for b in c.get("beats", []):
                    say = str(b.get("say", "")).strip()
                    if say:
                        beats.append({"say": say, "query": str(b.get("query", base_q)).strip() or base_q})
                if beats and c.get("heading"):
                    chapters.append({"heading": str(c["heading"]).strip(), "beats": beats})
            if d.get("title") and d.get("intro") and len(chapters) >= 3 and d.get("outro"):
                print(f"✅ Script ready — {len(chapters)} chapters.")
                return {"title": d["title"].strip(), "intro": d["intro"].strip(),
                        "chapters": chapters[:NUM_CHAPTERS], "outro": d["outro"].strip()}
        print(f"⚠️ Script JSON off ({r.status_code}); fallback.")
    except Exception as e:
        print(f"⚠️ Script failed ({e}); fallback.")
    return fb


# ---------- Pexels (landscape) ----------
def pexels_clip(query, out_path):
    if not PEXELS_API_KEY or not query:
        return None
    try:
        r = requests.get("https://api.pexels.com/videos/search",
                         headers={"Authorization": PEXELS_API_KEY},
                         params={"query": query, "orientation": "landscape",
                                 "per_page": 6, "size": "medium"}, timeout=25)
        if r.status_code != 200:
            return None
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", [])
                     if f.get("file_type") == "video/mp4" and f.get("link")]
            if not files:
                continue
            files.sort(key=lambda f: abs((f.get("width") or 0) - 1920))
            data = requests.get(files[0]["link"], timeout=90)
            if data.status_code == 200 and data.content:
                with open(out_path, "wb") as fh:
                    fh.write(data.content)
                print(f"   🎬 clip for '{query}'")
                return out_path
    except Exception as e:
        print(f"   ⚠️ Pexels '{query}': {e}")
    return None


# ---------- Overlays ----------
def _scrim():
    base = Image.new("RGBA", (W, H), (0, 0, 0, 95))
    top = Image.new("RGBA", (1, H))
    for y in range(H):
        f = y / (H - 1)
        a = int(150 * f)  # darker at bottom
        top.putpixel((0, y), (0, 0, 0, a))
    return Image.alpha_composite(base, top.resize((W, H)))


def _vgrad_rgb(top, bottom):
    g = Image.new("RGB", (1, H))
    for y in range(H):
        f = y / (H - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * f) for i in range(3)))
    return g.resize((W, H))


def make_intro_overlay(topic, path):
    ov = _scrim()
    draw = ImageDraw.Draw(ov)
    _shadow(draw, (60, 54), BRAND, _font(44), WHITE)
    kf = _font(60)
    tf = _font(150)
    lines = _wrap(draw, topic.upper(), tf, W - 300)
    block = kf.size + 40 + (tf.size + 12) * len(lines)
    y = (H - block) // 2
    kw = draw.textlength("THE COMPLETE STORY OF", font=kf)
    _shadow(draw, ((W - kw) / 2, y), "THE COMPLETE STORY OF", kf, YELLOW)
    y += kf.size + 40
    for ln in lines:
        lw = draw.textlength(ln, font=tf)
        _shadow(draw, ((W - lw) / 2, y), ln, tf, WHITE)
        y += tf.size + 12
    ov.save(path)
    return path


def make_chapter_overlay(n, heading, path):
    ov = _scrim()
    draw = ImageDraw.Draw(ov)
    _shadow(draw, (60, 54), BRAND, _font(44), WHITE)
    cf = _font(56)
    hf = _font(120)
    lines = _wrap(draw, heading.upper(), hf, W - 240)
    block = cf.size + 30 + (hf.size + 10) * len(lines)
    y = (H - block) // 2
    label = f"CHAPTER {n}"
    lw = draw.textlength(label, font=cf)
    _shadow(draw, ((W - lw) / 2, y), label, cf, YELLOW)
    y += cf.size + 30
    for ln in lines:
        lww = draw.textlength(ln, font=hf)
        _shadow(draw, ((W - lww) / 2, y), ln, hf, WHITE)
        y += hf.size + 10
    ov.save(path)
    return path


def make_beat_overlay(text, path):
    """Lower-third caption for a narration beat."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # bottom gradient band for legibility
    band = Image.new("RGBA", (1, H))
    for y in range(H):
        f = y / (H - 1)
        a = int(210 * max(0, (f - 0.55) / 0.45)) if f > 0.55 else 0
        band.putpixel((0, y), (0, 0, 0, a))
    ov = Image.alpha_composite(ov, band.resize((W, H)))
    draw = ImageDraw.Draw(ov)
    _shadow(draw, (60, 54), BRAND, _font(40), WHITE)
    bf = _font(64)
    lines = _wrap(draw, text, bf, W - 260)[:3]
    line_h = bf.size + 14
    y = H - 150 - line_h * len(lines)
    draw.rounded_rectangle([130, y - 40, 130 + 110, y - 28], radius=6, fill=(214, 51, 132))
    for ln in lines:
        lw = draw.textlength(ln, font=bf)
        _shadow(draw, ((W - lw) / 2, y), ln, bf, WHITE)
        y += line_h
    ov.save(path)
    return path


def make_outro_overlay(path):
    ov = _scrim()
    draw = ImageDraw.Draw(ov)
    _shadow(draw, (60, 54), BRAND, _font(44), WHITE)
    bf, sf = _font(130), _font(56)
    lines = _wrap(draw, "SUBSCRIBE FOR MORE", bf, W - 240)
    block = (bf.size + 10) * len(lines) + 40 + sf.size
    y = (H - block) // 2
    for ln in lines:
        lw = draw.textlength(ln, font=bf)
        _shadow(draw, ((W - lw) / 2, y), ln, bf, WHITE)
        y += bf.size + 10
    y += 24
    sub = "SPACE & SCIENCE DEEP DIVES"
    sw = draw.textlength(sub, font=sf)
    _shadow(draw, ((W - sw) / 2, y), sub, sf, YELLOW)
    ov.save(path)
    return path


# ---------- Voice (per segment, synced) ----------
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
    print(f"✅ Narration {sum(card_durations):.0f}s total")
    return VOICE_OUT, card_durations


# ---------- Clip building ----------
def build_clip(bg_video, gradient_png, overlay_png, duration, out_path):
    if bg_video and os.path.exists(bg_video):
        vf = ("[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
              "crop=1920:1080,setsar=1,eq=brightness=-0.05[bg];"
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
def upload_to_youtube(video_path, title, description):
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
        req = yt.videos().insert(
            part="snippet,status",
            body={"snippet": {"title": title[:100], "description": description[:4900],
                              "categoryId": "27",  # Education
                              "tags": ["space", "astronomy", "science", "space documentary",
                                       "universe", "TopTallyTales"]},
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
    print("🚀 TopTallyTales — Long-form Space Deep-Dive")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    os.makedirs(CARD_DIR, exist_ok=True)
    os.makedirs(CLIP_DIR, exist_ok=True)

    posted, sha = load_posted()
    subject = pick_subject(set(posted))
    script = generate_script(subject)
    topic = subject["topic"]

    # Build the ordered segment list (text) and a parallel plan for cards/footage.
    segments = [script["intro"]]
    plan = [("intro", None, subject["topic_query"])]  # (kind, data, query)
    for ci, ch in enumerate(script["chapters"]):
        segments.append(f"Chapter {ci + 1}. {ch['heading']}.")
        plan.append(("chapter", (ci + 1, ch["heading"]), ch["beats"][0]["query"]))
        for b in ch["beats"]:
            segments.append(b["say"])
            plan.append(("beat", b["say"], b["query"]))
    segments.append(script["outro"])
    plan.append(("outro", None, "galaxy stars"))

    voice, durations = build_narration(segments)

    clips = []
    for idx, (kind, dat, query) in enumerate(plan):
        ov = os.path.join(CARD_DIR, f"c{idx}.png")
        grad = os.path.join(CARD_DIR, f"c{idx}_grad.png")
        _vgrad_rgb(*PALETTE[idx % len(PALETTE)]).save(grad)
        if kind == "intro":
            make_intro_overlay(topic, ov)
        elif kind == "chapter":
            make_chapter_overlay(dat[0], dat[1], ov)
        elif kind == "outro":
            make_outro_overlay(ov)
        else:
            make_beat_overlay(dat, ov)
        bg = pexels_clip(query, os.path.join(CLIP_DIR, f"c{idx}.mp4")) \
            or pexels_clip("space", os.path.join(CLIP_DIR, f"c{idx}.mp4"))
        clips.append(build_clip(bg, grad, ov, durations[idx], f"clip_{idx}.mp4"))

    assemble(clips, voice, VIDEO_OUT)

    topic_tag = "#" + re.sub(r"[^A-Za-z0-9]", "", topic)
    description = (f"{script['intro']}\n\nA deep dive into {topic}.\n\n"
                   f"{topic_tag} #space #astronomy #science #universe #documentary")
    ok = upload_to_youtube(VIDEO_OUT, script["title"], description)

    if ok:
        posted.append(subject["key"])
        save_posted(posted, sha)


if __name__ == "__main__":
    main()
