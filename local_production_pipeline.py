"""
local_production_pipeline.py — v2.0 Master Orchestrator
Event-driven pipeline replacing the linear stateless model.

Architecture:
  produce()  → Source → Transcribe → Two-Pass LLM → DB overlap check → Render → Stage
  sync()     → Pick pending → Upload → Post pinned comment → Mark published
  run()      → produce() + sync()
  review()   → Print Hook Efficiency Report from DB analytics
"""
import sys
import os
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import json
import time
import random
import argparse
import shutil
import uuid
from datetime import datetime

# ── App modules ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import ai_brain, video_processor, youtube_uploader
from app import database, metadata_builder

# ── File Configuration ────────────────────────────────────────────────────────
SECRETS_FILE   = "local_secrets.json"
AFFILIATE_FILE = "affiliate_offers.json"
PENDING_DIR    = "output/pending"
PUBLISHED_DIR  = "output/published"

# ── Startup: ensure dirs + DB schema ─────────────────────────────────────────
os.makedirs(PENDING_DIR,  exist_ok=True)
os.makedirs(PUBLISHED_DIR, exist_ok=True)
database.init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: str, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default


def _generate_clip_id() -> str:
    """Generate a unique clip identifier."""
    return f"clip_{int(time.time())}_{uuid.uuid4().hex[:8]}"


# ── produce() — Content Generation ───────────────────────────────────────────

def produce():
    print(f"\n{'='*60}")
    print(f"PRODUCING CONTENT: {time.ctime()}")
    print(f"{'='*60}")

    secrets = load_json(SECRETS_FILE, {})
    affiliate_offers = load_json(AFFILIATE_FILE, {})

    if not secrets:
        print("Error: local_secrets.json not found.")
        return False

    # ── Phase 1: Query DB for best-performing hook type ──────────────────────
    preferred_hook = database.get_best_hook_type()
    print(f"Pipeline: Using preferred hook type → '{preferred_hook}'")

    # ── Source: Iterate through all channels to find a fresh non-overlapping clip ──
    channels_dict = ai_brain.load_channels()
    priority_pool = list(channels_dict.get("PRIORITY_CHANNELS", []))
    secondary_pool = list(channels_dict.get("SECONDARY_CHANNELS", []))
    
    import random
    random.shuffle(priority_pool)
    full_pool = priority_pool + secondary_pool

    if not full_pool:
        print("Pipeline: No channels available in channels.json.")
        return False

    task = None
    video_url = None
    video_title = None

    for channel_id in full_pool:
        try:
            recent_videos = ai_brain.get_recent_videos_from_channel(channel_id, count=5)
        except Exception as e:
            print(f"Pipeline: Sourcing failed for {channel_id}: {e}")
            continue

        for temp_url, temp_title in recent_videos:
            v_id = temp_url.split("v=")[-1]
            print(f"\nPipeline: Targeting '{temp_title}' (ID: {v_id}) from channel {channel_id}")

            # ── Transcript ────────────────────────────────────────────────────────────
            try:
                transcript_text, temp_transcript_raw = ai_brain.get_transcript(
                    temp_url, secrets.get("youtube_api_key", "")
                )
            except Exception as e:
                print(f"Pipeline: Transcript failed for {v_id}: {e}")
                continue

            used_segments = database.get_all_used_segments(temp_url)
            if used_segments:
                print(f"Pipeline: Found {len(used_segments)} previously used segments for this video. Instructing AI to avoid them.")

            # ── Two-Pass LLM + DB Overlap Guard (up to 5 attempts per video) ────────
            found_task = False
            for attempt in range(5):
                print(f"\nPipeline: LLM extraction attempt {attempt + 1}/5...")
                try:
                    potential_task = ai_brain.extract_task_with_llm(
                        temp_url, transcript_text,
                        secrets.get("llm_api_key", ""), affiliate_offers,
                        preferred_hook_type=preferred_hook,
                        used_segments=used_segments
                    )

                    s = ai_brain.parse_seconds(potential_task["start_time"])
                    e = ai_brain.parse_seconds(potential_task["end_time"])

                    # ── Agentic Rule: DB overlap check ────────────────────────────────
                    if database.is_segment_overlapping(temp_url, s, e):
                        print(f"  DB: Segment {potential_task['start_time']}–{potential_task['end_time']} "
                              f"overlaps existing clip. Retrying...")
                        continue

                    task = potential_task
                    transcript_raw = temp_transcript_raw
                    task["transcript_raw"] = transcript_raw
                    video_url = temp_url
                    video_title = temp_title
                    found_task = True
                    print(f"  ✅ Non-overlapping segment confirmed by DB.")
                    break

                except Exception as e:
                    print(f"  LLM attempt {attempt + 1} failed: {e}")
                    continue

            if found_task:
                break
            else:
                print(f"Pipeline: Exhausted video {v_id}. Moving to next video in channel...")

        if found_task:
            break
        else:
            print(f"Pipeline: Exhausted all recent videos for channel {channel_id}. Moving to next channel...")

    if not task:
        print("\nPipeline: All current channels exhausted! Initiating self-healing discovery...")
        success = ai_brain.discover_new_channels(secrets.get("llm_api_key", ""))
        if success:
            print("Pipeline: Self-healing complete. Restarting produce() with new channels...")
            return produce()
        else:
            print("Pipeline: Self-healing failed. Cannot proceed.")
            return False

    # Register source in DB now that we have a valid task
    database.upsert_source_media(video_url, video_title)

    # ── Generate clip ID + file paths ─────────────────────────────────────────
    clip_id        = _generate_clip_id()
    video_filename = f"{clip_id}.mp4"
    srt_filename   = f"{clip_id}.srt"
    meta_filename  = f"{clip_id}.json"

    output_path = os.path.join(PENDING_DIR, video_filename)
    srt_path    = os.path.join(PENDING_DIR, srt_filename)
    meta_path   = os.path.join(PENDING_DIR, meta_filename)

    # ── Phase 4: Build complete metadata ─────────────────────────────────────
    llm_recommendation = ai_brain.get_scheduling_recommendation(
        secrets["llm_api_key"], video_title, task.get("hook_text", "")
    )
    
    full_metadata = metadata_builder.build_metadata(
        task, affiliate_offers, script_text=task.get("hook_text", ""),
        scheduling_recommendation=llm_recommendation
    )
    # Merge LLM task fields into metadata
    full_metadata.update({
        "clip_id":           clip_id,
        "original_video_id": v_id,
        "original_video_url": video_url,
        "source_title":      video_title,
        "start_time":        task["start_time"],
        "end_time":          task["end_time"],
        "hook_text":         task.get("hook_text", ""),
        "bridge_text":       task.get("bridge_text", "Want to automate this? Link in bio."),
        "hook_type":         task.get("hook_type", ""),
        "loop_opening_line": task.get("loop_opening_line", ""),
        "loop_closing_line": task.get("loop_closing_line", ""),
        "tags":              task.get("tags", full_metadata.get("tags", [])),
        "category_id":       task.get("category_id", "28"),
        "pinned_comment":    task.get("pinned_comment", full_metadata.get("pinned_comment", "")),
        "visual_prompts":    task.get("visual_prompts", []),
        "title":             task.get("title", full_metadata["title"]),
    })
    # Ensure uploader-compatible description key
    full_metadata["youtube_description"] = full_metadata.get("description", "")

    # ── Stage clip in SQLite ──────────────────────────────────────────────────
    database.insert_clip(
        clip_id     = clip_id,
        parent_url  = video_url,
        start       = ai_brain.parse_seconds(task["start_time"]),
        end         = ai_brain.parse_seconds(task["end_time"]),
        hook_type   = task.get("hook_type", ""),
        hook_text   = task.get("hook_text", ""),
        title       = full_metadata["title"],
    )

    # ── Render Video ──────────────────────────────────────────────────────────
    try:
        video_processor.create_short(
            url           = video_url,
            start_time    = task["start_time"],
            end_time      = task["end_time"],
            bridge_text   = full_metadata["bridge_text"],
            output_path   = output_path,
            hook_text     = full_metadata["hook_text"],
            transcript_raw= transcript_raw,
            cta_overlay_text = full_metadata.get("cta_overlay_text", "Want this tool? Link in bio 👆"),
            affiliate_link= full_metadata.get("affiliate_link", ""),
        )
    except Exception as e:
        database.update_clip_status(clip_id, "failed")
        print(f"Render failed: {e}")
        return False

    # ── Generate SRT for SEO ──────────────────────────────────────────────────
    video_processor.generate_srt(transcript_raw, task["start_time"], task["end_time"], srt_path)

    # ── Save metadata JSON ────────────────────────────────────────────────────
    # Remove non-serializable fields before saving
    save_meta = {k: v for k, v in full_metadata.items()
                 if k not in ("transcript_raw",) and not callable(v)}
    metadata_builder.save_metadata_json(save_meta, meta_path)

    print(f"\n✅ Pipeline: SUCCESS")
    print(f"   Clip ID:  {clip_id}")
    print(f"   Title:    {full_metadata['title']}")
    print(f"   Hook:     {full_metadata['hook_text']}")
    print(f"   Clip:     {task['start_time']} → {task['end_time']}")
    print(f"   Staged:   {PENDING_DIR}")
    print(f"   Scheduled: {full_metadata.get('scheduled_at', 'ASAP')}")
    return True


# ── sync() — Upload & Publish ─────────────────────────────────────────────────

def sync():
    print(f"\n{'='*60}")
    print(f"SYNCING TO YOUTUBE: {time.ctime()}")
    print(f"{'='*60}")

    secrets = load_json(SECRETS_FILE, {})
    if not secrets:
        print("Error: local_secrets.json not found.")
        return False

    # Get all pending metadata files
    pending_files = sorted(
        [f for f in os.listdir(PENDING_DIR) if f.endswith(".json")],
        reverse=False  # Oldest first (FIFO queue)
    )

    if not pending_files:
        print("Pipeline: All videos are in sync. Nothing to upload.")
        return True

    target_meta_file  = pending_files[0]
    base_name         = target_meta_file.replace(".json", "")
    target_video_file = base_name + ".mp4"
    target_srt_file   = base_name + ".srt"

    meta_path  = os.path.join(PENDING_DIR, target_meta_file)
    video_path = os.path.join(PENDING_DIR, target_video_file)
    srt_path   = os.path.join(PENDING_DIR, target_srt_file)

    if not os.path.exists(video_path):
        print(f"Error: Video file missing for {target_meta_file}")
        return False

    with open(meta_path, "r") as f:
        meta = json.load(f)

    print(f"Uploading: {meta.get('title', 'Unknown')}")
    print(f"Hook Type: {meta.get('hook_type', 'N/A')}")

    # ── Calculate Next Valid Schedule ────────────────────────────────────────
    scheduling_rec = meta.get("scheduling_recommendation")
    publish_at_iso = None
    
    if scheduling_rec:
        print(f"Pipeline: AI recommended time: {scheduling_rec.get('time_of_day')} (UTC {scheduling_rec.get('utc_offset')})")
        try:
            # Get current queue
            queue = youtube_uploader.get_schedule_queue(
                secrets["youtube_client_id"], secrets["youtube_client_secret"], secrets["youtube_refresh_token"]
            )
            print(f"Pipeline: Current schedule queue has {len(queue)} videos.")
            
            # Find next valid slot
            from datetime import datetime, timedelta, timezone
            
            # Parse recommended time (e.g., "18:00")
            time_parts = scheduling_rec.get("time_of_day", "18:00").split(":")
            rec_hour = int(time_parts[0])
            rec_minute = int(time_parts[1]) if len(time_parts) > 1 else 0
            
            # Parse UTC offset (e.g., "+0530" or "+05:30")
            offset_str = scheduling_rec.get("utc_offset", "+0000").replace(":", "")
            sign = -1 if offset_str.startswith("-") else 1
            offset_hours = int(offset_str[1:3])
            offset_mins = int(offset_str[3:5])
            tz = timezone(timedelta(hours=sign * offset_hours, minutes=sign * offset_mins))
            
            # Find the latest scheduled time in UTC
            now_utc = datetime.now(timezone.utc)
            latest_scheduled_utc = now_utc
            if queue:
                # queue contains strings like '2026-05-15T18:00:00Z'
                queue_latest = datetime.strptime(queue[-1].replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
                # Ensure we only consider future queue items
                if queue_latest > latest_scheduled_utc:
                    latest_scheduled_utc = queue_latest
            
            # We want at least a 6 hour gap from the latest scheduled video
            MIN_GAP_HOURS = 6
            
            candidate_date = latest_scheduled_utc.astimezone(tz)
            candidate_slot = candidate_date.replace(hour=rec_hour, minute=rec_minute, second=0, microsecond=0)
            
            # Minimum allowed time is whichever is later: 6 hours from the queue, OR right now
            min_allowed_utc = latest_scheduled_utc + timedelta(hours=MIN_GAP_HOURS)
            if min_allowed_utc < now_utc:
                min_allowed_utc = now_utc
                
            # If the candidate slot is in the past or within the minimum gap, push to next day
            while candidate_slot.astimezone(timezone.utc) < min_allowed_utc:
                candidate_slot += timedelta(days=1)
                
            publish_at_iso = candidate_slot.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"Pipeline: Final computed schedule: {publish_at_iso} UTC")
            
        except Exception as e:
            print(f"Pipeline: Failed to calculate schedule from recommendation. Error: {e}")
            publish_at_iso = None

    try:
        youtube_id = youtube_uploader.upload_to_youtube(
            video_path     = video_path,
            title          = meta["title"],
            description    = meta["youtube_description"],
            client_id      = secrets["youtube_client_id"],
            client_secret  = secrets["youtube_client_secret"],
            refresh_token  = secrets["youtube_refresh_token"],
            tags           = meta.get("tags"),
            category_id    = meta.get("category_id", "28"),
            srt_path       = srt_path if os.path.exists(srt_path) else None,
            publish_at     = publish_at_iso,
        )

        # ── Update DB ─────────────────────────────────────────────────────────
        clip_id = meta.get("clip_id", base_name)
        database.update_clip_status(clip_id, "published", youtube_id)

        # ── Print actionable pinned comment ──────────────────────────────────
        print(f"\n📌 PINNED COMMENT (post manually in YouTube Studio):")
        print(f"   {meta.get('pinned_comment', '')}")
        print(f"\n🔗 Video live at: https://youtube.com/watch?v={youtube_id}")

        # ── Move to published folder ──────────────────────────────────────────
        for src, fname in [
            (meta_path,  target_meta_file),
            (video_path, target_video_file),
        ]:
            shutil.move(src, os.path.join(PUBLISHED_DIR, fname))

        if os.path.exists(srt_path):
            shutil.move(srt_path, os.path.join(PUBLISHED_DIR, target_srt_file))

        print(f"\n✅ Sync complete. Published → {PUBLISHED_DIR}")
        return True

    except Exception as e:
        print(f"Sync failed: {e}")
        return False


# ── review() — Analytics Intelligence Report ──────────────────────────────────

def review():
    print(f"\n{'='*60}")
    print(f"HOOK EFFICIENCY INTELLIGENCE REPORT: {time.ctime()}")
    print(f"{'='*60}")

    report = database.get_hook_efficiency_report()
    if not report:
        print("No performance data yet. Run produce → sync → log analytics first.")
        return

    print(f"\n{'Hook Type':<25} {'Avg HES':>8} {'Avg Stayed%':>12} {'Avg APV%':>10} {'Samples':>8}")
    print("-" * 70)
    for row in report:
        print(
            f"{row.get('Hook_Type', 'N/A'):<25} "
            f"{row.get('avg_hes', 0.0):>8.2f} "
            f"{row.get('avg_stayed', 0.0):>12.1f}% "
            f"{row.get('avg_apv', 0.0):>10.1f}% "
            f"{row.get('sample_count', 0):>8}"
        )

    best = report[0] if report else None
    if best:
        print(f"\n🏆 Best Hook Type: '{best.get('Hook_Type')}' "
              f"(HES={best.get('avg_hes', 0.0):.2f})")
        print("   This type will be prioritized in future production runs.")

    print(f"\nDB Path: {database.DB_PATH}")


# ── run_immediate() ────────────────────────────────────────────────────────────

def run_immediate(force: bool = False):
    if produce():
        return sync()
    return False


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ShortsAutomatorAIAgent v2.0 — Autonomous Affiliate Pipeline"
    )
    parser.add_argument(
        "action",
        choices=["produce", "sync", "run", "review"],
        help=(
            "produce: source + render a new Short | "
            "sync: upload pending Shorts to YouTube | "
            "run: produce + sync in sequence | "
            "review: print Hook Efficiency analytics report"
        )
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Override peak-window scheduling check during sync"
    )

    args = parser.parse_args()

    if args.action == "produce":
        produce()
    elif args.action == "sync":
        sync()
    elif args.action == "run":
        run_immediate(force=args.force)
    elif args.action == "review":
        review()
