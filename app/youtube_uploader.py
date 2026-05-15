import os
from datetime import datetime
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def get_authenticated_youtube(client_id, client_secret, refresh_token):
    """Authenticate and return a YouTube API build object."""
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token"
    )
    creds.refresh(google.auth.transport.requests.Request())
    return build("youtube", "v3", credentials=creds)

def get_schedule_queue(client_id, client_secret, refresh_token):
    """
    Fetches the authenticated user's recent uploads to find currently scheduled videos.
    Returns a list of ISO 8601 datetime strings (UTC) for videos that have publishAt set.
    """
    youtube = get_authenticated_youtube(client_id, client_secret, refresh_token)
    
    # 1. Get the uploads playlist ID for the authenticated user
    channels_response = youtube.channels().list(
        part="contentDetails",
        mine=True
    ).execute()
    
    if not channels_response.get("items"):
        print("Uploader: Could not find authenticated channel.")
        return []
        
    uploads_playlist_id = channels_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    
    # 2. Get recent videos from the uploads playlist
    playlistitems_response = youtube.playlistItems().list(
        part="contentDetails",
        playlistId=uploads_playlist_id,
        maxResults=50
    ).execute()
    
    video_ids = [item["contentDetails"]["videoId"] for item in playlistitems_response.get("items", [])]
    
    if not video_ids:
        return []
        
    # 3. Check the status.publishAt for each video
    videos_response = youtube.videos().list(
        part="status",
        id=",".join(video_ids)
    ).execute()
    
    scheduled_times = []
    for video in videos_response.get("items", []):
        status = video.get("status", {})
        # If publishAt exists and it is in the future, it's a scheduled video
        if "publishAt" in status:
            # YouTube API returns ISO strings like 2026-05-15T18:00:00Z
            scheduled_times.append(status["publishAt"])
            
    # Sort them so we can easily find the latest
    scheduled_times.sort()
    return scheduled_times

def upload_to_youtube(video_path, title, description, client_id, client_secret, refresh_token, tags=None, category_id="27", srt_path=None, publish_at=None):
    print("Uploading to YouTube Shorts with SEO 2.0...")
    
    youtube = get_authenticated_youtube(client_id, client_secret, refresh_token)
    
    # Use dynamic tags if provided, else fallback
    final_tags = tags if tags else ["shorts", "AI", "Wealth", "Wisdom"]
    
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": final_tags,
            "categoryId": category_id
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False
        },
        "recordingDetails": {
            "location": {
                "latitude": 37.0902, # USA Central
                "longitude": -95.7129
            },
            "locationDescription": "United States"
        }
    }
    
    # Inject scheduling logic if publish_at is provided
    if publish_at:
        body["status"]["publishAt"] = publish_at
        print(f"Uploader: Setting publishAt to {publish_at} (UTC)")
    
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    
    request = youtube.videos().insert(
        part="snippet,status,recordingDetails",
        body=body,
        media_body=media
    )
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")
            
    video_id = response['id']
    print(f"YouTube Upload Complete! Video ID: {video_id}")
    
    # --- Upload SRT Captions for SEO Indexing ---
    if srt_path and os.path.exists(srt_path):
        print("Uploading SEO Captions (SRT)...")
        try:
            caption_body = {
                'snippet': {
                    'videoId': video_id,
                    'language': 'en',
                    'name': 'English SEO',
                    'isDefault': True
                }
            }
            media_srt = MediaFileUpload(srt_path, mimetype='text/plain')
            youtube.captions().insert(
                part='snippet',
                body=caption_body,
                media_body=media_srt
            ).execute()
            print("SRT SEO Indexing Complete.")
        except Exception as e:
            print(f"SRT Upload Warning (Video still live): {e}")

    return video_id
