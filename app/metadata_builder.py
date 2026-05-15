"""
metadata_builder.py — Phase 4: Affiliate Integration & Metadata Automation
Generates all upload metadata: title, description, pinned comment,
tags, category ID, and 3-second CTA overlay spec.
"""
import json
import os
from datetime import datetime

# ──────────────── Affiliate Offer Loader ──────────────────────────────────────

def load_affiliate_offers(path: str = None) -> dict:
    """Load the affiliate_offers.json from the project root."""
    if path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(project_root, "affiliate_offers.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


# ──────────────── Semantic Topic → Affiliate Matching ─────────────────────────

TOPIC_CATEGORY_MAP = {
    "ai": "productivity",
    "automation": "business_automation",
    "writing": "productivity",
    "content": "productivity",
    "marketing": "marketing",
    "ads": "marketing",
    "crm": "business_automation",
    "workflow": "business_automation",
    "video": "video_editing",
    "edit": "video_editing",
    "podcast": "video_editing",
    "business": "business_automation",
    "startup": "business_automation",
    "money": "business_automation",
    "revenue": "business_automation",
    "growth": "marketing",
    "saas": "productivity",
    "tool": "productivity",
    "software": "productivity",
}

def match_affiliate(script_text: str, offers: dict) -> dict:
    if not offers:
        return {"name": "Jasper AI", "link": "https://jasper.ai", "problem_solved": "Content creation"}

    text_lower = script_text.lower()
    scores = {cat: 0 for cat in offers}

    for keyword, category in TOPIC_CATEGORY_MAP.items():
        if keyword in text_lower and category in scores:
            scores[category] += text_lower.count(keyword)

    best_category = max(scores, key=scores.get) if any(scores.values()) else list(offers.keys())[0]
    offer = offers.get(best_category, list(offers.values())[0])
    print(f"Metadata: Matched affiliate '{offer['name']}' for category '{best_category}'.")
    return offer

# ──────────────── Metadata Assembly ──────────────────────────────────────────

def build_metadata(task: dict, affiliate_offers: dict, script_text: str = "", scheduling_recommendation: dict = None) -> dict:
    """
    Assemble the complete upload metadata package for a clip.
    scheduling_recommendation comes from the LLM (geography, time_of_day, timezone).
    """
    offer = match_affiliate(script_text or task.get("hook_text", ""), affiliate_offers)

    title    = task.get("title", "AI Just Changed Everything #Shorts")
    hook     = task.get("hook_text", "")
    bridge   = task.get("bridge_text", "Want to automate this? Link in bio.")
    tags     = task.get("tags", [])
    cat_id   = task.get("category_id", "28")

    # ── Rich Description (affiliate link in first 2 lines) ──────────────────
    affiliate_line = f"🔗 Get {offer['name']}: {offer['link']}"
    description = (
        f"{affiliate_line}\n"
        f"{hook}\n\n"
        f"This clip reveals a high-impact insight from the world of AI and automation. "
        f"{offer['name']} solves the exact problem discussed: {offer['problem_solved']}.\n\n"
        f"📌 Subscribe for daily AI & Business insights.\n\n"
        f"#{' #'.join(tags[:5]) if tags else 'AI #Shorts #Business #Automation #Tech'}\n\n"
        f"Edited with AI assistance. Educational purposes only."
    )

    # ── Pinned Comment (highest-converting placement) ────────────────────────
    pinned_comment = (
        f"🤖 Want to automate what's discussed here? "
        f"I use {offer['name']} — it solves exactly this: {offer['problem_solved']}. "
        f"Link: {offer['link']}"
    )

    # ── 3-Second CTA Overlay Text ────────────────────────────────────────────
    cta_overlay_text = f"Want this tool? Link in bio 👆"

    # ── Auto-generated SEO tags ──────────────────────────────────────────────
    base_tags = ["Shorts", "AI", "Business", "Automation", "Wealth", "Tech2026",
                 "AITools", "SaaS", "DigitalMarketing", "Productivity"]
    final_tags = list(dict.fromkeys(tags + base_tags))[:15]

    metadata = {
        "title":              title,
        "description":        description,
        "tags":               final_tags,
        "category_id":        cat_id,
        "pinned_comment":     pinned_comment,
        "cta_overlay_text":   cta_overlay_text,
        "affiliate_name":     offer["name"],
        "affiliate_link":     offer["link"],
        "youtube_description": description,
    }
    
    # Store LLM recommendation for sync phase
    if scheduling_recommendation:
        metadata["scheduling_recommendation"] = scheduling_recommendation

    return metadata

def save_metadata_json(metadata: dict, output_path: str):
    """Write the metadata bundle to a JSON file alongside the video."""
    with open(output_path, "w") as f:
        json.dump(metadata, f, indent=4, default=str)
    print(f"Metadata: Saved to {output_path}")
