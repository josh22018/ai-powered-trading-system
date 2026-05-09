import os
import webbrowser
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv, set_key

# Load credentials
load_dotenv()
API_KEY = os.getenv("UPSTOX_API_KEY")
API_SECRET = os.getenv("UPSTOX_API_SECRET")
REDIRECT_URI = os.getenv("UPSTOX_REDIRECT_URI", "http://127.0.0.1:5000/login/callback")

AUTH_CODE = None

class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global AUTH_CODE
        query_components = parse_qs(urlparse(self.path).query)
        
        if "code" in query_components:
            AUTH_CODE = query_components["code"][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Authentication Successful!</h1><p>You can close this tab and return to the terminal.</p></body></html>")
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Authentication Failed!</h1><p>No code found in URL.</p></body></html>")

def login():
    if not API_KEY or not API_SECRET:
        print("Error: UPSTOX_API_KEY and UPSTOX_API_SECRET must be set in the .env file.")
        return None

    auth_url = f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={API_KEY}&redirect_uri={REDIRECT_URI}"
    
    print("="*60)
    print(" Upstox Authentication")
    print("="*60)
    print("Opening browser for login...")
    print(f"URL: {auth_url}")
    
    webbrowser.open(auth_url)
    
    # Extract port from redirect URI to run local server
    port = int(urlparse(REDIRECT_URI).port or 5000)
    server = HTTPServer(('127.0.0.1', port), AuthHandler)
    
    print(f"Waiting for callback on port {port}...")
    while AUTH_CODE is None:
        server.handle_request()
        
    print("\nAuthorization code received! Exchanging for access token...")
    
    token_url = "https://api.upstox.com/v2/login/authorization/token"
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    data = {
        'code': AUTH_CODE,
        'client_id': API_KEY,
        'client_secret': API_SECRET,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code'
    }
    
    response = requests.post(token_url, headers=headers, data=data)
    if response.status_code == 200:
        token_data = response.json()
        access_token = token_data.get("access_token")
        
        # Save token to .env
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        set_key(env_path, "UPSTOX_ACCESS_TOKEN", access_token)
        
        print("Successfully generated and saved UPSTOX_ACCESS_TOKEN to .env!")
        return access_token
    else:
        print(f"Failed to generate token. Status Code: {response.status_code}")
        print(response.text)
        return None

if __name__ == "__main__":
    login()
