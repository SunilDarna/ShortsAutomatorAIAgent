import subprocess
import time
import requests
import random
import json
import os
from urllib.parse import quote
from google import genai
from google.genai import types
from googleapiclient.discovery import build

CHANNELS = [
    "UCNJ1Ymd5yFuUPtn21xtRbbw", # AI Explained (Gold Standard)
    "UCsBjURrPoezykLs9EqgamOA", # Fireship (Retention King)
    "UCTNDbjZLbTNFtBL3FAXUEQF", # The AI Advantage (Viral Trends) - NEW
    "UCawZsQWqfGSbCI5yjkdVkTA", # Matthew Berman (LLM Hype) - NEW
    "UCt6l0E-bBC1Z4d7C3qgh3cA", # ColdFusion (Narrative Tech) - NEW
    "UChpleBmo18P08aKCIgti38g", # Matt Wolfe (News/Tools)
    "UCqcbQf6yw5KzRoDDcZ_wBSw", # Wes Roth (AI News)
    "UCCSrPWb7mjVUIPcxSbJ2SSA", # Sam Despo (AI Biz)
    "UCUyDOdBWhC1MCxEjC46d-zw", # Alex Hormozi (Income Cheat Codes)
    "UCQ4FNww3XoNgqIlkBqEAVCg", # Iman Gadzhi (Wealth Hype)
    "UCctXZhXmG-kf3tlIXgVZUlw", # GaryVee (Attention King)
    "UC2D2CMWXMOVWx7giW1n3LIg", # Huberman Lab (Health/Authority)
    "UCGq-a57w-aPwyi3pW7XLiHw", # Diary of a CEO (Emotional Hooks)
    "UCnYMOamNKLGVlJgRUbamveA", # Impact Theory (Success Hooks)
    "UCbfYPyITQ-7l4upoX8nvctg"  # Two Minute Papers (Visual AI)
]

def get_local_headers():
    """Returns randomized browser headers to mimic a real user."""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0"
    ]
    return {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive"
    }

def get_latest_video_from_channels(unused_key=None):
    """ 
    Uses Local Scraper (yt-dlp) to find latest videos.
    Replaces ScraperAPI to avoid costs/limits.
    """
    for attempt in range(15):
        channel_id = random.choice(CHANNELS)
        print(f"Local Scraper: Probing channel {channel_id}...")
        
        try:
            channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"
            # Use python3 -m yt_dlp to ensure it's found
            cmd = [
                'python3', '-m', 'yt_dlp',
                '--playlist-items', '1',
                '--get-id', '--get-title',
                '--flat-playlist',
                '--quiet', '--no-warnings',
                '--user-agent', get_local_headers()['User-Agent'],
                channel_url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    title = lines[0]
                    video_id = lines[1]
                    return f"https://www.youtube.com/watch?v={video_id}", title
        except Exception as e:
            print(f"Local Scraper Error for {channel_id}: {e}")
            
    raise Exception("Local Scraper failed to find videos after multiple attempts.")

from youtube_transcript_api import YouTubeTranscriptApi

def get_transcript(video_url, youtube_api_key, unused_key=None):
    """Fetch transcript and return both full text and raw timestamped data."""
    video_id = video_url.split("v=")[-1]
    print(f"Local Scraper: Fetching transcript for {video_id}...")
    
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        transcript = transcript_list.find_transcript(['en'])
        transcript_data = transcript.fetch()
        
        full_text = ""
        for entry in transcript_data:
            # Robustly handle both dict and object types
            if isinstance(entry, dict):
                start = int(entry.get('start', 0))
                text = entry.get('text', '').strip()
            else:
                start = int(getattr(entry, 'start', 0))
                text = getattr(entry, 'text', '').strip()
                
            mins, secs = divmod(start, 60)
            timestamp = f"[{mins:02d}:{secs:02d}]"
            if text:
                full_text += f"{timestamp} {text}\n"
        
        if full_text:
            # Convert to plain list of dicts for JSON serialization
            serializable_data = []
            for entry in transcript_data:
                if isinstance(entry, dict):
                    serializable_data.append(entry)
                else:
                    serializable_data.append({
                        'start': getattr(entry, 'start', 0),
                        'duration': getattr(entry, 'duration', 0),
                        'text': getattr(entry, 'text', '')
                    })
            return full_text, serializable_data
        raise Exception("Transcript was empty.")
    except Exception as e:
        print(f"Local Transcript Fetch failed: {e}")
        raise Exception(f"Failed to fetch transcript: {e}")

def extract_task_with_llm(video_url, transcript, llm_api_key, affiliate_offers):
    client = genai.Client(api_key=llm_api_key)
    
    prompt = f"""
    ROLE: You are an autonomous Affiliate Strategist and "Conversion Architect". Your goal is to maximize Click-Through Rate (CTR) by matching viral content with high-utility software solutions.

    TASK 1: COMPLIANCE & SAFETY (THE "SAFE SHIELD")
    1. Avoid "Scammy" or "Get Rich Quick" claims.
    2. Ensure the segment is informative, educational, or transformative.
    3. Do NOT select segments containing sensitive political, medical, or controversial topics.
    4. Ensure the Title and Description accurately reflect the video content.

    TASK 2: SMART AFFILIATE MATCHING
    1. Analyze the Transcript: Identify the specific "Pain Point" or problem discussed in the video.
    2. Match the Engine: Select the most relevant tool from this list that acts as the immediate mechanical solution:
    {json.dumps(affiliate_offers, indent=2)}

    TASK 3: SEGMENT EXTRACTION (THE "GOLDEN NUGGET")
    Identify a high-impact, standalone segment from the transcript.
    CRITICAL: The duration (end_time minus start_time) MUST be between 30 and 58 seconds. NEVER exceed 58 seconds.

    TASK 4: CONVERSION TRAPS
    1. Hook Text: A dramatic, scroll-stopping headline for the FIRST 3 seconds (max 5 words).
    2. Title: Viral, click-worthy title (max 50 chars).
    3. Description: Start with the affiliate link. Include "#Shorts #AI #Business".
    4. AI Disclosure: Include "Edited with AI assistance" at the bottom.
    5. Bridge Text: Overlay text for the final 3 seconds: "Want to automate this? Link in bio"
    6. Pinned Comment (ENGAGEMENT TRAP): Create a "Keyword Trigger" comment. 
       Format: "Want to use this [Tool Name]? Comment '[KEYWORD]' below and I'll send you the direct link! 🚀"
       (The keyword should be short and relevant, e.g. 'AI', 'TOOL', 'BOT').

    Return your answer EXACTLY as a raw JSON object.

    Required JSON Schema:
    {{
        "start_time": "MM:SS",
        "end_time": "MM:SS",
        "hook_text": "First 3-sec hook text",
        "bridge_text": "Final 3-sec bridge text",
        "title": "Viral Video Title",
        "suggested_affiliate": "Name of Selected Tool",
        "youtube_description": "[Affiliate Link] \n[Viral Description] \n#Shorts #AI #Business \n\nEdited with AI assistance.",
        "pinned_comment": "Keyword trigger comment (Comment '...' for the link!)"
    }}
    
    Transcript:
    {transcript}
    """
    
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt
    )
    raw_text = response.text.strip()
    
    # Strip markdown if LLM added it anyway
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]
        
    return json.loads(raw_text.strip())

def generate_autonomous_task(llm_api_key, youtube_api_key, scraper_api_key=None):
    print("AI Brain: Initiating autonomous video sourcing...")
    
    video_url, title = get_latest_video_from_channels()
    print(f"AI Brain: Found latest video: {title} ({video_url})")
    
    transcript = get_transcript(video_url, youtube_api_key, scraper_api_key)
    print("AI Brain: Transcript fetched. Analyzing with Gemini LLM...")
    
    task_data = extract_task_with_llm(video_url, transcript, llm_api_key)
    print(f"AI Brain: Extraction complete! Golden Nugget: {task_data['start_time']} - {task_data['end_time']}")
    
    return task_data
