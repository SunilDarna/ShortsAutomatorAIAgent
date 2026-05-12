import os
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def upload_to_youtube(video_path, title, description, client_id, client_secret, refresh_token):
    print("Uploading to YouTube Shorts...")
    
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
    
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["shorts", "AI", "Wealth", "Wisdom"],
            "categoryId": "27" # Education
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False
        }
    }
    
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    
    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media
    )
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")
            
    print(f"YouTube Upload Complete! Video ID: {response['id']}")
    return response['id']
