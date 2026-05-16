"""
visual_retention.py — smart first-frame, caption, and CTA planning.

This module keeps visual choices deterministic and metadata-friendly. It does
not render anything by itself; it gives the video processor a compact plan.
"""
import re
from typing import Dict, List


FINANCE_TERMS = {"stock", "market", "buffett", "invest", "finance", "money", "housing", "revenue"}
AI_TERMS = {"ai", "automation", "tool", "software", "chatgpt", "agent", "workflow"}
BUSINESS_TERMS = {"business", "sales", "growth", "startup", "marketing", "customer", "brand"}
MYSTERY_TERMS = {"ufo", "alien", "mystery", "cia", "classified", "coverup"}

POWER_WORDS = {
    "ai", "money", "market", "wrong", "broken", "secret", "never", "nobody",
    "stop", "mistake", "million", "billion", "growth", "sales", "system",
    "strategy", "rule", "truth", "failed", "win", "risk", "expensive",
}


STYLE_PACKS = {
    "clean_finance": {
        "caption_primary": "&H00FFFFFF",
        "caption_accent": "&H0000FFFF",
        "caption_outline": "&H00000000",
        "font_size": 54,
        "cta_color": "yellow",
        "cta_box": "black@0.78",
    },
    "ai_neon": {
        "caption_primary": "&H00FFFFFF",
        "caption_accent": "&H00FFFF00",
        "caption_outline": "&H00000000",
        "font_size": 54,
        "cta_color": "cyan",
        "cta_box": "black@0.82",
    },
    "business_bold": {
        "caption_primary": "&H00FFFFFF",
        "caption_accent": "&H0000FFFF",
        "caption_outline": "&H00000000",
        "font_size": 56,
        "cta_color": "yellow",
        "cta_box": "black@0.80",
    },
    "shock_red": {
        "caption_primary": "&H00FFFFFF",
        "caption_accent": "&H000000FF",
        "caption_outline": "&H00000000",
        "font_size": 56,
        "cta_color": "white",
        "cta_box": "red@0.88",
    },
    "tutorial_save": {
        "caption_primary": "&H00FFFFFF",
        "caption_accent": "&H0000FFFF",
        "caption_outline": "&H00000000",
        "font_size": 52,
        "cta_color": "yellow",
        "cta_box": "black@0.76",
    },
}


def _token_set(*parts) -> set:
    text = " ".join(str(part or "") for part in parts)
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))


def choose_caption_style(title: str = "", hook_text: str = "", tags: List[str] = None) -> str:
    tags = tags or []
    tokens = _token_set(title, hook_text, " ".join(tags))
    if tokens & MYSTERY_TERMS:
        return "shock_red"
    if tokens & FINANCE_TERMS:
        return "clean_finance"
    if tokens & BUSINESS_TERMS:
        return "business_bold"
    if tokens & AI_TERMS:
        return "ai_neon"
    return "tutorial_save"


def thumbnail_text_from_hook(hook_text: str, title: str = "") -> str:
    source = hook_text or title or "Watch This"
    source = re.sub(r"[^\w\s%$.-]", "", source).strip()
    words = source.split()
    if len(words) <= 6:
        return source.upper()

    priority = []
    for word in words:
        clean = re.sub(r"[^a-zA-Z0-9%$]", "", word)
        if clean.lower() in POWER_WORDS or re.search(r"\d|%|\$", clean):
            priority.append(word)

    selected = priority[:4]
    if len(selected) < 3:
        selected = words[:5]
    return " ".join(selected[:6]).upper()


def choose_cta(title: str = "", hook_text: str = "", tags: List[str] = None,
               duration: float = 45.0) -> Dict:
    tags = tags or []
    tokens = _token_set(title, hook_text, " ".join(tags))
    if tokens & FINANCE_TERMS:
        cta_type = "follow"
        text = "Follow for market breakdowns"
    elif tokens & BUSINESS_TERMS:
        cta_type = "save"
        text = "Save this growth system"
    elif tokens & AI_TERMS:
        cta_type = "follow"
        text = "Follow for AI tools"
    elif tokens & MYSTERY_TERMS:
        cta_type = "follow"
        text = "Follow before this changes"
    else:
        cta_type = "save"
        text = "Save this insight"

    start = max(6.0, min(duration - 4.0, duration * 0.76))
    end = min(duration, start + 2.4)
    return {
        "cta_type": cta_type,
        "cta_text": text,
        "cta_start": round(start, 2),
        "cta_end": round(end, 2),
        "cta_motion": "pop",
    }


def plan_visuals(metadata: Dict, duration: float) -> Dict:
    title = metadata.get("title", "")
    hook = metadata.get("hook_text", "")
    tags = metadata.get("tags", [])
    caption_style = choose_caption_style(title, hook, tags)
    style_pack = STYLE_PACKS[caption_style]
    cta = choose_cta(title, hook, tags, duration)
    return {
        "thumbnail_text": thumbnail_text_from_hook(hook, title),
        "thumbnail_style": "proof" if caption_style == "clean_finance" else "curiosity",
        "caption_style": caption_style,
        "caption_effects": ["keyword_highlight", "stroke", "shadow", "short_beats"],
        "caption_style_pack": style_pack,
        **cta,
        "visual_density_score": 0.0,
    }


def keyword_set_for_text(text: str) -> set:
    words = set(re.findall(r"[a-zA-Z0-9%$]+", text.lower()))
    return words & POWER_WORDS
