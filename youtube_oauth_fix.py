import os
from google_auth_oauthlib.flow import InstalledAppFlow

# This is the scope needed to upload videos AND manage captions (SRT)
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

def main():
    print("=== YouTube OAuth Refresh Token Generator ===")
    print("Make sure you have downloaded your client_secret.json from Google Cloud Console.")
    print("Place it in the same folder as this script, or specify the path below.\n")
    
    client_secrets_file = input("Enter path to client_secret.json (or press Enter if in current dir): ").strip()
    if not client_secrets_file:
        client_secrets_file = "client_secret.json"
        
    if not os.path.exists(client_secrets_file):
        print(f"Error: Could not find {client_secrets_file}.")
        return

    # Run the OAuth flow
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
    
    # This opens a browser window for you to log in
    credentials = flow.run_local_server(port=0)
    
    print("\n=== SUCCESS ===")
    print("Here is your Refresh Token. Save this in AWS Secrets Manager under 'youtube_refresh_token':\n")
    print("--------------------------------------------------")
    print(credentials.refresh_token)
    print("--------------------------------------------------\n")
    print("You can now safely delete the client_secret.json file if you wish.")

if __name__ == "__main__":
    main()
