"""
auth.py — Authentication and session management module.

This module manages user authentication and server-side session storage.
It uses an in-memory data structure to simulate a MySQL database.
When a real DB is available, replace the in-memory stores with actual
queries inside `get_db_connection()` and the helper functions.

Typical usage:
    from auth import verify_user, create_session, validate_session, destroy_session

    if verify_user("test1", "test1"):
        token = create_session("test1")
        # store token in cookie
"""

import hashlib
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SESSION_DURATION_HOURS = 24
COOKIE_NAME = "auth_session"

# ---------------------------------------------------------------------------
# In-memory stores (simulate MySQL tables)
# These are module-level so they persist across Streamlit reruns/connections
# on the same server process.
# ---------------------------------------------------------------------------

_USERS: dict[str, str] = {
    "test1": hashlib.sha256("test1".encode()).hexdigest(),
    "test2": hashlib.sha256("test2".encode()).hexdigest(),
}
"""
Simulates a `users` table.
Schema: { username: sha256_password_hash }
Replace with a DB query in get_db_connection() when MySQL is available.
"""

_SESSION_STORE: dict[str, dict] = {}
"""
Simulates a `sessions` table.
Schema: {
    token (str): {
        "username":   str,
        "created_at": datetime,
        "expires_at": datetime,
    }
}
"""


# ---------------------------------------------------------------------------
# Database placeholder
# ---------------------------------------------------------------------------

def get_db_connection():
    """Return a MySQL database connection.

    This is a placeholder for when a real MySQL database is configured.
    Replace the body with actual connection logic using a library such as
    `mysql-connector-python` or `SQLAlchemy`.

    Returns:
        None: Always returns None until a real DB is configured.

    Example (future MySQL implementation)::

        import mysql.connector
        return mysql.connector.connect(
            host=os.environ["DB_HOST"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ["DB_NAME"],
        )
    """
    logger.info("get_db_connection called — using in-memory store (no DB configured)")
    return None


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def verify_user(username: str, password: str) -> bool:
    """Check whether username/password credentials are valid.

    Hashes the supplied password with SHA-256 and compares it against the
    stored hash. In a real setup this would query the `users` table via
    `get_db_connection()`.

    Args:
        username (str): The username to look up.
        password (str): The plain-text password to verify.

    Returns:
        bool: True if credentials match, False otherwise.
    """
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    stored_hash = _USERS.get(username)
    if stored_hash is None:
        return False
    return stored_hash == password_hash


def create_session(username: str) -> str:
    """Create a new server-side session for an authenticated user.

    Generates a UUID4 token, stores session metadata in `_SESSION_STORE`,
    and returns the token so the caller can persist it as a browser cookie.

    Args:
        username (str): The authenticated user's username.

    Returns:
        str: A UUID4 session token string.
    """
    token = str(uuid.uuid4())
    now = datetime.now()
    _SESSION_STORE[token] = {
        "username": username,
        "created_at": now,
        "expires_at": now + timedelta(hours=SESSION_DURATION_HOURS),
    }
    logger.info("Session created for user '%s' (token prefix: %s)", username, token[:8])
    return token


def validate_session(token: str) -> Optional[str]:
    """Validate a session token and return the owning username if valid.

    Looks up the token in `_SESSION_STORE` and checks its expiry. Expired
    sessions are cleaned up automatically.

    Args:
        token (str): The session token read from the browser cookie.

    Returns:
        Optional[str]: The username associated with the token, or None if the
            token is missing, expired, or otherwise invalid.
    """
    if not token:
        return None

    session = _SESSION_STORE.get(token)
    if session is None:
        return None

    if datetime.now() > session["expires_at"]:
        logger.info("Session expired for token prefix %s — removing", token[:8])
        del _SESSION_STORE[token]
        return None

    return session["username"]


def destroy_session(token: str) -> None:
    """Remove a session from the server-side store (logout).

    Args:
        token (str): The session token to invalidate.

    Returns:
        None
    """
    removed = _SESSION_STORE.pop(token, None)
    if removed:
        logger.info(
            "Session destroyed for user '%s' (token prefix: %s)",
            removed["username"],
            token[:8],
        )
