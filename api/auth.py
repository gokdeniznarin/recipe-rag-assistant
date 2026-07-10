import os
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt
import chromadb

# Şifre hashleme ayarı
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT ayarları
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "gelistirme-icin-gizli-anahtar-degistir")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# ChromaDB'de kullanıcılar için ayrı bir koleksiyon
chroma_client = chromadb.HttpClient(host='localhost', port=8000)
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
    """ChromaDB'de e-postaya göre kullanıcı arar."""
    results = users_collection.get(ids=[email])
    if len(results["ids"]) == 0:
        return None
    return {
        "email": results["ids"][0],
        "hashed_password": results["metadatas"][0]["hashed_password"],
    }


def create_user(email: str, password: str):
    """Yeni bir kullanıcı oluşturur, ChromaDB'ye kaydeder."""
    existing = get_user_by_email(email)
    if existing is not None:
        raise ValueError("A user with this email already exists.")

    hashed = hash_password(password)
    users_collection.add(
        ids=[email],
        documents=[email],
        metadatas=[{"hashed_password": hashed, "created_at": str(datetime.now(timezone.utc))}]
    )