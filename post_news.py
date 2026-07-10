import os
import sys
import json
import subprocess
import feedparser
import requests
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS

# === CONFIGURATION ===
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID")

# === FETCH NEWS ===
def fetch_news():
    feeds = [
        "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=s",
        "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=e",
        "https://feeds.npr.org/1001/rss.xml",
    ]
    articles = []
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:1]:
                articles.append({
                    'title': entry.title,
                    'summary': entry.get('summary', entry.get('description', ''))[:200],
                    'link': entry.link,
                })
        except:
            pass
    return articles

# === GENERATE SCRIPT ===
def generate_script(title, summary):
    return f"BREAKING: {title}\n\n{summary[:150]}\n\nSubscribe for daily updates! #TopTallyTales #News"

# === CREATE IMAGE WITH TEXT ===
def create_image_with_text(title):
    img_path = "background.jpg"
    try:
        img = Image.new('RGB', (1080, 1920), color='#cc0000')
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 80)
        except:
            font = ImageFont.load_default()
        
        lines = []
        words = title.split()
        line = ""
        for word in words:
            if len(line + word) < 30:
                line += word + " "
            else:
                lines.append(line)
                line = word + " "
        lines.append(line)
        
        y = 700
        for line in lines:
            draw.text((540, y), line, fill='white', font=font, anchor='mt')
            y += 100
        
        draw.text((540, 1800), "TopTallyTales", fill='white', font=font, anchor='mt')
        img.save(img_path)
        print(f"✅ Image created: {img_path}")
        return img_path
    except Exception as e:
        print(f"❌ Image creation failed: {e}")
        return None

# === CREATE AUDIO ===
def create_audio(script):
    audio_path = "audio.mp3"
    try:
        tts = gTTS(script[:200], lang='en', slow=False)
        tts.save(audio_path)
        print(f"✅ Audio created: {audio_path}")
        return audio_path
    except Exception as e:
        print(f"❌ Audio creation failed: {e}")
        return None

# === CREATE VIDEO ===
def create_video(title):
    print(f"🎬 Creating video for: {title}")
    
    image_path = create_image_with_text(title)
    if not image_path:
        return None
    
    script = generate_script(title, "Summary placeholder")
    audio_path = create_audio(script)
    if not audio_path:
        return None
    
    output_path = f"short_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    
    try:
        cmd = [
            "ffmpeg",
            "-loop", "1",
            "-i", image_path,
            "-i", audio_path,
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            "-vf", "scale=1080:1920",
            output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✅ Video created: {output_path}")
        return output_path
    except Exception as e:
        print(f"❌ Video creation failed: {e}")
        return None

# === UPLOAD TO YOUTUBE ===
def upload_to_youtube(video_path, title, description):
    print("📤 Uploading to YouTube...")
    
    if not YOUTUBE_REFRESH_TOKEN or not YOUTUBE_CLIENT_ID:
        print("❌ YouTube credentials not configured!")
        return False
    
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        
        # Create credentials from refresh token
        creds = Credentials(
            None,
            refresh_token=YOUTUBE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=YOUTUBE_CLIENT_ID,
            client_secret=YOUTUBE_CLIENT_SECRET
        )
        
        # Build YouTube service
        youtube = build("youtube", "v3", credentials=creds)
        
        # Upload video
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title[:100],
                    "description": description[:5000],
                    "categoryId": "22",  # News & Politics
                    "tags": ["TopTallyTales", "News", "Trending", "Shorts"]
                },
                "status": {
                    "privacyStatus": "public",
                    "madeForKids": False,
                    "selfDeclaredMadeForKids": False
                }
            },
            media_body=media
        )
        
        response = request.execute()
        print(f"✅ Uploaded! Video ID: {response['id']}")
        print(f"🔗 https://youtu.be/{response['id']}")
        return True
        
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return False

# === MAIN ===
def main():
    print("🚀 Starting TopTallyTales Shorts Bot...")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Fetch news
    articles = fetch_news()
    if not articles:
        print("❌ No articles found!")
        return
    
    # Process first article
    article = articles[0]
    print(f"📰 {article['title']}")
    
    # Generate script
    script = generate_script(article['title'], article['summary'])
    print(f"📝 Script: {script[:100]}...")
    
    # Create video
    video_path = create_video(article['title'])
    if not video_path:
        print("❌ Video creation failed!")
        return
    
    # Upload to YouTube
    upload_to_youtube(video_path, article['title'], script)

if __name__ == "__main__":
    main()
