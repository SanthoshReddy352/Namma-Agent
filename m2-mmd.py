import asyncio
import os
from mermaid_cli import render_mermaid

async def generate_auth_flow_playwright(output_filename="auth_flow_cli.png"):
    # Inserted the actual full diagram steps here instead of the placeholder text
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
    
    print("Rendering diagram via local playwright instance...")
    
    # This package returns a tuple: (title, description, binary_data)
    _, _, image_data = await render_mermaid(auth_flow_mermaid, output_format="png")
    
    with open(output_filename, "wb") as f:
        f.write(image_data)
        
    print(f"🎉 Success! Diagram saved to: {os.path.abspath(output_filename)}")

if __name__ == "__main__":
    asyncio.run(generate_auth_flow_playwright())