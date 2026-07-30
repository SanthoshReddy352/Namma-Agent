import sqlite3
import hashlib
import os
import json
import base64
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "omnicloud.db"
OUTPUT_CREDS_PATH = PROJECT_ROOT / ".gws_creds.json"

# Get the encryption key - fingerprint from Docker container
machine_fingerprint = "ff1326489a87c5a135afacb3b4b9fea6658d7b557124aaab9b421694af8133c2"

env_half = os.environ.get("OMNICLOUD_SECRET_HALF", "omnicloud-dev-secret-half")
derived_key_material = f"{env_half}:{machine_fingerprint}"
encryption_key = hashlib.sha256(derived_key_material.encode()).digest()

print(f"Encryption key (hex): {encryption_key.hex()}")

# Read encrypted credentials from DB
conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()
cursor.execute("SELECT encrypted_credentials FROM cloud_accounts WHERE id = 'be20ff50-0f27-4c92-af55-51d2915ae30e'")
row = cursor.fetchone()
conn.close()

if not row:
    print("No account found!")
    exit(1)

encrypted_b64 = row[0]
raw = base64.b64decode(encrypted_b64)

# Decrypt: IV (12 bytes) + authTag (16 bytes) + ciphertext
iv = raw[:12]
auth_tag = raw[12:28]
ciphertext = raw[28:]

aesgcm = AESGCM(encryption_key)
plaintext = aesgcm.decrypt(iv, ciphertext, auth_tag)
credentials = json.loads(plaintext.decode("utf-8"))

print(f"\nCredentials decrypted successfully!")
print(f"Client ID: {credentials.get('clientId', 'N/A')[:30]}...")
print(f"Has refresh_token: {'refreshToken' in credentials}")
print(f"Has access_token: {'accessToken' in credentials}")

# Save the credentials for gws
with open(OUTPUT_CREDS_PATH, "w") as f:
    json.dump(credentials, f)
print(f"\nSaved to {OUTPUT_CREDS_PATH}")
