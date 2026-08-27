import hashlib

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app import models


def hash_api_key(raw_key: str) -> str:
    """
    Keys are never stored in plaintext. We store only a SHA-256 hash and
    compare hashes on lookup - the same pattern used for password/PAT
    storage. This is a deliberate step up from the original version of
    this project, which stored raw keys directly.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_current_user(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> models.User:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
        )
    key_hash = hash_api_key(x_api_key)
    user = db.query(models.User).filter(models.User.api_key_hash == key_hash).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
    if user.api_key_revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This API key has been revoked.",
        )
    return user


def require_owner(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != models.UserRole.owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an organization owner can perform this action.",
        )
    return user
