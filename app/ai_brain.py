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

# 🌟 Viral Authority Tier (Priority Sources)
PRIORITY_CHANNELS = [
    "UCUyDOdBWhC1MCxEjC46d-zw", # Alex Hormozi
    "UCGq-a57w-aPwyi3pW7XLiHw", # The Diary of a CEO
    "UCxoRKax_0vHaulMbceZtAwA", # My First Million
    "UCGX7nGXpz-CmO_Arg-cgJ7A", # Codie Sanchez
    "UChfo46ZNOV-vtehDc25A1Ug", # Ali Abdaal
    "UC3ov_5a1a1p4-1p9fL8P0Lw", # Patrick Bet-David (Valuetainment)
    "UCQ4FNww3XoNgqIlkBqEAVCg", # Iman Gadzhi
    "UCXC3etwvNkMBGrc6tcwu5oQ", # Noah Kagan
    "UCa-ckhlKL98F8YXKQ-BALiw", # Graham Stephan
    "UCctXZhXmG-kf3tlIXgVZUlw", # GaryVee
]

# ⚙️ Technical & News Tier (Secondary Sources)
SECONDARY_CHANNELS = [
    "UCawZsQWqfGSbCI5yjkdVkTA", # Matthew Berman (AI/Tech)
    "UCTNDbjZLbTNFtBL3FAXUEQF", # The AI Advantage
    "UCt6l0E-bBC1Z4d7C3qgh3cA", # ColdFusion (Narrative Tech)
    "UCsBjURrPoezykLs9EqgamOA", # Fireship (High retention tech)
    "UChpleBmo18P08aKCIgti38g", # Matt Wolfe (AI Tools)
    "UCqcbQf6yw5KzRoDDcZ_wBSw", # Wes Roth (AI News)
    "UCmZhTGgWGcgQ_zRUsMowPuw", # ByteByteGo (System Design & Architecture)
    "UCd6MoB9NC6uYN2grvUNT-Zg", # AWS Events / re:Invent (Enterprise Cloud)
    "UCMxNxyU0h6S0H0t-tL8FzNg", # Y Combinator (Startup Strategy)
    "UCNJ1Ymd5yFuUPtn21xtRbbw", # AI Explained (Gold Standard)
    "UCCSrPWb7mjVUIPcxSbJ2SSA", # Sam Despo (AI Biz)
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
    Prioritizes Authority channels before falling back to Secondary tech channels.
    """
    # Attempt priority channels first
    priority_pool = list(PRIORITY_CHANNELS)
    random.shuffle(priority_pool)
    
    # Combined list for full fallback
    full_pool = priority_pool + SECONDARY_CHANNELS
    
    for attempt, channel_id in enumerate(full_pool):
        if attempt < len(PRIORITY_CHANNELS):
             print(f"Local Scraper [PRIORITY]: Probing channel {channel_id}...")
        else:
             print(f"Local Scraper [SECONDARY]: Probing channel {channel_id}...")
        
        try:
            channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"
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
            
    raise Exception("Local Scraper failed to find videos in both tiers.")

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

def parse_seconds(time_str):
    parts = time_str.split(':')
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return int(time_str)

def extract_task_with_llm(video_url, transcript, llm_api_key, affiliate_offers):
    """TWO-PASS VIRAL HOOK ENGINE with SEO 2.0 Enhancements."""
    client = genai.Client(api_key=llm_api_key)
    
    # PASS 1: Identify High-Value Concepts
    print("AI Brain Pass 1: Identifying high-value concepts...")
    pass1_prompt = f"""
    ROLE: Viral Content Strategist.
    Analyze this transcript and identify the 3 most controversial, counter-intuitive, or high-value business/tech concepts.
    Return only a JSON list of concepts with approximate start and end timestamps (MM:SS).
    
    Example: [{{"concept": "...", "start": "02:10", "end": "04:30"}}, ...]
    
    Transcript:
    {transcript[:15000]}
    """
    
    response1 = client.models.generate_content(model="gemini-flash-latest", contents=pass1_prompt)
    raw1 = response1.text.strip().replace("```json", "").replace("```", "").strip()
    concepts = json.loads(raw1)
    
    # Pick the first concept for deep analysis
    target = concepts[0]
    print(f"AI Brain Pass 2: Zooming in on '{target['concept']}' at {target['start']}...")
    
    # PASS 2: Precision Clip Extraction & SEO Engineering
    pass2_prompt = f"""
    ROLE: Precision Clip Architect & SEO Engineer.
    Analyze the dialogue around {target['start']} to {target['end']}.
    EXTRACT a continuous, coherent sequence strictly between 40 and 57 seconds.
    
    TASK 1: VIRAL TITLING
    Generate 3 title variations. Pick the one with the highest "Curiosity Gap".
    
    TASK 2: DYNAMIC TAGGING
    Generate 15 highly specific SEO tags for this content.
    
    TASK 3: CATEGORY SELECTION
    Select the best Category ID: 
    - 27 (Education) for tutorials/wisdom.
    - 28 (Science & Tech) for news/tools.
    - 22 (People & Blogs) for business/personalities.
    
    TASK 4: AFFILIATE MATCHING
    {json.dumps(affiliate_offers, indent=2)}
    
    Return EXACTLY this JSON:
    {{
        "start_time": "MM:SS",
        "end_time": "MM:SS",
        "hook_text": "3-sec visual hook",
        "bridge_text": "Final CTA text",
        "title": "Winning Viral Title",
        "tags": ["tag1", "tag2", ...],
        "category_id": "27",
        "suggested_affiliate": "...",
        "youtube_description": "[Link] \n[Viral Hook] \n\nRelated: Watch more AI Business tools on our channel! \n\n#Shorts #AI #Business \n\nEdited with AI assistance.",
        "pinned_comment": "..."
    }}
    
    Context Segment:
    {transcript}
    """
    
    response2 = client.models.generate_content(model="gemini-flash-latest", contents=pass2_prompt)
    raw2 = response2.text.strip().replace("```json", "").replace("```", "").strip()
    task = json.loads(raw2)
    
    # VALIDATION: Strictly under 57 seconds
    s = parse_seconds(task['start_time'])
    e = parse_seconds(task['end_time'])
    duration = e - s
    
    if duration > 57:
        task['end_time'] = f"{int((s + 55)/60):02d}:{(s + 55)%60:02d}"
    elif duration < 30:
         task['end_time'] = f"{int((s + 45)/60):02d}:{(s + 45)%60:02d}"
         
    return task

def generate_autonomous_task(llm_api_key, youtube_api_key, scraper_api_key=None):
    print("AI Brain: Initiating autonomous video sourcing...")
    
    video_url, title = get_latest_video_from_channels()
    print(f"AI Brain: Found latest video: {title} ({video_url})")
    
    transcript = get_transcript(video_url, youtube_api_key, scraper_api_key)
    print("AI Brain: Transcript fetched. Analyzing with Gemini LLM...")
    
    task_data = extract_task_with_llm(video_url, transcript, llm_api_key)
    print(f"AI Brain: Extraction complete! Golden Nugget: {task_data['start_time']} - {task_data['end_time']}")
    
    return task_data
