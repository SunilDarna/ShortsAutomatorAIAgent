"""
ai_brain.py — Phase 3: Two-Pass Viral Hook Engine + Sourcing
v2.0 — Full implementation of the Two-Pass LLM Narrative Framework.

Pass 1: Semantic Mapping — Extract 3-5 high-value, contextually independent segments.
Pass 2: Hook & Loop Engineering — Engineer a "pattern interrupt" hook and seamless loop.

All existing yt-dlp scraping methods are preserved and extended.
"""
import subprocess
import time
import requests
import random
import json
import os
import re
from urllib.parse import quote
from google import genai
from google.genai import types
from googleapiclient.discovery import build

# ──────────────── Channel Tiers ───────────────────────────────────────────────

# 🌟 Viral Authority Tier (Priority Sources — Business/Wealth/Wisdom)
PRIORITY_CHANNELS = [
    "UCUyDOdBWhC1MCxEjC46d-zw",  # Alex Hormozi
    "UCGq-a57w-aPwyi3pW7XLiHw",  # The Diary of a CEO
    "UCxoRKax_0vHaulMbceZtAwA",  # My First Million
    "UCGX7nGXpz-CmO_Arg-cgJ7A",  # Codie Sanchez
    "UChfo46ZNOV-vtehDc25A1Ug",  # Ali Abdaal
    "UC3ov_5a1a1p4-1p9fL8P0Lw",  # Patrick Bet-David (Valuetainment)
    "UCQ4FNww3XoNgqIlkBqEAVCg",  # Iman Gadzhi
    "UCXC3etwvNkMBGrc6tcwu5oQ",  # Noah Kagan
    "UCa-ckhlKL98F8YXKQ-BALiw",  # Graham Stephan
    "UCctXZhXmG-kf3tlIXgVZUlw",  # GaryVee
]

# ⚙️ Technical & AI Tier (Secondary Sources — Tech/Tools)
SECONDARY_CHANNELS = [
    "UCawZsQWqfGSbCI5yjkdVkTA",  # Matthew Berman (AI/Tech)
    "UCTNDbjZLbTNFtBL3FAXUEQF",  # The AI Advantage
    "UCt6l0E-bBC1Z4d7C3qgh3cA",  # ColdFusion (Narrative Tech)
    "UCsBjURrPoezykLs9EqgamOA",  # Fireship (High retention tech)
    "UChpleBmo18P08aKCIgti38g",  # Matt Wolfe (AI Tools)
    "UCqcbQf6yw5KzRoDDcZ_wBSw",  # Wes Roth (AI News)
    "UCmZhTGgWGcgQ_zRUsMowPuw",  # ByteByteGo (System Design)
    "UCd6MoB9NC6uYN2grvUNT-Zg",  # AWS Events / re:Invent
    "UCMxNxyU0h6S0H0t-tL8FzNg",  # Y Combinator
    "UCNJ1Ymd5yFuUPtn21xtRbbw",  # AI Explained
    "UCCSrPWb7mjVUIPcxSbJ2SSA",  # Sam Despo (AI Biz)
    "UCnYMOamNKLGVlJgRUbamveA",  # Impact Theory
    "UCbfYPyITQ-7l4upoX8nvctg",  # Two Minute Papers
]

# ──────────────── Hook Type Definitions (for DB weighting) ───────────────────

HOOK_TYPES = [
    "Counter-Intuitive",   # Challenges a common belief → cognitive friction
    "Immediate-Reward",    # Promises a specific takeaway in 15s → reduces drop-off
    "Question-Hook",       # Opens a loop that must be closed → completion
    "Shock-Statistic",     # Surprising data point → shares & saves
    "Contrarian-Reframe",  # Inverts conventional wisdom → discussion
]

# ──────────────── Local Scraper (yt-dlp) — PRESERVED ─────────────────────────

def get_local_headers() -> dict:
    """Returns randomized browser headers to mimic a real user."""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    ]
    return {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }


def get_latest_video_from_channels(unused_key=None):
    """
    Uses local yt-dlp scraper to find the latest video from priority then secondary channels.
    Returns (video_url, title) or raises Exception.
    PRESERVED: No changes to this scraping method.
    """
    priority_pool = list(PRIORITY_CHANNELS)
    random.shuffle(priority_pool)
    full_pool = priority_pool + SECONDARY_CHANNELS

    for attempt, channel_id in enumerate(full_pool):
        tier = "PRIORITY" if attempt < len(PRIORITY_CHANNELS) else "SECONDARY"
        print(f"Local Scraper [{tier}]: Probing channel {channel_id}...")

        try:
            channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"
            cmd = [
                "python3", "-m", "yt_dlp",
                "--playlist-items", "1",
                "--get-id", "--get-title",
                "--flat-playlist",
                "--quiet", "--no-warnings",
                "--user-agent", get_local_headers()["User-Agent"],
                channel_url,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 2:
                    title    = lines[0]
                    video_id = lines[1]
                    return f"https://www.youtube.com/watch?v={video_id}", title
        except Exception as e:
            print(f"Local Scraper Error for {channel_id}: {e}")

    raise Exception("Local Scraper failed to find videos in both tiers.")


# ──────────────── Transcript Fetcher — PRESERVED & EXTENDED ──────────────────

from youtube_transcript_api import YouTubeTranscriptApi

def get_transcript(video_url: str, youtube_api_key: str, unused_key=None):
    """
    Fetch transcript. Returns (full_text_with_timestamps, raw_serializable_list).
    PRESERVED: Original logic intact; extended with robust entry normalization.
    """
    video_id = video_url.split("v=")[-1]
    print(f"Local Scraper: Fetching transcript for {video_id}...")

    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        transcript = transcript_list.find_transcript(["en"])
        transcript_data = transcript.fetch()

        full_text = ""
        serializable_data = []

        for entry in transcript_data:
            # Normalize: handle both dict-like and object forms
            if isinstance(entry, dict):
                start    = entry.get("start", 0)
                duration = entry.get("duration", 0)
                text     = entry.get("text", "").strip()
            else:
                start    = getattr(entry, "start", 0)
                duration = getattr(entry, "duration", 0)
                text     = getattr(entry, "text", "").strip()

            mins, secs = divmod(int(start), 60)
            timestamp  = f"[{mins:02d}:{secs:02d}]"
            if text:
                full_text += f"{timestamp} {text}\n"

            serializable_data.append({
                "start":    start,
                "duration": duration,
                "text":     text,
            })

        if full_text:
            return full_text, serializable_data

        raise Exception("Transcript was empty.")

    except Exception as e:
        print(f"Transcript Fetch failed: {e}")
        raise Exception(f"Failed to fetch transcript: {e}")


# ──────────────── Time Parsing ────────────────────────────────────────────────

def parse_seconds(time_str: str) -> float:
    """Convert MM:SS or HH:MM:SS or plain seconds string to float seconds."""
    try:
        parts = str(time_str).split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(time_str)
    except Exception:
        return 0.0


def seconds_to_mmss(seconds: float) -> str:
    """Convert float seconds to MM:SS string."""
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


# ──────────────── Pass 1: Semantic Heatmapping ────────────────────────────────

PASS1_SYSTEM_PROMPT = """You are a Viral Content Extraction Specialist for YouTube Shorts in 2026.
Your job is to find the EXACT moments in a transcript that will stop the scroll.

CRITERIA for a viral segment:
1. Contextual Independence — The viewer does NOT need context from the rest of the video.
2. Complete Narrative Arc — Has a clear setup, reveal, and resolution within 30-58 seconds.
3. Psychological Trigger — Must hit at least ONE of: Fear of Missing Out, Contrarian Surprise, Immediate Value, Shocking Statistic, or Curiosity Gap.
4. Affiliate Alignment — Segment should naturally connect to an AI, SaaS, automation, or business pain point.

OUTPUT: Return ONLY a valid JSON array with no markdown. Example:
[
  {"concept": "...", "start": "MM:SS", "end": "MM:SS", "hook_type": "Counter-Intuitive", "why_viral": "..."},
  {"concept": "...", "start": "MM:SS", "end": "MM:SS", "hook_type": "Shock-Statistic", "why_viral": "..."}
]"""


def _run_pass1(client, transcript: str, preferred_hook_type: str = None) -> list:
    """
    Pass 1: Semantic Heatmapping.
    Identifies 3-5 high-value, contextually independent segments from the transcript.
    """
    hook_bias = ""
    if preferred_hook_type:
        hook_bias = f"\nBIAS: Prioritize segments that fit the '{preferred_hook_type}' hook type, as historical data shows this performs best."

    prompt = f"""{PASS1_SYSTEM_PROMPT}{hook_bias}

Analyze this transcript and identify the 3-5 most viral-worthy segments.
Return ONLY valid JSON.

TRANSCRIPT:
{transcript[:18000]}
"""
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.7)
    )

    raw = response.text.strip()
    raw = re.sub(r"```json|```", "", raw).strip()

    try:
        concepts = json.loads(raw)
        print(f"AI Brain Pass 1: Found {len(concepts)} viral candidates.")
        return concepts
    except json.JSONDecodeError:
        # Fallback: extract a JSON array from the response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise Exception(f"Pass 1 JSON parsing failed. Raw: {raw[:200]}")


# ──────────────── Pass 2: Hook & Loop Engineering ─────────────────────────────

PASS2_SYSTEM_PROMPT = """You are a Precision Clip Architect, SEO Engineer, and Conversion Optimizer for YouTube Shorts.

Your objective is to engineer ONE perfect 40-57 second clip that:
1. HOOK (0-3s): Starts with a "Pattern Interrupt" — a statement that challenges the viewer's current mental state.
2. RETAIN (3-end): Maintains engagement through the narrative arc.
3. LOOP: The final sentence must grammatically and phonetically flow back into the hook line, creating a seamless passive replay loop. This is the single most important factor for achieving >100% APV.
4. CONVERT: The script must naturally mention a pain point that maps to a SaaS/AI tool.

HOOK TYPES you must use:
- Counter-Intuitive: "Nobody tells you [surprising truth]..."
- Immediate-Reward: "In the next 30 seconds, you'll learn exactly how to [outcome]..."
- Question-Hook: "What if [common assumption] is completely wrong?"
- Shock-Statistic: "[Number]% of [audience] don't know [shocking fact]..."
- Contrarian-Reframe: "Stop [common advice]. Here's what actually works..."

OUTPUT: Return ONLY strict JSON — no markdown, no extra text."""

PASS2_USER_TEMPLATE = """TARGET SEGMENT: {concept} at {start} — {end}
HOOK TYPE TO USE: {hook_type}
AFFILIATE OFFERS AVAILABLE: {affiliate_json}

Extract the exact dialogue window (40-57 seconds) and engineer the output.

Return EXACTLY this JSON structure:
{{
    "start_time": "MM:SS",
    "end_time": "MM:SS",
    "hook_type": "{hook_type}",
    "hook_text": "3-second visual pattern interrupt text (under 12 words)",
    "bridge_text": "Final 3-second CTA overlay text",
    "loop_opening_line": "The opening sentence engineered to loop back from the ending",
    "loop_closing_line": "The final sentence that flows back into hook_text",
    "title": "The winning viral title with maximum Curiosity Gap (under 60 chars)",
    "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"],
    "category_id": "28",
    "suggested_affiliate": "product name",
    "affiliate_pain_point": "exact pain point this clip addresses",
    "youtube_description": "Affiliate link goes here\\n\\nHook line from video.\\n\\nSubscribe for daily AI insights.\\n\\n#Shorts #AI #Business",
    "pinned_comment": "Soft CTA comment with affiliate link placeholder",
    "visual_prompts": ["Zoom in 120% at 0s", "Flash red text at 2s", "Cut pace: 2s intervals"],
    "why_this_stops_scroll": "One sentence explaining the psychological trigger"
}}

CONTEXT (transcript around target timestamps):
{context_transcript}"""


def _run_pass2(client, concept: dict, affiliate_offers: dict, transcript: str) -> dict:
    """
    Pass 2: Hook & Loop Engineering.
    Refines the target segment into a complete, engineered viral clip spec.
    """
    print(f"AI Brain Pass 2: Engineering hook for '{concept.get('concept', '')}' at {concept.get('start')}...")

    # Extract the relevant transcript window for context (±2 minutes)
    try:
        seg_start = parse_seconds(concept.get("start", "0:00"))
        seg_end   = parse_seconds(concept.get("end", "1:00"))
        context_lines = []
        for line in transcript.split("\n"):
            match = re.match(r"\[(\d+):(\d+)\]", line)
            if match:
                t = int(match.group(1)) * 60 + int(match.group(2))
                if (seg_start - 30) <= t <= (seg_end + 30):
                    context_lines.append(line)
        context_transcript = "\n".join(context_lines) if context_lines else transcript[:3000]
    except Exception:
        context_transcript = transcript[:3000]

    prompt = PASS2_SYSTEM_PROMPT + "\n\n" + PASS2_USER_TEMPLATE.format(
        concept=concept.get("concept", ""),
        start=concept.get("start", "0:00"),
        end=concept.get("end", "1:00"),
        hook_type=concept.get("hook_type", "Counter-Intuitive"),
        affiliate_json=json.dumps(affiliate_offers, indent=2),
        context_transcript=context_transcript,
    )

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.4)  # Lower temp for precision JSON
    )

    raw = response.text.strip()
    raw = re.sub(r"```json|```", "", raw).strip()

    try:
        task = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            task = json.loads(match.group())
        else:
            raise Exception(f"Pass 2 JSON parsing failed. Raw: {raw[:300]}")

    # ── Duration Validation & Correction ──────────────────────────────────────
    s = parse_seconds(task.get("start_time", concept.get("start", "0:00")))
    e = parse_seconds(task.get("end_time",   concept.get("end",   "1:00")))
    duration = e - s

    if duration > 57:
        e = s + 55
        task["end_time"] = seconds_to_mmss(e)
        print(f"  Duration clamped: {duration:.0f}s → 55s")
    elif duration < 30:
        e = s + 45
        task["end_time"] = seconds_to_mmss(e)
        print(f"  Duration extended: {duration:.0f}s → 45s")

    task["start_time"] = task.get("start_time", seconds_to_mmss(s))
    print(f"  Final clip: {task['start_time']} → {task['end_time']} ({int(parse_seconds(task['end_time']) - parse_seconds(task['start_time']))}s)")
    print(f"  Hook type: {task.get('hook_type')} | Hook: {task.get('hook_text', '')[:60]}")
    return task


# ──────────────── Validation Agent (Sub-LLM Scorer) ──────────────────────────

VALIDATOR_PROMPT = """You are a Viral Hook Validator for YouTube Shorts.
Score the following hook on a scale of 1-10 for:
- Scroll-Stop Power (does it create immediate curiosity?)
- Clarity (is it instantly understandable to a general audience?)
- Loop Quality (does the ending naturally connect back to the start?)

Return ONLY JSON: {{"scroll_stop": N, "clarity": N, "loop_quality": N, "total": N, "verdict": "PASS/FAIL"}}
PASS threshold: total >= 21 (out of 30).

Hook Text: "{hook_text}"
Loop Opening: "{loop_opening}"
Loop Closing: "{loop_closing}"
Hook Type: "{hook_type}"
"""

def _validate_hook(client, task: dict) -> bool:
    """
    Validation Agent: Sub-LLM that scores the hook before it reaches the video pipeline.
    Returns True if the hook passes the quality threshold.
    """
    try:
        prompt = VALIDATOR_PROMPT.format(
            hook_text=task.get("hook_text", ""),
            loop_opening=task.get("loop_opening_line", ""),
            loop_closing=task.get("loop_closing_line", ""),
            hook_type=task.get("hook_type", ""),
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        raw = re.sub(r"```json|```", "", response.text.strip()).strip()
        score_data = json.loads(raw)
        total = score_data.get("total", 0)
        verdict = score_data.get("verdict", "FAIL")
        print(f"  Hook Validator: Score {total}/30 → {verdict} "
              f"(Scroll={score_data.get('scroll_stop')}, "
              f"Clarity={score_data.get('clarity')}, "
              f"Loop={score_data.get('loop_quality')})")
        return verdict == "PASS"
    except Exception as e:
        print(f"  Hook Validator error (skipping): {e}")
        return True  # Fail open — don't block pipeline on validator error


# ──────────────── Main Entry: Two-Pass Engine ─────────────────────────────────

def extract_task_with_llm(video_url: str, transcript: str,
                          llm_api_key: str, affiliate_offers: dict,
                          preferred_hook_type: str = None) -> dict:
    """
    TWO-PASS VIRAL HOOK ENGINE with Validation Agent.

    Pass 1: Semantic Heatmapping — identify 3-5 high-value segments.
    Pass 2: Hook & Loop Engineering — engineer the winning clip.
    Validation: Sub-LLM scorer filters low-quality hooks before render.

    Returns the complete task dict ready for video_processor.
    """
    client = genai.Client(api_key=llm_api_key)

    # ── Pass 1 ────────────────────────────────────────────────────────────────
    concepts = _run_pass1(client, transcript, preferred_hook_type)
    if not concepts:
        raise Exception("Pass 1 returned no concepts.")

    # ── Pass 2: Try each concept until one passes validation ─────────────────
    best_task = None
    for i, concept in enumerate(concepts[:5]):
        print(f"\nAI Brain: Evaluating candidate {i+1}/{len(concepts[:5])}...")
        try:
            task = _run_pass2(client, concept, affiliate_offers, transcript)
            if _validate_hook(client, task):
                best_task = task
                print(f"  ✅ Candidate {i+1} accepted.")
                break
            else:
                print(f"  ❌ Candidate {i+1} failed validation. Trying next...")
        except Exception as e:
            print(f"  Pass 2 error for candidate {i+1}: {e}. Trying next...")
            continue

    if not best_task:
        # Last resort: use first concept without validation
        print("AI Brain: All candidates failed validation. Using best available.")
        best_task = _run_pass2(client, concepts[0], affiliate_offers, transcript)

    return best_task


# ──────────────── Autonomous Task Generator ───────────────────────────────────

def generate_autonomous_task(llm_api_key: str, youtube_api_key: str,
                             scraper_api_key=None, preferred_hook_type: str = None):
    """
    Full autonomous pipeline: discover → transcribe → two-pass extract.
    Returns (video_url, task_dict, transcript_raw).
    """
    print("AI Brain: Initiating autonomous video sourcing...")

    video_url, title = get_latest_video_from_channels()
    print(f"AI Brain: Found video: {title} ({video_url})")

    transcript_text, transcript_raw = get_transcript(video_url, youtube_api_key)
    print("AI Brain: Transcript fetched. Running Two-Pass Viral Hook Engine...")

    # Load affiliate offers for matching
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    affiliate_path = os.path.join(project_root, "affiliate_offers.json")
    affiliate_offers = {}
    if os.path.exists(affiliate_path):
        with open(affiliate_path) as f:
            affiliate_offers = json.load(f)

    task = extract_task_with_llm(
        video_url, transcript_text, llm_api_key, affiliate_offers, preferred_hook_type
    )
    task["transcript_raw"] = transcript_raw
    task["source_title"]   = title

    print(f"\nAI Brain: ✅ Complete! Clip: {task['start_time']} → {task['end_time']}")
    print(f"  Title: {task.get('title', '')}")
    print(f"  Hook: {task.get('hook_text', '')}")

    return video_url, task, transcript_raw
