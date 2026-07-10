import os
import pickle
import google.auth.transport.requests
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_credentials():
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    credentials = flow.run_local_server(port=8080)
    
    # Save credentials for later use
    with open("token.pickle", "wb") as token:
        pickle.dump(credentials, token)
    
    print(f"✅ Refresh Token: {credentials.refresh_token}")
    return credentials

if __name__ == "__main__":
    get_credentials()
