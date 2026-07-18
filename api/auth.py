import os
import json
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth
from fastapi import Header, HTTPException


# ── Firebase Admin SDK ────────────────────────────────────
# Service-account kimliğini üç kaynaktan biriyle bulur (öncelik sırasıyla):
#   1. GOOGLE_APPLICATION_CREDENTIALS → JSON dosyasının yolu. Lokal Docker bunu
#      kullanıyor (docker-compose salt-okunur mount ediyor).
#   2. FIREBASE_CREDENTIALS_JSON → JSON'ın kendisi (dosya değil). Anahtarı dosya
#      olarak koyamadığın platformlar için, örn. HF Spaces Secrets. Dosya bir
#      yerde diske düşmediği için bu daha güvenli.
#   3. Hiçbiri yoksa Application Default Credentials (GCP/Cloud Run ortamı).
# Uygulama içinde tek sefer başlatılır.
if not firebase_admin._apps:
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if cred_path and os.path.exists(cred_path):
        firebase_admin.initialize_app(credentials.Certificate(cred_path))
    elif cred_json:
        firebase_admin.initialize_app(credentials.Certificate(json.loads(cred_json)))
    else:
        # GCP ortamında Application Default Credentials'a düş
        firebase_admin.initialize_app()


def get_current_user_email(authorization: str = Header(...)) -> str:
    """Header'daki Firebase ID token'ını doğrular, geçerliyse kullanıcının e-postasını döner."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = authorization.replace("Bearer ", "")

    try:
        decoded_token = firebase_auth.verify_id_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    email = decoded_token.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token does not contain an email")

    return email
