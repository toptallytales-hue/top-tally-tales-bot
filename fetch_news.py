import feedparser
import requests
import json
import os
from datetime import datetime, timedelta

# === RELIABLE NEWS SOURCES (No API Key Required) ===
# These RSS feeds cover global news, sports, entertainment, and trending topics
RSS_FEEDS = [
    # General News (Google News via RSS - works without API)
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss?hl=en-GB&gl=GB&ceid=GB:en",
    "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    
    # Sports
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=s",
    "http://www.espn.com/espn/rss/news",
    "https://www.skysports.com/rss/0,0,,,00.xml",
    "https://www.bbc.com/sport/rss.xml",
    
    # Entertainment & Celebrity
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=e",
    "https://rss.nytimes.com/services/xml/rss/nyt/Movies.xml",
    "https://www.wwe.com/feed/news",
    
    # Technology
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=t",
    "https://www.theverge.com/rss/index.xml",
    "https://feeds.feedburner.com/TechCrunch",
    
    # Business & Finance
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=b",
    "https://feeds.bloomberg.com/markets/news.rss",
    
    # Top Stories (Multiple Sources)
    "https://feeds.npr.org/1001/rss.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
]

# === FALLBACK: Scrape Google News Trending Topics (No API) ===
def fetch_google_trending():
    """Fetch trending topics from Google News RSS."""
    try:
        url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries[:10]:
            articles.append({
                'title': entry.title,
                'summary': entry.get('summary', entry.title)[:200],
                'link': entry.link,
                'source': 'Google News',
                'published': entry.get('published', '')
            })
        return articles
    except Exception as e:
        print(f"⚠️ Google News fetch failed: {e}")
        return []

# === MAIN FETCH FUNCTION ===
def fetch_all_news(limit=3):
    """Fetch news from all sources and return combined list."""
    print("📰 Fetching news from multiple sources...")
    all_articles = []
    
    # Try each RSS feed
    for feed_url in RSS_FEEDS:
        try:
            print(f"  Checking: {feed_url[:50]}...")
            feed = feedparser.parse(feed_url)
            count = 0
            for entry in feed.entries:
                if count >= limit:
                    break
                # Skip entries without titles or summaries
                if not entry.get('title'):
                    continue
                    
                all_articles.append({
                    'title': entry.title,
                    'summary': entry.get('summary', entry.get('description', ''))[:300],
                    'link': entry.link,
                    'source': feed.feed.get('title', 'Unknown'),
                    'published': entry.get('published', datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT'))
                })
                count += 1
        except Exception as e:
            print(f"⚠️ Error with feed: {e}")
    
    # If no articles found, use Google News fallback
    if not all_articles:
        print("⚠️ No articles from RSS feeds. Trying Google News fallback...")
        all_articles = fetch_google_trending()
    
    # Remove duplicates based on title
    seen_titles = set()
    unique_articles = []
    for article in all_articles:
        if article['title'] not in seen_titles:
            seen_titles.add(article['title'])
            unique_articles.append(article)
    
    print(f"✅ Found {len(unique_articles)} unique articles")
    return unique_articles

# === GET TRENDING TOPICS (Simple classification) ===
def categorize_article(title, summary):
    """Simple keyword-based categorization."""
    text = (title + " " + summary).lower()
    categories = {
        'sports': ['sport', 'football', 'wwe', 'nfl', 'nba', 'cricket', 'tennis', 'boxing', 'match', 'player', 'team', 'score'],
        'entertainment': ['celebrity', 'movie', 'film', 'actor', 'actress', 'music', 'concert', 'award', 'hollywood', 'bollywood'],
        'tech': ['tech', 'apple', 'google', 'ai', 'artificial intelligence', 'robot', 'space', 'science', 'software'],
        'business': ['business', 'stock', 'market', 'economy', 'trade', 'company', 'fund', 'investment'],
        'politics': ['politics', 'government', 'election', 'vote', 'president', 'prime minister', 'congress', 'senate'],
        'world': ['world', 'international', 'global', 'country', 'nation', 'peace', 'conflict', 'war', 'peace'],
        'health': ['health', 'medical', 'doctor', 'hospital', 'covid', 'disease', 'medicine', 'vaccine'],
        'science': ['science', 'discovery', 'research', 'scientist', 'study', 'space', 'evolution', 'climate'],
        'weather': ['weather', 'storm', 'earthquake', 'tsunami', 'hurricane', 'flood', 'climate'],
    }
    
    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword in text:
                return category
    return 'general'

# === GET TRENDING TOPICS WITH CATEGORY ===
def get_trending_topics(limit=5):
    """Get trending news with categories."""
    articles = fetch_all_news(limit=limit)
    for article in articles:
        article['category'] = categorize_article(article['title'], article['summary'])
    return articles

# === MAIN (For Testing) ===
if __name__ == "__main__":
    print("🚀 Starting TopTallyTales News Fetcher...")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    topics = get_trending_topics(limit=5)
    
    if not topics:
        print("❌ No articles found!")
    else:
        print("\n📋 TOP TRENDING TOPICS:\n")
        for i, topic in enumerate(topics, 1):
            print(f"{i}. [{topic['category'].upper()}] {topic['title']}")
            print(f"   📎 {topic['link'][:80]}...")
            print(f"   📰 {topic['source']}")
            print()