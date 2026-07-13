import os
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt, JWTError
import chromadb
from fastapi import Header, HTTPException
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests


# Şifre hashleme ayarı
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT ayarları
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "gelistirme-icin-gizli-anahtar-degistir")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
GOOGLE_CLIENT_ID = "490027664953-ne5lp527bovm51j30qh3aqrto329fjog.apps.googleusercontent.com"

# ChromaDB'de kullanıcılar için ayrı bir koleksiyon
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=8000)
users_collection = chroma_client.get_or_create_collection("users")


def hash_password(password: str) -> str:
    """Şifreyi güvenli bir hash'e çevirir."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Girilen şifrenin, kayıtlı hash ile eşleşip eşleşmediğini kontrol eder."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_email: str) -> str:
    """Kullanıcı için bir JWT token üretir."""
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": user_email, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    """Token'ı çözüp içindeki kullanıcı e-postasını döndürür. Geçersizse hata fırlatır."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return payload["sub"]


def get_user_by_email(email: str):
    results = users_collection.get(ids=[email])
    if len(results["ids"]) == 0:
        return None
    meta = results["metadatas"][0]
    return {
        "email": results["ids"][0],
        "hashed_password": meta["hashed_password"],
        "auth_provider": meta.get("auth_provider", "password"),
        "created_at": meta.get("created_at", ""),
    }


def create_user(email: str, password: str):
    existing = get_user_by_email(email)
    if existing is not None:
        if existing["auth_provider"] == "google":
            raise ValueError("This email is already registered with Google. Please sign in with Google.")
        raise ValueError("A user with this email already exists.")

    hashed = hash_password(password)
    users_collection.add(
        ids=[email],
        embeddings=[[0.0] * 384],
        documents=[email],
        metadatas=[{
            "hashed_password": hashed,
            "auth_provider": "password",
            "created_at": str(datetime.now(timezone.utc))
        }]
    )



def get_current_user_email(authorization: str = Header(...)) -> str:
    """Header'daki JWT token'ı doğrular, geçerliyse kullanıcının e-postasını döner."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = authorization.replace("Bearer ", "")

    try:
        email = decode_access_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return email    



def verify_google_token(token: str) -> dict:
    """Google ID token'ını doğrular, içindeki kullanıcı bilgilerini döner."""
    idinfo = id_token.verify_oauth2_token(
        token,
        google_requests.Request(),
        GOOGLE_CLIENT_ID
    )
    return {
        "email": idinfo["email"],
        "name": idinfo.get("name", ""),
    }


def create_or_get_google_user(email: str) -> str:
    """Google kullanıcısını ChromaDB'de oluşturur ya da mevcut hesabı 'both' olarak günceller."""
    existing = get_user_by_email(email)

    if existing is None:
        # Yeni Google kullanıcısı — şifresi yok
        users_collection.add(
            ids=[email],
            embeddings=[[0.0] * 384],
            documents=[email],
            metadatas=[{
                "hashed_password": "",
                "auth_provider": "google",
                "created_at": str(datetime.now(timezone.utc)),
            }]
        )
    elif existing["auth_provider"] == "password":
        # Klasik kullanıcı Google ile de bağlandı → "both"
        users_collection.update(
            ids=[email],
            metadatas=[{
                "hashed_password": existing["hashed_password"],
                "auth_provider": "both",
                "created_at": existing["created_at"],
            }]
        )

    return email