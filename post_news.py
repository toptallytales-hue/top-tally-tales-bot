"""
TopTallyTales — trending "Did you know?" facts Short.

Picks the day's most prominent trending topic, GPT turns it into a punchy hook
+ 4 surprising one-line facts, each on its own vibrant animated card, narrated
in an energetic neural voice, perfectly synced, then uploaded to YouTube.

Free stack: feedparser + GPT + edge-tts + Pillow + FFmpeg.

Env (secrets): OPENAI_API_KEY, YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET,
YOUTUBE_REFRESH_TOKEN, and (optional) GH_TOKEN + GITHUB_REPOSITORY for no-repeats.
"""

import os
import re
import json
import time
import base64
import asyncio
import subprocess
from datetime import datetime

import feedparser
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# === CONFIG ===
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

GH_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("APPROVAL_TOKEN")
GH_REPO = os.environ.get("GITHUB_REPOSITORY")
POSTED_FILE = "posted_shorts.json"

BRAND = "TOP TALLY TALES"
VOICE = "en-US-AriaNeural"      # lively US voice. Try en-US-GuyNeural / en-US-JennyNeural
SPEAKING_RATE = "+12%"          # energetic
NUM_FACTS = 4

# Trending sources (order = prominence; we take the top unposted topic)
RSS_FEEDS = [
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=e",  # entertainment
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=t",  # tech
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=s",  # sports
]

W, H = 1080, 1920
FPS = 30
GAP = 0.28
TAIL = 0.6
ZOOM_MAX = 1.06

VOICE_OUT = "voice.mp3"
VIDEO_OUT = "short.mp4"
CARD_DIR = "cards"

WHITE = (255, 255, 255)
# Vibrant gradient palette (top, bottom) — white text pops on all of them.
PALETTE = [
    ((104, 58, 183), (38, 16, 84)),     # purple
    ((33, 118, 214), (12, 40, 96)),     # blue
    ((0, 150, 136), (0, 55, 66)),       # teal
    ((233, 106, 20), (96, 30, 8)),      # orange
    ((214, 51, 132), (78, 12, 58)),     # magenta
    ((46, 160, 90), (12, 58, 34)),      # green
]


# ---------- Fonts ----------
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


def _clean_html(t):
    return " ".join(re.sub(r"<[^>]+>", "", t or "").split())


def _clean_title(t):
    return re.sub(r"\s+-\s+[^-]+$", "", t or "").strip()


# ---------- Pick a trending topic ----------
def fetch_trending():
    print("📡 Finding a trending topic...")
    entries = []
    for url in RSS_FEEDS:
        try:
            entries.extend(feedparser.parse(url).entries[:15])
        except Exception as e:
            print(f"   ⚠️ {url}: {e}")
    out, seen = [], set()
    for e in entries:
        title = _clean_title(e.get("title", ""))
        key = " ".join(re.findall(r"[a-z0-9]+", title.lower())[:6])
        if not title or key in seen:
            continue
        seen.add(key)
        out.append({"title": title,
                    "summary": _clean_html(e.get("summary", e.get("description", "")))[:400],
                    "link": e.get("link", "")})
    print(f"✅ {len(out)} trending candidates.")
    return out


# ---------- Posted history ----------
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


# ---------- GPT: topic -> hook + facts ----------
def make_facts(story):
    print("🤖 Generating facts...")
    fallback = {
        "topic": story["title"][:40],
        "hook": "Here are some things you probably didn't know.",
        "facts": [story["title"]],
        "title": story["title"][:80] + " #Shorts",
    }
    if not OPENAI_API_KEY:
        return fallback
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": (
                        "You make viral 'Did you know?' fact Shorts for YouTube. Given a trending topic, "
                        "identify the core subject and produce genuinely surprising, accurate, well-known facts "
                        "about it (not made up). Retention is everything: instant hook, punchy delivery. "
                        "Respond ONLY with valid JSON: "
                        '{"topic": "...", "hook": "...", "facts": ["...", "..."], "title": "..."}. '
                        "topic: 1-3 word on-screen subject in caps-friendly form. "
                        "hook: one spoken scroll-stopping sentence (no 'welcome'/'hey guys'). "
                        f"facts: EXACTLY {NUM_FACTS} items, each ONE short punchy factual sentence (max ~16 words), "
                        "surprising and true. "
                        "title: catchy YouTube Short title under 90 chars ending with #Shorts. "
                        "No emojis, no hashtags inside hook/facts, no URLs."
                    )},
                    {"role": "user", "content": f"Trending topic: {story['title']}\nContext: {story['summary']}"},
                ],
            },
            timeout=45,
        )
        if r.status_code == 200:
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()
            d = json.loads(raw)
            facts = [str(x).strip() for x in d.get("facts", []) if str(x).strip()]
            if d.get("topic") and d.get("hook") and len(facts) >= 3 and d.get("title"):
                d["facts"] = facts[:NUM_FACTS]
                print(f"✅ Facts ready on: {d['topic']}")
                return d
        print(f"⚠️ Facts JSON off; using fallback. ({r.status_code})")
    except Exception as e:
        print(f"⚠️ Facts generation failed ({e}); fallback.")
    return fallback


# ---------- Cards ----------
def _vertical_gradient(size, top, bottom):
    w, h = size
    g = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return g.resize((w, h))


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


def _center_text(draw, y, text, font, fill, maxw):
    for ln in _wrap(draw, text, font, maxw):
        lw = draw.textlength(ln, font=font)
        draw.text(((W - lw) / 2, y), ln, font=font, fill=fill)
        y += font.size + 14
    return y


def _brand(draw):
    f = _font(38)
    draw.text((44, H - 80), BRAND, font=f, fill=(255, 255, 255))


def make_hook_card(topic, path, color):
    card = _vertical_gradient((W, H), *color)
    draw = ImageDraw.Draw(card)
    draw.text((44, 70), BRAND, font=_font(42), fill=(255, 255, 255))
    # centered stack
    kf, tf, sf = _font(56), _font(150), _font(52)
    topic_lines = _wrap(draw, topic.upper(), tf, W - 120)
    block_h = kf.size + 40 + (tf.size + 10) * len(topic_lines) + 40 + sf.size
    y = (H - block_h) // 2
    kw = draw.textlength("DID YOU KNOW?", font=kf)
    draw.text(((W - kw) / 2, y), "DID YOU KNOW?", font=kf, fill=(255, 235, 120))
    y += kf.size + 40
    y = _center_text(draw, y, topic.upper(), tf, WHITE, W - 120)
    y += 26
    sub = f"{NUM_FACTS} FACTS THAT WILL SURPRISE YOU"
    sw = draw.textlength(sub, font=sf)
    draw.text(((W - sw) / 2, y), sub, font=sf, fill=(255, 255, 255))
    card.save(path, "PNG")
    return path


def make_fact_card(n, total, fact, path, color):
    card = _vertical_gradient((W, H), *color)
    draw = ImageDraw.Draw(card)
    draw.text((44, 70), BRAND, font=_font(42), fill=(255, 255, 255))

    # Number badge (circle)
    r = 90
    cx, cy = W // 2, 430
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255))
    nf = _font(96)
    ns = str(n)
    nw = draw.textlength(ns, font=nf)
    draw.text((cx - nw / 2, cy - nf.size / 2 - 6), ns, font=nf, fill=color[0])

    # Fact text (centered, big)
    ff = _font(80)
    lines = _wrap(draw, fact, ff, W - 140)
    total_h = (ff.size + 16) * len(lines)
    y = cy + r + 90
    for ln in lines:
        lw = draw.textlength(ln, font=ff)
        draw.text(((W - lw) / 2, y), ln, font=ff, fill=WHITE)
        y += ff.size + 16

    # progress dots
    dot = 18
    gap = 34
    total_w = total * dot + (total - 1) * gap
    x = (W - total_w) // 2
    for i in range(total):
        fill = (255, 235, 120) if i < n else (255, 255, 255, 120)
        draw.ellipse([x, H - 150, x + dot, H - 150 + dot], fill=(255, 235, 120) if i < n else (255, 255, 255))
        x += dot + gap
    card.save(path, "PNG")
    return path


def make_outro_card(path, color):
    card = _vertical_gradient((W, H), *color)
    draw = ImageDraw.Draw(card)
    draw.text((44, 70), BRAND, font=_font(42), fill=(255, 255, 255))
    bf, sf = _font(120), _font(50)
    lines = _wrap(draw, "FOLLOW FOR MORE", bf, W - 120)
    block = (bf.size + 10) * len(lines) + 40 + sf.size
    y = (H - block) // 2
    y = _center_text(draw, y, "FOLLOW FOR MORE", bf, WHITE, W - 120)
    y += 24
    sub = "MIND-BLOWING FACTS DAILY"
    sw = draw.textlength(sub, font=sf)
    draw.text(((W - sw) / 2, y), sub, font=sf, fill=(255, 235, 120))
    card.save(path, "PNG")
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
    print(f"🎙️ Synthesizing {len(segment_texts)} segments ({VOICE})...")
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


# ---------- Assemble (hard cuts, synced) ----------
def _clip(card_path, duration, out_path, zoom_in=True):
    frames = max(int(duration * FPS), 1)
    z = f"min(zoom+0.0004,{ZOOM_MAX})" if zoom_in else f"if(eq(on,1),{ZOOM_MAX},max(zoom-0.0004,1.0))"
    vf = (f"scale={int(W*1.08)}:{int(H*1.08)},"
          f"zoompan=z='{z}':d={frames}:s={W}x{H}:fps={FPS}:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',format=yuv420p")
    subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", card_path, "-vf", vf,
                    "-frames:v", str(frames), "-r", str(FPS), "-preset", "veryfast",
                    "-an", out_path], check=True, capture_output=True)


def assemble(cards, durations, audio, out):
    print("🎞️ Rendering...")
    clips = []
    for i, (c, d) in enumerate(zip(cards, durations)):
        clip = f"clip_{i}.mp4"
        _clip(c, d, clip, zoom_in=(i % 2 == 0))
        clips.append(clip)
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
                              "categoryId": "24",
                              "tags": ["DidYouKnow", "Facts", "Trending", "Shorts", "TopTallyTales"]},
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
    print("🚀 TopTallyTales — Did You Know Shorts")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    os.makedirs(CARD_DIR, exist_ok=True)

    posted, sha = load_posted()
    candidates = fetch_trending()
    story = next((c for c in candidates if c["link"] and c["link"] not in posted), None)
    if not story:
        print("✅ No new trending topic. Exiting.")
        return
    print(f"📌 Topic source: {story['title']}")

    data = make_facts(story)
    topic, hook, facts = data["topic"], data["hook"], data["facts"]

    segments = [hook] + facts + ["Follow for more mind-blowing facts every day."]
    voice, durations = build_narration(segments)

    # Cards: hook + fact cards + outro (same count/order as segments)
    cards = [make_hook_card(topic, os.path.join(CARD_DIR, "hook.png"), PALETTE[0])]
    for i, fact in enumerate(facts):
        color = PALETTE[(i + 1) % len(PALETTE)]
        cards.append(make_fact_card(i + 1, len(facts), fact,
                                    os.path.join(CARD_DIR, f"fact_{i}.png"), color))
    cards.append(make_outro_card(os.path.join(CARD_DIR, "outro.png"), PALETTE[(len(facts) + 1) % len(PALETTE)]))

    assemble(cards, durations, voice, VIDEO_OUT)

    description = (f"{topic} — did you know? {hook}\n\n"
                   "#Shorts #DidYouKnow #Facts #Trending #Viral #TopTallyTales")
    ok = upload_to_youtube(VIDEO_OUT, data["title"], description)

    if ok and story.get("link"):
        posted.append(story["link"])
        save_posted(posted, sha)


if __name__ == "__main__":
    main()
