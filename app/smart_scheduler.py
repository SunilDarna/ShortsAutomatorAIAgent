"""
smart_scheduler.py — Queue-aware, geography-aware scheduling.

The LLM can suggest audience intent, but final scheduling should be stable,
schema-safe, and able to use historical slot performance when available.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List


DEFAULT_SLOT_PACKS = {
    "india": {
        "geography": "India",
        "utc_offset": "+05:30",
        "recommended_slots": ["08:30", "13:30", "20:30"],
    },
    "united states": {
        "geography": "United States",
        "utc_offset": "-05:00",
        "recommended_slots": ["08:00", "13:00", "19:30"],
    },
    "global": {
        "geography": "Global",
        "utc_offset": "+00:00",
        "recommended_slots": ["06:30", "13:00", "18:30"],
    },
}


def _normalize_offset(offset: str) -> str:
    offset = str(offset or "+00:00").strip()
    if len(offset) == 5 and offset[0] in "+-" and offset[3:].isdigit():
        return f"{offset[:3]}:{offset[3:]}"
    if len(offset) == 6 and offset[0] in "+-" and offset[3] == ":":
        return offset
    return "+00:00"


def _offset_timezone(offset: str) -> timezone:
    offset = _normalize_offset(offset)
    sign = -1 if offset.startswith("-") else 1
    hours = int(offset[1:3])
    minutes = int(offset[4:6])
    return timezone(timedelta(hours=sign * hours, minutes=sign * minutes))


def normalize_recommendation(rec: Dict = None, title: str = "", tags: List[str] = None) -> Dict:
    """
    Accept old and new metadata shapes and return one scheduler-safe structure.
    """
    rec = rec or {}
    tags = tags or []
    text = f"{title} {' '.join(tags)} {rec.get('geography', '')}".lower()

    if "india" in text or not rec.get("geography"):
        base = DEFAULT_SLOT_PACKS["india"].copy()
    elif "usa" in text or "united states" in text or "america" in text:
        base = DEFAULT_SLOT_PACKS["united states"].copy()
    else:
        base = DEFAULT_SLOT_PACKS["global"].copy()

    slots = rec.get("recommended_slots")
    if not slots and rec.get("time_of_day"):
        slots = [rec["time_of_day"]]
    if not slots:
        slots = base["recommended_slots"]

    normalized_slots = []
    for slot in slots:
        try:
            h, m = map(int, str(slot).split(":")[:2])
            if 0 <= h <= 23 and 0 <= m <= 59:
                normalized_slots.append(f"{h:02d}:{m:02d}")
        except Exception:
            continue

    return {
        "geography": rec.get("geography") or base["geography"],
        "recommended_slots": normalized_slots or base["recommended_slots"],
        "utc_offset": _normalize_offset(rec.get("utc_offset") or base["utc_offset"]),
        "reasoning": rec.get("reasoning", "Normalized scheduling recommendation."),
    }


def _parse_utc(value: str):
    try:
        return datetime.strptime(value.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    except Exception:
        return None


def _slot_hours_from_history(history: List[Dict], geography: str) -> List[str]:
    if not history:
        return []
    hours = []
    for row in history:
        if row.get("Geography") and row.get("Geography") != geography:
            continue
        try:
            hour = int(row.get("Local_Hour"))
            hours.append(f"{hour:02d}:00")
        except Exception:
            continue
    return hours[:3]


def choose_publish_slot(schedule_rec: Dict, queue: List[str],
                        history: List[Dict] = None,
                        min_gap_hours: int = 5,
                        now_utc: datetime = None) -> Dict:
    """
    Choose the next valid publish slot from current queue plus recommended/history slots.
    """
    schedule_rec = normalize_recommendation(schedule_rec)
    history_slots = _slot_hours_from_history(history or [], schedule_rec["geography"])
    slots = list(dict.fromkeys(history_slots + schedule_rec["recommended_slots"]))
    slots.sort()

    tz = _offset_timezone(schedule_rec["utc_offset"])
    now_utc = now_utc or datetime.now(timezone.utc)

    scheduled_datetimes = [dt for dt in (_parse_utc(item) for item in queue or []) if dt]
    future_queue = [dt for dt in scheduled_datetimes if dt > now_utc]
    latest_scheduled_utc = max(future_queue) if future_queue else now_utc
    min_allowed_utc = latest_scheduled_utc + timedelta(hours=min_gap_hours)

    local_anchor = min_allowed_utc.astimezone(tz)
    found_slot = None
    for day_offset in range(30):
        check_day = local_anchor + timedelta(days=day_offset)
        for slot_str in slots:
            h, m = map(int, slot_str.split(":"))
            candidate_local = check_day.replace(hour=h, minute=m, second=0, microsecond=0)
            candidate_utc = candidate_local.astimezone(timezone.utc)
            if candidate_utc >= min_allowed_utc:
                found_slot = candidate_utc
                break
        if found_slot:
            break

    if not found_slot:
        found_slot = min_allowed_utc

    return {
        "publish_at": found_slot.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "geography": schedule_rec["geography"],
        "local_hour": found_slot.astimezone(tz).hour,
        "weekday": found_slot.astimezone(tz).weekday(),
        "slots_considered": slots,
        "reasoning": schedule_rec.get("reasoning", ""),
    }
