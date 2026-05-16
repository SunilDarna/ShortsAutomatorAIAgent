"""
youtube_analytics.py — YouTube Analytics ingestion scaffold.

This module pulls video-level metrics so the pipeline can learn from published
Shorts. It is safe to import without credentials; API calls only happen when
collection functions are invoked.
"""
from datetime import date, timedelta
from typing import Dict, List

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


ANALYTICS_METRICS = [
    "views",
    "engagedViews",
    "averageViewDuration",
    "averageViewPercentage",
    "estimatedMinutesWatched",
    "subscribersGained",
    "likes",
    "comments",
    "shares",
]


def get_authenticated_analytics(client_id: str, client_secret: str, refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/yt-analytics.readonly"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    return build("youtubeAnalytics", "v2", credentials=creds)


def fetch_video_metrics(client_id: str, client_secret: str, refresh_token: str,
                        youtube_id: str, days_back: int = 7) -> Dict:
    analytics = get_authenticated_analytics(client_id, client_secret, refresh_token)
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    response = analytics.reports().query(
        ids="channel==MINE",
        startDate=start_date.isoformat(),
        endDate=end_date.isoformat(),
        metrics=",".join(ANALYTICS_METRICS),
        filters=f"video=={youtube_id}",
    ).execute()

    headers = [col["name"] for col in response.get("columnHeaders", [])]
    rows = response.get("rows", [])
    if not rows:
        return {"youtube_id": youtube_id}
    values = rows[0]
    data = dict(zip(headers, values))
    data["youtube_id"] = youtube_id
    return data


def metrics_to_performance_args(metrics: Dict) -> Dict:
    return {
        "views_24h": int(metrics.get("views", 0) or 0),
        "stayed_rate": float(metrics.get("averageViewPercentage", 0.0) or 0.0),
        "apv": float(metrics.get("averageViewPercentage", 0.0) or 0.0),
        "replay_rate": max(0.0, float(metrics.get("averageViewPercentage", 0.0) or 0.0) - 100.0),
        "subs_gained": int(metrics.get("subscribersGained", 0) or 0),
    }


def collect_for_clips(client_id: str, client_secret: str, refresh_token: str,
                      published_clips: List[Dict], days_back: int = 7) -> List[Dict]:
    results = []
    for clip in published_clips:
        youtube_id = clip.get("YouTube_ID")
        if not youtube_id:
            continue
        metrics = fetch_video_metrics(
            client_id, client_secret, refresh_token, youtube_id, days_back=days_back
        )
        metrics["clip_id"] = clip.get("Clip_ID")
        results.append(metrics)
    return results
