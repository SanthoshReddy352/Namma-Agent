import base64
import os
import requests

def generate_auth_flow_via_api(output_filename="auth_flow_api.png"):
    # 1. Define the Authentication Flow Sequence Diagram
    auth_flow_mermaid = """
    sequenceDiagram
        autonumber
        actor User
        participant Client as Frontend App
        participant API as Auth API Server
        participant DB as User Database

        User->>Client: Input Username & Password
        Client->>API: POST /api/v1/auth/login (Credentials)
        
        Note over API,DB: Verify User Credentials
        API->>DB: Query user by username
        DB-->>API: Return password hash & salt
        
        alt Credentials Valid
            API->>API: Generate Signed JWT Token
            API-->>Client: HTTP 200 OK (JWT Token + User Profile)
            Client-->>User: Redirect to Dashboard / Show Success
        else Credentials Invalid
            API-->>Client: HTTP 401 Unauthorized (Error Message)
            Client-->>User: Show "Invalid Credentials" Alert
        end
    """
    
    print("Encoding diagram and requesting from Mermaid.ink API...")
    
    # 2. Encode the string to Base64
    encoded_bytes = base64.b64encode(auth_flow_mermaid.encode('utf-8'))
    encoded_string = encoded_bytes.decode('utf-8')
    
    # 3. Construct the endpoint URL
    api_url = f"https://mermaid.ink/img/{encoded_string}"
    
    # 4. Fetch the image
    try:
        response = requests.get(api_url, timeout=15)
        if response.status_code == 200:
            with open(output_filename, 'wb') as f:
                f.write(response.content)
            print(f"🎉 Success! Auth flow diagram saved as: {os.path.abspath(output_filename)}")
        else:
            print(f"❌ Failed to render. Server returned status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error occurred: {e}")

if __name__ == "__main__":
    # Ensure requests is installed: pip install requests
    generate_auth_flow_via_api()