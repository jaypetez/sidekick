"""
One-time Google OAuth authorization script.

Run this on your LOCAL LAPTOP (not the server) — it needs a browser.
It saves token.json which you then SCP to the server.

Usage:
    pip install google-auth-oauthlib
    python auth.py

Then copy token.json to your server:
    scp token.json youruser@yourserver:~/.config/sidekick/token.json
"""

import json
import os
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Missing dependency. Run: pip install google-auth-oauthlib")
    sys.exit(1)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/tasks",
]

def main():
    creds_file = input(
        "Path to credentials.json (press Enter for ./credentials.json): "
    ).strip() or "credentials.json"

    if not os.path.exists(creds_file):
        print(f"File not found: {creds_file}")
        print("Download it from Google Cloud Console → Credentials → your OAuth client → Download JSON")
        sys.exit(1)

    print("\nOpening browser for Google authorization...")
    flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
    creds = flow.run_local_server(port=0)

    output = "token.json"
    with open(output, "w") as f:
        f.write(creds.to_json())

    print(f"\nSaved {output}")
    print("\nNow copy it to your server:")
    print(f"    scp {output} youruser@yourserver:~/.config/sidekick/token.json")
    print("\nThen run the bot on the server — no browser needed from here on.")

if __name__ == "__main__":
    main()
