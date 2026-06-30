"""Auth: bcrypt + opaque session token in httpOnly cookie."""
import os
import secrets

import bcrypt
from fastapi import Cookie, HTTPException, Response

from db import execute, fetch_one, new_id, now_iso

COOKIE_NAME = "kaptaan_session"

# Cookie security knobs (env-driven so the same code runs on:
#   - Emergent preview (cross-site → SameSite=None + Secure)
#   - VPS same-origin behind nginx (SameSite=Lax + no Secure on http)
# Defaults are safe for VPS deployments. Override in the preview env.
_SAMESITE = (os.environ.get("SESSION_COOKIE_SAMESITE", "lax") or "lax").lower()
if _SAMESITE not in ("lax", "strict", "none"):
    _SAMESITE = "lax"
_SECURE = (os.environ.get("SESSION_COOKIE_SECURE", "false") or "").lower() in ("1", "true", "yes")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


async def seed_bootstrap_user() -> None:
    """Create initial user if none exist."""
    row = await fetch_one("SELECT COUNT(*) AS c FROM users")
    if row and row.get("c", 0) > 0:
        return
    username = os.environ.get("BOOTSTRAP_USERNAME", "kaptaan")
    password = os.environ.get("BOOTSTRAP_PASSWORD", "kaptaan")
    await execute(
        "INSERT INTO users (id, username, password_hash, created_at) VALUES (?,?,?,?)",
        (new_id(), username, hash_password(password), now_iso()),
    )


async def login_user(username: str, password: str, response: Response) -> dict:
    user = await fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_urlsafe(32)
    await execute(
        "UPDATE users SET session_token = ? WHERE id = ?", (token, user["id"])
    )
    # SameSite=None + Secure required for cross-site preview; Lax + no Secure
    # is fine for same-origin VPS behind nginx (over http or https).
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_SECURE,
        samesite=_SAMESITE,
        max_age=60 * 60 * 24 * 30,
        path="/",
    )
    return {"id": user["id"], "username": user["username"]}


async def logout_user(token: str, response: Response) -> None:
    if token:
        await execute(
            "UPDATE users SET session_token = NULL WHERE session_token = ?", (token,)
        )
    response.delete_cookie(COOKIE_NAME, path="/")


async def current_user(
    kaptaan_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    if not kaptaan_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = await fetch_one(
        "SELECT id, username FROM users WHERE session_token = ?", (kaptaan_session,)
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user


async def update_credentials(
    user_id: str, new_username: str | None, new_password: str | None
) -> None:
    sets = []
    values: list = []
    if new_username:
        sets.append("username = ?")
        values.append(new_username)
    if new_password:
        sets.append("password_hash = ?")
        values.append(hash_password(new_password))
    if not sets:
        return
    values.append(user_id)
    await execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", tuple(values))
