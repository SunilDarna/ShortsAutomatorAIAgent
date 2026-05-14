import sys
import os
import warnings
# Suppress deprecated warnings from Python 3.9 and Google/Boto3 libraries
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
import json
import time
import random
import argparse
import shutil
from app import ai_brain, video_processor, youtube_uploader

# Local File Configuration
SECRETS_FILE = "local_secrets.json"
AFFILIATE_FILE = "affiliate_offers.json"
HISTORY_FILE = "processed_videos.json"
PENDING_DIR = "output/pending"
PUBLISHED_DIR = "output/published"

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default

def save_history(video_id, start_time_str, end_time_str):
    history = load_json(HISTORY_FILE, {})
    
    # Ensure history is a dict (handles transition from old list format)
    if not isinstance(history, dict):
        history = {}
        
    start_sec = video_processor.parse_time(start_time_str)
    end_sec = video_processor.parse_time(end_time_str)
    
    if video_id not in history:
        history[video_id] = []
    
    history[video_id].append({"start": start_sec, "end": end_sec})
    
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def is_overlapping(video_id, new_start_str, new_end_str, history):
    if video_id not in history or not isinstance(history, dict):
        return False
        
    new_start = video_processor.parse_time(new_start_str)
    new_end = video_processor.parse_time(new_end_str)
    
    for segment in history[video_id]:
        prev_start = segment['start']
        prev_end = segment['end']
        
        # Check for any overlap: (StartA < EndB) and (EndA > StartB)
        if (new_start < prev_end) and (new_end > prev_start):
            return True
    return False

def produce():
    print(f"\n--- PRODUCING CONTENT: {time.ctime()} ---")
    secrets = load_json(SECRETS_FILE, {})
    affiliate_offers = load_json(AFFILIATE_FILE, {})
    
    if not secrets:
        print("Error: local_secrets.json not found.")
        return False

    history = load_json(HISTORY_FILE, {})
    video_url = None
    video_title = None
    
    # Sourcing: Find a video that isn't completely exhausted
    # Note: We now allow re-using videos if segments don't overlap
    for _ in range(30):
        try:
            temp_url, temp_title = ai_brain.get_latest_video_from_channels()
            # For now, we still prefer fresh videos, but we'll accept re-discovery 
            # if the LLM can find a non-overlapping segment later.
            video_url = temp_url
            video_title = temp_title
            break
        except:
            continue

    if not video_url:
        print("No new videos found.")
        return False

    v_id = video_url.split("v=")[-1]
    print(f"Targeting: {video_title} (ID: {v_id})")
    
    try:
        # Two-Pass Viral Hook Engine will be implemented in ai_brain.py
        # Here we just handle the results and overlap check
        transcript_text, transcript_raw = ai_brain.get_transcript(video_url, secrets['youtube_api_key'])
        
        # Try to find a non-overlapping segment
        task = None
        for attempt in range(3):
            potential_task = ai_brain.extract_task_with_llm(video_url, transcript_text, secrets['llm_api_key'], affiliate_offers)
            
            if not is_overlapping(v_id, potential_task['start_time'], potential_task['end_time'], history):
                task = potential_task
                break
            print(f"Overlap detected for segment {potential_task['start_time']}-{potential_task['end_time']}. Retrying LLM...")
            
        if not task:
            print(f"Could not find a unique segment for {v_id} after 3 attempts.")
            return False
            
        # Inject raw transcript for video processing
        task['transcript_raw'] = transcript_raw
        
        timestamp = int(time.time())
        video_filename = f"video_{timestamp}.mp4"
        meta_filename = f"video_{timestamp}.json"
        srt_filename = f"video_{timestamp}.srt"
        
        output_path = os.path.join(PENDING_DIR, video_filename)
        srt_path = os.path.join(PENDING_DIR, srt_filename)
        
        # 1. Generate Video
        video_processor.create_short(video_url, task['start_time'], task['end_time'], task['bridge_text'], output_path, task.get('hook_text', ""), task.get('transcript_raw'))
        
        # 2. Generate SRT for SEO indexing
        video_processor.generate_srt(task['transcript_raw'], task['start_time'], task['end_time'], srt_path)
        
        # Save metadata
        task['original_video_id'] = v_id
        with open(os.path.join(PENDING_DIR, meta_filename), "w") as f:
            json.dump(task, f, indent=4)
            
        print(f"SUCCESS: Video generated and staged with SEO metadata in {PENDING_DIR}")
        return True
    except Exception as e:
        print(f"Production Failed: {e}")
        return False

def sync():
    print(f"\n--- SYNCING TO YOUTUBE: {time.ctime()} ---")
    secrets = load_json(SECRETS_FILE, {})
    
    # Get all pending JSON files
    pending_files = [f for f in os.listdir(PENDING_DIR) if f.endswith(".json")]
    if not pending_files:
        print("All videos are in sync.")
        return True

    # Sort by timestamp (latest first)
    pending_files.sort(reverse=True)
    target_meta_file = pending_files[0]
    base_name = target_meta_file.replace(".json", "")
    target_video_file = base_name + ".mp4"
    target_srt_file = base_name + ".srt"
    
    meta_path = os.path.join(PENDING_DIR, target_meta_file)
    video_path = os.path.join(PENDING_DIR, target_video_file)
    srt_path = os.path.join(PENDING_DIR, target_srt_file)
    
    if not os.path.exists(video_path):
        print(f"Error: Metadata exists but video {target_video_file} is missing.")
        return False

    with open(meta_path, "r") as f:
        task = json.load(f)

    print(f"Uploading latest un-uploaded video: {task['title']}")
    
    try:
        youtube_uploader.upload_to_youtube(
            video_path, 
            task['title'], 
            task['youtube_description'],
            secrets['youtube_client_id'],
            secrets['youtube_client_secret'],
            secrets['youtube_refresh_token'],
            tags=task.get('tags'),
            category_id=task.get('category_id', "27"),
            srt_path=srt_path
        )
        
        print(f"PINNED COMMENT DRAFT: {task['pinned_comment']}")
        
        # Mark as published (Updated with start/end times)
        save_history(task['original_video_id'], task['start_time'], task['end_time'])
        
        # Move to published folder
        shutil.move(meta_path, os.path.join(PUBLISHED_DIR, target_meta_file))
        shutil.move(video_path, os.path.join(PUBLISHED_DIR, target_video_file))
        if os.path.exists(srt_path):
            shutil.move(srt_path, os.path.join(PUBLISHED_DIR, target_srt_file))
        
        print("Sync Complete.")
        return True
    except Exception as e:
        print(f"Sync Failed: {e}")
        return False

def run_immediate():
    if produce():
        # Find the one we just produced and sync it
        return sync()
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Affiliate Pipeline Control")
    parser.add_argument("action", choices=["produce", "sync", "run"], help="Action to perform")
    
    args = parser.parse_args()
    
    if args.action == "produce":
        produce()
    elif args.action == "sync":
        sync()
    elif args.action == "run":
        run_immediate()
