"""
app.py — Main entry point for the Streamlit application.

Cookie strategy (hybrid):
  - READ  : st.context.cookies  — official Streamlit 1.37+ API, synchronous,
            reads directly from the HTTP request headers on every render.
            No timing workarounds, no first-render delays.
  - WRITE : extra-streamlit-components CookieManager (write/delete only).
            Unlike st.components.v1.html(), a CookieManager custom component
            is sandboxed with allow-same-origin, so its iframe JavaScript can
            write to document.cookie in the main page's cookie jar.
            st.stop() after set/delete lets the iframe JS execute, which then
            calls Streamlit.setComponentValue() to trigger the next rerun.

Session flow:
  - Login     → verify creds → create server-side session → set session_state
                → cookie_manager.set() → st.stop()
                → iframe writes cookie → setComponentValue() triggers rerun
                → authenticated=True → home page shown
  - Reload    → st.context.cookies.get() → validate token → restore session_state
  - New tab   → browser shares cookie store → same validation → auto-login
  - New browser / incognito → no cookie → login form
  - Logout    → destroy server session → clear session_state
                → cookie_manager.delete() → st.stop()
                → iframe deletes cookie → setComponentValue() triggers rerun
                → no cookie → login form shown

Run with:
    streamlit run app.py
"""

import logging
import logging.config
from datetime import datetime, timedelta, timezone

import extra_streamlit_components as stx
import streamlit as st

from auth import (
    COOKIE_NAME,
    SESSION_DURATION_HOURS,
    create_session,
    destroy_session,
    validate_session,
    verify_user,
)

# ---------------------------------------------------------------------------
# Logging setup — configured once at import time
# ---------------------------------------------------------------------------

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            }
        },
        "root": {"level": "INFO", "handlers": ["console"]},
    }
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page config — must be the very first Streamlit call
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="My App",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CookieManager — used for WRITE only (set/delete).
# READ is done via st.context.cookies (synchronous, no timing issues).
# The "cm_singleton" key ensures one instance is reused across reruns.
# ---------------------------------------------------------------------------

cookie_manager = stx.CookieManager(key="cm_singleton")


# ---------------------------------------------------------------------------
# Session-state initialisation
# ---------------------------------------------------------------------------


def _init_session_state() -> None:
    """Initialise all required session_state keys if they are absent.

    Keys:
        authenticated (bool): Whether the current tab session is authenticated.
        username (str | None): Logged-in username, or None.
        token (str | None): Active session token, or None.

    Returns:
        None
    """
    defaults = {
        "authenticated": False,
        "username": None,
        "token": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_session_state()


# ---------------------------------------------------------------------------
# Login UI
# ---------------------------------------------------------------------------


def _show_login_form() -> None:
    """Render the login form and handle submission.

    On successful authentication:
      - Creates a server-side session token.
      - Updates session_state immediately so the rerun triggered by
        cookie_manager shows the home page (no second auth-gate check needed).
      - Calls cookie_manager.set() which writes the browser cookie via its
        allow-same-origin iframe, then calls setComponentValue() to trigger
        a natural Streamlit rerun.
      - st.stop() halts the current render so no further output is produced;
        the iframe JS executes in the browser and triggers the rerun.

    Returns:
        None
    """
    _, col2, _ = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("## 🔐 Sign in")
        st.markdown("---")

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="Enter username")
            password = st.text_input(
                "Password", type="password", placeholder="Enter password"
            )
            submitted = st.form_submit_button("Login", use_container_width=True)

        if submitted:
            if not username or not password:
                logger.warning("Login attempt with empty username or password")
                st.error("Please enter both username and password.")
                return

            logger.info("Login attempt for username '%s'", username)
            if verify_user(username, password):
                token = create_session(username)
                logger.info(
                    "Login SUCCESS for '%s' — token prefix: %s", username, token[:8]
                )
                # Set session_state before stopping so the next rerun (triggered
                # by setComponentValue) sees authenticated=True and shows home.
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.token = token
                cookie_manager.set(
                    COOKIE_NAME,
                    token,
                    expires_at=datetime.now(timezone.utc)
                    + timedelta(hours=SESSION_DURATION_HOURS),
                )
                st.stop()
                # iframe JS writes cookie → setComponentValue() → rerun
                # → authenticated=True → home page shown.
            else:
                logger.warning(
                    "Login FAILED for username '%s' — bad credentials", username
                )
                st.error("Invalid username or password.")

        st.markdown(
            "<br><small style='color:grey'>Test accounts: "
            "<b>test1 / test1</b> &nbsp;·&nbsp; <b>test2 / test2</b></small>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def _logout() -> None:
    """Destroy the current session and clear all auth state.

    Removes the server-side session entry, clears st.session_state, then
    calls cookie_manager.delete() which removes the browser cookie via its
    allow-same-origin iframe and triggers a rerun that shows the login form.

    Returns:
        None
    """
    token = st.session_state.get("token")
    username = st.session_state.get("username")
    if token:
        destroy_session(token)
    logger.info("Logout: user '%s' signed out", username)

    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.token = None
    cookie_manager.delete(COOKIE_NAME)
    st.stop()
    # iframe JS deletes cookie → setComponentValue() → rerun → login form.


# ---------------------------------------------------------------------------
# Auth gate — READ via st.context.cookies (synchronous, no cm_ready needed)
# ---------------------------------------------------------------------------

if not st.session_state.authenticated:
    # st.context.cookies reads directly from the HTTP request headers —
    # synchronous on every render, no timing workarounds required.
    token = st.context.cookies.get(COOKIE_NAME)
    logger.info("Auth gate: cookie token present=%s", bool(token))

    if token:
        username = validate_session(token)
        if username:
            logger.info(
                "Session restored from cookie for user '%s' (token prefix: %s)",
                username,
                token[:8],
            )
            st.session_state.authenticated = True
            st.session_state.username = username
            st.session_state.token = token
        else:
            logger.warning(
                "Cookie present but invalid/expired (prefix: %s) — ignoring",
                token[:8],
            )

    if not st.session_state.authenticated:
        logger.info("Auth gate: no valid session — showing login form")
        _show_login_form()
        st.stop()

# ---------------------------------------------------------------------------
# Authenticated — sidebar + navigation + page execution
# ---------------------------------------------------------------------------

_PAGES = [
    st.Page("pages/home.py", title="Home", icon="🏠"),
    st.Page("pages/about.py", title="About", icon="ℹ️"),
]
pg = st.navigation(_PAGES, position="hidden")

with st.sidebar:
    st.markdown(f"### Welcome, **{st.session_state.username}**!")
    st.markdown("---")
    for page in _PAGES:
        st.page_link(page, label=page.title, icon=page.icon)
    st.markdown("---")
    if st.button("Logout", use_container_width=True):
        _logout()

pg.run()
