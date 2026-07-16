import os
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth
from fastapi import Header, HTTPException


# ── Firebase Admin SDK ────────────────────────────────────
# GOOGLE_APPLICATION_CREDENTIALS env değişkeni, service-account JSON dosyasının
# yolunu göstermeli (docker-compose'da salt-okunur olarak mount edilir).
# Uygulama içinde tek sefer başlatılır.
if not firebase_admin._apps:
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        firebase_admin.initialize_app(credentials.Certificate(cred_path))
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
