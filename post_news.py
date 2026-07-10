"""
TopTallyTales — one trending story -> one branded YouTube Short.

Free stack: feedparser + GPT (rewrite) + edge-tts (voice) + Pillow (card) + FFmpeg.
Reuses the quality approach from the MK reel builder (photo + blurred fill,
Ken Burns, natural neural voice), self-contained for this channel.

Env (GitHub secrets):
  OPENAI_API_KEY
  YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
  (optional) GH_TOKEN + GITHUB_REPOSITORY  -> remembers posted stories (no repeats)
"""

import os
import re
import json
import time
import base64
import asyncio
import subprocess
from io import BytesIO
from datetime import datetime

import feedparser
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# === CONFIG ===
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

GH_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("APPROVAL_TOKEN")
GH_REPO = os.environ.get("GITHUB_REPOSITORY")
POSTED_FILE = "posted_shorts.json"

BRAND = "TOP TALLY TALES"
# Natural US neural voice. Alternatives: en-US-GuyNeural (male), en-US-JennyNeural,
# en-GB-SoniaNeural (British). Free, no key.
VOICE = "en-US-AriaNeural"
SPEAKING_RATE = "+8%"

RSS_FEEDS = [
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=s",   # sports
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=e",   # entertainment
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=t",   # tech
    "https://feeds.npr.org/1001/rss.xml",
]

W, H = 1080, 1920
FPS = 30
ZOOM_MAX = 1.06

VIDEO_OUT = "short.mp4"
VOICE_OUT = "voice.mp3"
CARD_OUT = "card.png"

ACCENT = (204, 0, 0)
WHITE = (255, 255, 255)


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


def _clean_html(text):
    return " ".join(re.sub(r"<[^>]+>", "", text or "").split())


def _clean_title(title):
    return re.sub(r"\s+-\s+[^-]+$", "", title or "").strip()


# ---------- Fetch + pick trending story ----------
def _entry_time(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    try:
        return time.mktime(t) if t else 0
    except Exception:
        return 0


def fetch_candidates():
    print("📰 Fetching trending stories...")
    entries = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            entries.extend(feed.entries)
        except Exception as e:
            print(f"   ⚠️ {url}: {e}")
    entries.sort(key=_entry_time, reverse=True)
    out, seen = [], set()
    for e in entries:
        title = _clean_title(e.get("title", ""))
        key = " ".join(re.findall(r"[a-z0-9]+", title.lower())[:6])
        if not title or key in seen:
            continue
        seen.add(key)
        out.append({
            "title": title,
            "summary": _clean_html(e.get("summary", e.get("description", "")))[:400],
            "link": e.get("link", ""),
        })
    print(f"✅ {len(out)} candidate stories.")
    return out


# ---------- Posted history (optional, via GitHub) ----------
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
            data = r.json()
            return json.loads(base64.b64decode(data["content"]).decode()), data["sha"]
    except Exception as e:
        print(f"⚠️ posted history load failed: {e}")
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
        print(f"⚠️ posted history save failed: {e}")


# ---------- GPT rewrite ----------
def rewrite(story):
    print("🤖 Rewriting for Shorts...")
    if not OPENAI_API_KEY:
        return {
            "title": story["title"][:90] + " #Shorts",
            "headline": story["title"][:60],
            "narration": story["title"] + ". Follow for more trending news.",
        }
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": (
                        "You produce punchy YouTube Shorts about trending news. Retention is everything; "
                        "the first line must hook instantly (no 'welcome', no greetings). "
                        "Respond ONLY with valid JSON: "
                        '{"title": "...", "headline": "...", "narration": "..."}. '
                        "title: catchy YouTube Short title, under 90 chars, may end with #Shorts. "
                        "headline: 3-7 word bold on-screen phrase. "
                        "narration: 2-3 short spoken sentences in your OWN words (do not copy the source), "
                        "opening with a scroll-stopping hook and ending with a quick 'follow for more'. "
                        "No emojis, no hashtags inside narration, no URLs."
                    )},
                    {"role": "user", "content": f"Story: {story['title']}\nDetails: {story['summary']}"},
                ],
            },
            timeout=45,
        )
        if r.status_code == 200:
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()
            data = json.loads(raw)
            if data.get("title") and data.get("headline") and data.get("narration"):
                print("✅ Rewrite ready.")
                return data
    except Exception as e:
        print(f"⚠️ Rewrite failed ({e}); using fallback.")
    return {
        "title": story["title"][:90] + " #Shorts",
        "headline": story["title"][:60],
        "narration": story["title"] + ". Follow for more trending news.",
    }


# ---------- Image ----------
def _download_image(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if r.status_code == 200 and r.content:
            return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception:
        pass
    return None


def fetch_og_image(link):
    """Best-effort: pull the article's social preview image."""
    if not link:
        return None
    try:
        r = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=20, allow_redirects=True)
        if r.status_code == 200:
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', r.text, re.I) \
                or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', r.text, re.I)
            if m:
                return _download_image(m.group(1))
    except Exception:
        pass
    return None


def _vertical_gradient(size, top, bottom):
    w, h = size
    g = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4)))
    return g.resize((w, h))


def _cover(img, size):
    tw, th = size
    iw, ih = img.size
    s = max(tw / iw, th / ih)
    img = img.resize((int(iw * s), int(ih * s)), Image.LANCZOS)
    l, t = (img.width - tw) // 2, (img.height - th) // 2
    return img.crop((l, t, l + tw, t + th))


def _fit_within(img, mw, mh):
    iw, ih = img.size
    s = min(mw / iw, mh / ih)
    return img.resize((max(int(iw * s), 1), max(int(ih * s), 1)), Image.LANCZOS)


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


def make_card(headline, photo, path):
    card = Image.new("RGB", (W, H), (12, 12, 14))
    if photo is not None:
        blur = _cover(photo, (W, H)).filter(ImageFilter.GaussianBlur(45))
        blur = ImageEnhance.Brightness(blur).enhance(0.4)
        card.paste(blur, (0, 0))
        fitted = _fit_within(photo, W, 980)
        card.paste(fitted, ((W - fitted.width) // 2, 330))
    else:
        card.paste(_vertical_gradient((W, H), (30, 30, 40, 255), (8, 8, 12, 255)).convert("RGB"), (0, 0))

    rgba = card.convert("RGBA")
    rgba = Image.alpha_composite(rgba, _vertical_gradient((W, H), (0, 0, 0, 130), (0, 0, 0, 0)))
    rgba = Image.alpha_composite(rgba, _vertical_gradient((W, H), (0, 0, 0, 0), (0, 0, 0, 248)))
    card = rgba.convert("RGB")
    draw = ImageDraw.Draw(card)

    # Brand strip (top)
    draw.rectangle([0, 60, 18, 150], fill=ACCENT)
    draw.text((44, 78), BRAND, font=_font(48), fill=WHITE)

    # Headline (lower third)
    hfont = _font(86)
    lines = _wrap(draw, headline.upper(), hfont, W - 120)[:5]
    line_h = hfont.size + 12
    y = H - 330 - line_h * len(lines)
    draw.rounded_rectangle([60, y - 48, 60 + 130, y - 34], radius=6, fill=ACCENT)
    for ln in lines:
        draw.text((60, y), ln, font=hfont, fill=WHITE)
        y += line_h

    # CTA
    draw.text((60, H - 150), "▶  SUBSCRIBE for daily trending news", font=_font(40, bold=False),
              fill=(230, 230, 230))
    card.save(path, "PNG")
    return path


# ---------- Voice + video ----------
async def _synth(text, path):
    await edge_tts.Communicate(text, VOICE, rate=SPEAKING_RATE).save(path)


def audio_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", path],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except Exception:
        return 15.0


def build_video(card_path, audio_path, out_path):
    dur = audio_duration(audio_path) + 0.4
    frames = max(int(dur * FPS), 1)
    vf = (f"scale={int(W*1.08)}:{int(H*1.08)},"
          f"zoompan=z='min(zoom+0.0004,{ZOOM_MAX})':d={frames}:s={W}x{H}:fps={FPS}:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',format=yuv420p")
    subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", card_path, "-vf", vf,
                    "-frames:v", str(frames), "-r", str(FPS), "-preset", "veryfast",
                    "-an", "silent.mp4"], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-i", "silent.mp4", "-i", audio_path,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "192k", "-shortest", out_path], check=True, capture_output=True)
    print(f"✅ Video built: {out_path}")
    return out_path


# ---------- YouTube upload ----------
def upload_to_youtube(video_path, title, description):
    print("📤 Uploading to YouTube...")
    if not YOUTUBE_REFRESH_TOKEN or not YOUTUBE_CLIENT_ID:
        print("❌ YouTube credentials not configured!")
        return False
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        creds = Credentials(
            None, refresh_token=YOUTUBE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET,
        )
        youtube = build("youtube", "v3", credentials=creds)
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        req = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title[:100],
                    "description": description[:4900],
                    "categoryId": "25",  # News & Politics
                    "tags": ["TopTallyTales", "News", "Trending", "Shorts"],
                },
                "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
            },
            media_body=media,
        )
        resp = req.execute()
        print(f"✅ Uploaded: https://youtu.be/{resp['id']}")
        return True
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return False


# ---------- Main ----------
def main():
    print("🚀 TopTallyTales Shorts builder")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    posted, sha = load_posted()
    candidates = fetch_candidates()
    story = next((c for c in candidates if c["link"] and c["link"] not in posted), None)
    if not story:
        print("✅ No new trending story to post.")
        return
    print(f"📌 Story: {story['title']}")

    content = rewrite(story)

    print("🎙️ Synthesizing voice...")
    asyncio.run(_synth(content["narration"], VOICE_OUT))

    photo = _download_image(story.get("link")) if False else None  # RSS rarely has images
    photo = fetch_og_image(story.get("link"))
    make_card(content["headline"], photo, CARD_OUT)

    build_video(CARD_OUT, VOICE_OUT, VIDEO_OUT)

    description = (content["narration"] + "\n\n" +
                   "#Shorts #Trending #News #TopTallyTales #Viral #Breaking")
    ok = upload_to_youtube(VIDEO_OUT, content["title"], description)

    if ok and story.get("link"):
        posted.append(story["link"])
        save_posted(posted, sha)


if __name__ == "__main__":
    main()
