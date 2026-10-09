from __future__ import annotations

import hashlib
import hmac
from typing import Any


def _read_users_from_secrets() -> dict[str, str]:
    try:
        import streamlit as st

        users = st.secrets.get("users", {})
        if users:
            return {str(user).strip(): str(password) for user, password in dict(users).items()}
    except Exception:
        pass
    return {}


def users_missing() -> bool:
    return not _read_users_from_secrets()


def _password_matches(stored: str, password: str) -> bool:
    stored = str(stored or "")
    password = str(password or "")
    if stored.startswith("sha256:"):
        digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(stored.removeprefix("sha256:"), digest)
    return hmac.compare_digest(stored, password)


def authenticate(username: str, password: str) -> bool:
    user = str(username or "").strip()
    users = _read_users_from_secrets()
    return bool(user in users and _password_matches(users[user], str(password or "")))
