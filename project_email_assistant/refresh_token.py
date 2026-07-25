import sys
sys.path.insert(0, 'backend')
from google.oauth2.credentials import Credentials
import google.auth.transport.requests

creds = Credentials.from_authorized_user_file(
    'backend/token.json',
    ['https://www.googleapis.com/auth/gmail.modify']
)
print('valid:', creds.valid)
print('expired:', creds.expired)
print('has refresh:', bool(creds.refresh_token))
if not creds.valid and creds.refresh_token:
    creds.refresh(google.auth.transport.requests.Request())
    print('refreshed! new expiry:', creds.expiry)
    with open('backend/token.json', 'w') as f:
        f.write(creds.to_json())
    print('token.json updated')
elif creds.valid:
    print('Token is still valid')
else:
    print('ERROR: token expired and no refresh token')
