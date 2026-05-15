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

    # ── Source: Find a fresh video via yt-dlp scraper ────────────────────────
    video_url   = None
    video_title = None

    for _ in range(30):
        try:
            temp_url, temp_title = ai_brain.get_latest_video_from_channels()
            video_url   = temp_url
            video_title = temp_title
            break
        except Exception as e:
            print(f"Sourcing attempt failed: {e}")
            continue

    if not video_url:
        print("Pipeline: No videos found from any channel.")
        return False

    v_id = video_url.split("v=")[-1]
    print(f"\nPipeline: Targeting '{video_title}' (ID: {v_id})")

    # Register source in DB
    database.upsert_source_media(video_url, video_title)

    # ── Transcript ────────────────────────────────────────────────────────────
    try:
        transcript_text, transcript_raw = ai_brain.get_transcript(
            video_url, secrets["youtube_api_key"]
        )
    except Exception as e:
        print(f"Transcript failed: {e}")
        return False

    # ── Two-Pass LLM + DB Overlap Guard (up to 5 attempts) ───────────────────
    task = None
    for attempt in range(5):
        print(f"\nPipeline: LLM extraction attempt {attempt + 1}/5...")
        try:
            potential_task = ai_brain.extract_task_with_llm(
                video_url, transcript_text,
                secrets["llm_api_key"], affiliate_offers,
                preferred_hook_type=preferred_hook
            )

            s = ai_brain.parse_seconds(potential_task["start_time"])
            e = ai_brain.parse_seconds(potential_task["end_time"])

            # ── Agentic Rule: DB overlap check ────────────────────────────────
            if database.is_segment_overlapping(video_url, s, e):
                print(f"  DB: Segment {potential_task['start_time']}–{potential_task['end_time']} "
                      f"overlaps existing clip. Retrying...")
                continue

            task = potential_task
            task["transcript_raw"] = transcript_raw
            print(f"  ✅ Non-overlapping segment confirmed by DB.")
            break

        except Exception as e:
            print(f"  LLM attempt {attempt + 1} failed: {e}")
            continue

    if not task:
        print("Pipeline: Could not find a valid non-overlapping segment after 5 attempts.")
        return False

    # ── Generate clip ID + file paths ─────────────────────────────────────────
    clip_id        = _generate_clip_id()
    video_filename = f"{clip_id}.mp4"
    srt_filename   = f"{clip_id}.srt"
    meta_filename  = f"{clip_id}.json"

    output_path = os.path.join(PENDING_DIR, video_filename)
    srt_path    = os.path.join(PENDING_DIR, srt_filename)
    meta_path   = os.path.join(PENDING_DIR, meta_filename)

    # ── Phase 4: Build complete metadata ─────────────────────────────────────
    full_metadata = metadata_builder.build_metadata(
        task, affiliate_offers, script_text=task.get("hook_text", "")
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

    # ── Check peak window ────────────────────────────────────────────────────
    if not metadata_builder.is_in_peak_window():
        scheduled = meta.get("scheduled_at", "")
        print(f"Pipeline: Not in peak window. Scheduled for: {scheduled}")
        print("Pipeline: Use --force to override scheduling.")
        # Continue anyway in non-interactive mode

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
