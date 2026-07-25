from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify"
]

flow = InstalledAppFlow.from_client_secrets_file(
    "credential.json",
    SCOPES
)

creds = flow.run_local_server(port=8080)

with open("token.json", "w") as token:
    token.write(creds.to_json())

print("✅ token.json created successfully!")