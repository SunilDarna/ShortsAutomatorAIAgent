"""
local_production_pipeline.py — v3.0 Master Orchestrator
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
from app import content_scorer, smart_scheduler, caption_intelligence, youtube_analytics
from app import visual_retention

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

            source_metadata = content_scorer.collect_source_metadata(temp_url)
            if source_metadata.get("error"):
                print(f"Pipeline: Source intelligence unavailable: {source_metadata['error']}")
                source_metadata = {"url": temp_url, "title": temp_title, "source_score": 0.0}
            database.upsert_source_intelligence(temp_url, source_metadata)

            ranked_candidates = content_scorer.build_ranked_candidates(
                temp_transcript_raw,
                temp_url,
                source_metadata=source_metadata,
                used_segments=used_segments,
                limit=8,
            )
            if ranked_candidates:
                database.insert_candidate_segments(temp_url, ranked_candidates)
                print(
                    "Pipeline: Top candidate score "
                    f"{ranked_candidates[0]['virality_score']} at "
                    f"{ranked_candidates[0]['start_time']}–{ranked_candidates[0]['end_time']}"
                )

            # ── Two-Pass LLM + DB Overlap Guard (up to 5 attempts per video) ────────
            found_task = False
            for attempt in range(5):
                print(f"\nPipeline: LLM extraction attempt {attempt + 1}/5...")
                try:
                    potential_task = ai_brain.extract_task_with_llm(
                        temp_url, transcript_text,
                        secrets.get("llm_api_key", ""), affiliate_offers,
                        preferred_hook_type=preferred_hook,
                        used_segments=used_segments,
                        ranked_candidates=ranked_candidates,
                    )

                    s = ai_brain.parse_seconds(potential_task["start_time"])
                    e = ai_brain.parse_seconds(potential_task["end_time"])

                    # ── Agentic Rule: DB overlap check ────────────────────────────────
                    if database.is_segment_overlapping(temp_url, s, e):
                        print(f"  DB: Segment {potential_task['start_time']}–{potential_task['end_time']} "
                              f"overlaps existing clip. Retrying...")
                        continue

                    task = potential_task
                    matched_candidate = content_scorer.find_matching_candidate(task, ranked_candidates)
                    if matched_candidate:
                        task["candidate_id"] = matched_candidate.get("candidate_id", "")
                        task["candidate_score"] = matched_candidate.get("virality_score", 0.0)
                        task["source_score"] = matched_candidate.get("source_score", source_metadata.get("source_score", 0.0))
                        task["topic"] = matched_candidate.get("topic", "")
                        task["candidate_features"] = matched_candidate.get("features", {})
                    transcript_raw = temp_transcript_raw
                    task["transcript_raw"] = transcript_raw
                    task["source_metadata"] = source_metadata
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
    database.upsert_source_media(
        video_url,
        video_title,
        duration=int(task.get("source_metadata", {}).get("duration", 0) or 0),
        channel_id=task.get("source_metadata", {}).get("channel_id", ""),
    )

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
        "candidate_id":      task.get("candidate_id", ""),
        "candidate_score":   task.get("candidate_score", 0.0),
        "source_score":      task.get("source_score", 0.0),
        "topic":             task.get("topic", ""),
        "candidate_features": task.get("candidate_features", {}),
    })
    full_metadata = metadata_builder.ensure_affiliate_consistency(full_metadata, affiliate_offers)
    full_metadata["scheduling_recommendation"] = smart_scheduler.normalize_recommendation(
        full_metadata.get("scheduling_recommendation"),
        title=full_metadata.get("title", ""),
        tags=full_metadata.get("tags", []),
    )
    clip_duration = ai_brain.parse_seconds(task["end_time"]) - ai_brain.parse_seconds(task["start_time"])
    visual_plan = visual_retention.plan_visuals(full_metadata, clip_duration)
    full_metadata["visual_retention"] = {
        key: value for key, value in visual_plan.items()
        if key != "caption_style_pack"
    }

    # ── Stage clip in SQLite ──────────────────────────────────────────────────
    inserted = database.insert_clip(
        clip_id     = clip_id,
        parent_url  = video_url,
        start       = ai_brain.parse_seconds(task["start_time"]),
        end         = ai_brain.parse_seconds(task["end_time"]),
        hook_type   = task.get("hook_type", ""),
        hook_text   = task.get("hook_text", ""),
        title       = full_metadata["title"],
        candidate_id= task.get("candidate_id", ""),
        candidate_score=float(task.get("candidate_score", 0.0) or 0.0),
        source_score=float(task.get("source_score", 0.0) or 0.0),
        topic       = task.get("topic", ""),
        geography   = full_metadata.get("scheduling_recommendation", {}).get("geography", ""),
    )
    if not inserted:
        print("Pipeline: DB rejected clip because it overlaps an existing segment.")
        return False

    # ── Render Video ──────────────────────────────────────────────────────────
    try:
        render_context = video_processor.create_short(
            url           = video_url,
            start_time    = task["start_time"],
            end_time      = task["end_time"],
            bridge_text   = full_metadata["bridge_text"],
            output_path   = output_path,
            hook_text     = full_metadata["hook_text"],
            transcript_raw= transcript_raw,
            cta_overlay_text = full_metadata.get("cta_overlay_text", "Want this tool? Link in bio 👆"),
            affiliate_link= full_metadata.get("affiliate_link", ""),
            visual_plan = visual_plan,
        )
    except Exception as e:
        database.update_clip_failure(clip_id, str(e))
        print(f"Render failed: {e}")
        return False

    caption_detection = (render_context or {}).get("caption_detection", {})
    qa = caption_intelligence.run_render_qa(
        output_path,
        expected_min_duration=30.0,
        expected_max_duration=60.5,
        burned_in_captions=bool(caption_detection.get("burned_in_captions")),
        caption_zone=caption_detection.get("caption_zone", "none"),
    )
    database.log_render_qa(clip_id, qa)
    full_metadata["render_qa"] = qa
    full_metadata["caption_detection"] = caption_detection
    if not qa.get("passed"):
        database.update_clip_failure(clip_id, "; ".join(qa.get("warnings", [])))
        print(f"Render QA failed: {qa.get('warnings', [])}")
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
        print(f"Pipeline: AI recommended geography: {scheduling_rec.get('geography')} (UTC {scheduling_rec.get('utc_offset')})")
        try:
            # Get current queue
            queue = youtube_uploader.get_schedule_queue(
                secrets["youtube_client_id"], secrets["youtube_client_secret"], secrets["youtube_refresh_token"]
            )
            print(f"Pipeline: Current schedule queue has {len(queue)} videos.")
            
            history = database.get_schedule_slot_report(
                scheduling_rec.get("geography", ""),
                limit=6,
            )
            slot_decision = smart_scheduler.choose_publish_slot(
                scheduling_rec,
                queue,
                history=history,
                min_gap_hours=5,
            )
            publish_at_iso = slot_decision["publish_at"]
            meta["schedule_decision"] = slot_decision
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
            geography      = meta.get("schedule_decision", {}).get("geography", meta.get("scheduling_recommendation", {}).get("geography", "")),
        )

        # ── Update DB ─────────────────────────────────────────────────────────
        clip_id = meta.get("clip_id", base_name)
        database.update_clip_status(clip_id, "published", youtube_id)
        if publish_at_iso:
            database.update_clip_schedule(
                clip_id,
                publish_at_utc=publish_at_iso,
                geography=meta.get("schedule_decision", {}).get("geography", ""),
            )

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


def collect_analytics():
    print(f"\n{'='*60}")
    print(f"COLLECTING YOUTUBE ANALYTICS: {time.ctime()}")
    print(f"{'='*60}")

    secrets = load_json(SECRETS_FILE, {})
    if not secrets:
        print("Error: local_secrets.json not found.")
        return False

    clips = database.get_published_clips(limit=50)
    if not clips:
        print("No published clips with YouTube IDs found.")
        return True

    try:
        metrics_rows = youtube_analytics.collect_for_clips(
            secrets["youtube_client_id"],
            secrets["youtube_client_secret"],
            secrets["youtube_refresh_token"],
            clips,
            days_back=7,
        )
    except Exception as e:
        print(f"Analytics collection failed: {e}")
        return False

    by_clip_id = {clip["Clip_ID"]: clip for clip in clips}
    for metrics in metrics_rows:
        clip_id = metrics.get("clip_id")
        args = youtube_analytics.metrics_to_performance_args(metrics)
        database.log_performance(clip_id, **args)
        clip = by_clip_id.get(clip_id, {})
        if clip.get("Schedule_Slot_UTC"):
            database.log_schedule_performance(
                clip_id=clip_id,
                geography=clip.get("Geography") or "Unknown",
                local_hour=0,
                weekday=0,
                topic=clip.get("Topic") or "",
                publish_at_utc=clip.get("Schedule_Slot_UTC"),
                views_24h=args["views_24h"],
                avg_view_percentage=args["apv"],
                subscribers_gained=args["subs_gained"],
            )
    print(f"Analytics: Logged {len(metrics_rows)} performance snapshots.")
    return True


# ── run_immediate() ────────────────────────────────────────────────────────────

def run_immediate(force: bool = False):
    if produce():
        return sync()
    return False


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ShortsAutomatorAIAgent v3.0 — Autonomous Visual Retention Pipeline"
    )
    parser.add_argument(
        "action",
        choices=["produce", "sync", "run", "review", "collect-analytics"],
        help=(
            "produce: source + render a new Short | "
            "sync: upload pending Shorts to YouTube | "
            "run: produce + sync in sequence | "
            "review: print Hook Efficiency analytics report | "
            "collect-analytics: ingest YouTube Analytics for published clips"
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
    elif args.action == "collect-analytics":
        collect_analytics()
