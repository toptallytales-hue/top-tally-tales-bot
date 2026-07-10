import os
import sys
import requests
import json
import subprocess
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import feedparser

# === CONFIGURATION ===
YOUTUBE_ACCESS_TOKEN = os.environ.get("YOUTUBE_ACCESS_TOKEN")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID")

# === FETCH NEWS ===
def fetch_trending_news():
    """Fetch trending news from multiple RSS feeds."""
    feeds = [
        "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=s",
        "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=e",
        "https://feeds.npr.org/1001/rss.xml",
    ]
    
    all_articles = []
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:2]:
                all_articles.append({
                    'title': entry.title,
                    'summary': entry.get('summary', entry.get('description', ''))[:200],
                    'link': entry.link,
                    'published': entry.get('published', '')
                })
        except Exception as e:
            print(f"⚠️ Error fetching feed: {e}")
    
    return all_articles

# === GENERATE SCRIPT ===
def generate_script(title, summary):
    """Generate a 60-second script from the news."""
    script = f"BREAKING NEWS: {title}\n\n{summary[:150]}\n\nThanks for watching! Subscribe for daily updates! #TopTallyTales #Trending #News #Shorts"
    return script

# === CREATE VIDEO USING FFMPEG ===
def create_video(script, title):
    """Create a YouTube Short using ffmpeg."""
    print(f"🎬 Creating video for: {title}")
    
    # Create a simple image with text overlay
    image_path = create_image_with_text(title)
    audio_path = create_audio(script)
    
    # Combine image + audio into a video
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

# === CREATE IMAGE WITH TEXT ===
def create_image_with_text(title):
    """Create a 1080x1920 image with text overlay."""
    img_path = "background.jpg"
    
    # Use a simple colored background
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new('RGB', (1080, 1920), color='#cc0000')
        draw = ImageDraw.Draw(img)
        
        # Use default font (or arial if available)
        try:
            font = ImageFont.truetype("arial.ttf", 80)
        except:
            font = ImageFont.load_default()
        
        # Wrap text
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
        
        # Add footer
        draw.text((540, 1800), "TopTallyTales", fill='white', font=font, anchor='mt')
        
        img.save(img_path)
        print(f"✅ Image created: {img_path}")
        return img_path
    except ImportError:
        print("⚠️ PIL not installed. Using fallback.")
        return None

# === CREATE AUDIO ===
def create_audio(script):
    """Create audio from text using gTTS."""
    audio_path = "audio.mp3"
    try:
        from gtts import gTTS
        tts = gTTS(script[:200], lang='en', slow=False)
        tts.save(audio_path)
        print(f"✅ Audio created: {audio_path}")
        return audio_path
    except ImportError:
        print("⚠️ gTTS not installed. Creating silent audio.")
        # Create silent audio using ffmpeg
        try:
            cmd = ["ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "30", "-c:a", "pcm_s16le", "silent.wav"]
            subprocess.run(cmd, check=True, capture_output=True)
            return "silent.wav"
        except:
            return None

# === UPLOAD TO YOUTUBE ===
def upload_to_youtube(video_path, title, description):
    """Upload video to YouTube using the API."""
    print(f"📤 Uploading to YouTube: {title}")
    print(f"📝 Description: {description[:100]}...")
    
    # Placeholder - you'll need to set up OAuth2
    # See: https://developers.google.com/youtube/v3/guides/uploading_a_video
    print("⚠️ YouTube upload requires OAuth2 setup.")
    print("💡 For now, you can upload the video manually.")
    
    return False

# === MAIN ===
def main():
    print("🚀 Starting TopTallyTales Shorts Automation...")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Step 1: Fetch news
    articles = fetch_trending_news()
    if not articles:
        print("❌ No articles found!")
        return
    
    # Step 2: Process first article
    article = articles[0]
    print(f"📰 {article['title']}")
    
    # Step 3: Generate script
    script = generate_script(article['title'], article['summary'])
    print(f"📝 Script: {script[:100]}...")
    
    # Step 4: Create video
    video_path = create_video(script, article['title'])
    
    if video_path:
        # Step 5: Upload
        upload_to_youtube(video_path, article['title'], script)
    else:
        print("❌ Video creation failed!")

if __name__ == "__main__":
    main()
