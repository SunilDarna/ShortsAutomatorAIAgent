import os
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def upload_to_youtube(video_path, title, description, client_id, client_secret, refresh_token, tags=None, category_id="27", srt_path=None):
    print("Uploading to YouTube Shorts with SEO 2.0...")
    
    # Reconstruct credentials using the refresh token
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token"
    )
    
    # Refresh the token if needed
    creds.refresh(google.auth.transport.requests.Request())
    
    youtube = build("youtube", "v3", credentials=creds)
    
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
    
    # --- NEW: Upload SRT Captions for SEO Indexing ---
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
