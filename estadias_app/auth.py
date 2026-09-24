from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any


DEFAULT_USERS = {"admin": "admin"}


def _read_users_from_secrets() -> dict[str, str]:
    try:
        import streamlit as st

        users = st.secrets.get("users", {})
        if users:
            return {str(user).strip(): str(password) for user, password in dict(users).items()}
    except Exception:
        pass
    return {}


def _allow_default_admin() -> bool:
    """admin/admin so vale para desenvolvimento local, com ALLOW_DEFAULT_ADMIN=SIM explicito."""
    value = os.environ.get("ALLOW_DEFAULT_ADMIN", "")
    try:
        import streamlit as st

        value = str(st.secrets.get("ALLOW_DEFAULT_ADMIN", value))
    except Exception:
        pass
    return value.strip().upper() in {"1", "SIM", "S", "TRUE", "YES", "ON"}


def login_not_configured() -> bool:
    """Sem usuarios nos Secrets e sem liberacao explicita do admin padrao: login bloqueado."""
    return not _read_users_from_secrets() and not _allow_default_admin()


def using_default_admin() -> bool:
    return not _read_users_from_secrets() and _allow_default_admin()


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
    if not users and _allow_default_admin():
        users = DEFAULT_USERS
    return bool(user in users and _password_matches(users[user], str(password or "")))
