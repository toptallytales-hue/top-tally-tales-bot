import os
import sys
import requests
import json
from datetime import datetime

# === CONFIGURATION ===
YOUTUBE_ACCESS_TOKEN = os.environ.get("YOUTUBE_ACCESS_TOKEN")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID")

# === CREATE VIDEO SCRIPT ===
def generate_script(title, summary, category):
    """Generate a 60-second script for a YouTube Short."""
    
    # Clean the title and summary
    title = title.replace('"', '').replace("'", "")
    summary = summary.replace('"', '').replace("'", "")
    
    # Generate a hook based on category
    hooks = {
        'sports': "🔥 HUGE NEWS in the sports world! ",
        'entertainment': "🎬 BREAKING: ",
        'tech': "💡 Technology just changed! ",
        'business': "💰 Big business alert! ",
        'politics': "🏛️ Political update: ",
        'world': "🌍 World news: ",
        'health': "🏥 Health alert: ",
        'science': "🔬 Science breakthrough! ",
        'weather': "🌪️ Weather warning: ",
        'general': "🚨 BREAKING NEWS: "
    }
    
    hook = hooks.get(category, "🚨 BREAKING NEWS: ")
    
    # Create the full script (about 150-200 words = 60 seconds)
    script = f"""{hook}{title}

{summary[:200]}

Thanks for watching! Subscribe for daily updates! 🔔
#TopTallyTales #Trending #News #Shorts"""
    
    return script

# === CREATE VIDEO (Placeholder - We'll use ffmpeg later) ===
def create_video(script, title):
    """Create a video from the script (Placeholder)."""
    print(f"🎬 Creating video for: {title}")
    print(f"📝 Script: {script[:200]}...")
    
    # For now, we'll just save the script to a file
    with open(f"video_script_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", "w") as f:
        f.write(script)
    
    return "video_script.txt"

# === UPLOAD TO YOUTUBE (Placeholder) ===
def upload_to_youtube(video_path, title, description):
    """Upload video to YouTube (Placeholder)."""
    print(f"📤 Uploading to YouTube: {title}")
    print(f"📝 Description: {description[:100]}...")
    print(f"⚠️ YouTube upload requires OAuth2 setup.")
    return True

# === MAIN ===
def main():
    print("🚀 Starting TopTallyTales YouTube Automation...")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check if we have the necessary files
    if not os.path.exists("fetch_news.py"):
        print("❌ fetch_news.py not found!")
        sys.exit(1)
    
    # Import fetch_news
    try:
        from fetch_news import get_trending_topics
    except ImportError:
        print("❌ Could not import fetch_news.py")
        sys.exit(1)
    
    # Get trending topics
    topics = get_trending_topics(limit=1)
    
    if not topics:
        print("❌ No topics found. Exiting.")
        sys.exit(1)
    
    # Process the first topic
    topic = topics[0]
    print(f"\n📋 Topic: {topic['title']}")
    print(f"📂 Category: {topic['category']}")
    
    # Generate script
    script = generate_script(topic['title'], topic['summary'], topic['category'])
    print(f"\n📝 Script generated:")
    print("-" * 50)
    print(script)
    print("-" * 50)
    
    # Create video (placeholder)
    video_path = create_video(script, topic['title'])
    
    # Upload (placeholder)
    upload_to_youtube(video_path, topic['title'], script)
    
    print("\n✅ Workflow completed!")

if __name__ == "__main__":
    main()