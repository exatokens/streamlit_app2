# Streamlit Auth App

A Streamlit multi-page application demonstrating browser-cookie-based authentication
with server-side session management. Solves the hard problem of persisting login state
across page reloads and browser tabs without logging users out.

---

## Features

- Login persists across **page reloads** in the same tab
- Login persists across **multiple tabs** in the same browser (open as many tabs as you want — no re-login)
- Different browsers are **isolated** — each browser must log in separately
- Two protected pages: **Home** and **About**
- Console logging for every auth event
- MySQL-ready — swap one file to connect a real database

---

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501` and log in with:

| Username | Password |
|----------|----------|
| test1    | test1    |
| test2    | test2    |

---

## File Structure

```
streamlit_app2/
├── app.py              # Entry point: logging, auth gate, navigation
├── auth.py             # Session store, user store, all auth functions
├── pages/
│   ├── home.py         # Home page
│   └── about.py        # About page
└── requirements.txt
```

---

## Architecture

### Why cookies?

Streamlit's `st.session_state` is **per-tab** (tied to a WebSocket connection).
It resets on every page reload and is empty in a new tab. It cannot persist auth
state across reloads or tabs on its own.

The solution uses two layers:

```
Browser (cookie)               Server (Python module, in-memory)
────────────────               ─────────────────────────────────
auth_session = <UUID token>    _SESSION_STORE = {
                                   "<UUID>": {
                                       "username":   "test1",
                                       "created_at": datetime,
                                       "expires_at": datetime,
                                   }
                               }
```

- The **browser cookie** stores a UUID session token. Cookies are automatically
  shared across all tabs in the same browser, and isolated between different browsers.
- The **server-side `_SESSION_STORE`** (module-level Python dict in `auth.py`) is
  shared across every Streamlit connection on the same server process. It maps tokens
  to user data and expiry times.
- On every render, the cookie is read → the token is validated against the store →
  if valid, the user is authenticated without showing the login form.

### Session behaviour by scenario

| Scenario | How it works |
|----------|-------------|
| Page reload (same tab) | New WebSocket connection, fresh `session_state`. Cookie is read → token validated → auto-login |
| New tab (same browser) | Browser shares cookies across tabs. Token validated → auto-login, no prompt |
| New browser / incognito | Separate cookie store → no cookie found → login form shown |
| Server restart | In-memory `_SESSION_STORE` is cleared → cookie token fails validation → login form shown |
| Session expiry (24 h) | `validate_session()` detects expiry → purges cookie → login form shown |
| Logout | Server session destroyed + browser cookie deleted → all tabs require re-login on next load |

---

## auth.py — How It Works

All authentication logic lives here. Module-level dicts simulate database tables.

### In-memory stores (DB simulation)

```python
# Simulates a `users` table: { username: sha256(password) }
_USERS = {
    "test1": hashlib.sha256("test1".encode()).hexdigest(),
    "test2": hashlib.sha256("test2".encode()).hexdigest(),
}

# Simulates a `sessions` table: { token: { username, created_at, expires_at } }
_SESSION_STORE = {}
```

### Functions

| Function | What it does |
|----------|-------------|
| `get_db_connection()` | Placeholder — returns `None`. Replace with MySQL connector when ready |
| `verify_user(username, password)` | SHA-256 hashes the password and compares against `_USERS` |
| `create_session(username)` | Generates a UUID4 token, stores metadata in `_SESSION_STORE`, returns the token |
| `validate_session(token)` | Looks up token, checks expiry, returns username or `None` |
| `destroy_session(token)` | Removes token from `_SESSION_STORE` |

---

## app.py — Three Non-Obvious Problems Solved

### Problem 1: CookieManager first-render timing

`extra-streamlit-components` `CookieManager` injects a browser iframe with JavaScript.
On the **first render** of any new tab or reload, that JS has not executed yet, so
`cookie_manager.get()` always returns `None` — even when a real cookie exists.

**Fix — `cm_ready` flag:**

```
Render #1  →  cm_ready = False
              Set cm_ready = True
              st.stop()  ← halt, don't show login form yet
              ↓
              CookieManager JS executes in browser iframe
              Reads browser cookies
              Calls Streamlit.setComponentValue() → triggers automatic rerun

Render #2  →  cm_ready = True
              cookie_manager.get() returns real cookie value
              Validate token → authenticated or show login form
```

Without this, render #1 would see `None` from the cookie, conclude the user is not
logged in, and show the login form immediately — even for a user who is already logged in.

---

### Problem 2: Cookie never written to the browser

`cookie_manager.set()` works by rendering a browser iframe component. That component's
JavaScript writes `document.cookie` and then calls `Streamlit.setComponentValue()` to
signal completion and trigger the next rerun.

The original code called `st.rerun()` immediately after `cookie_manager.set()`. This
caused Streamlit to send a **new render** to the browser before the iframe's JS had
a chance to execute. The iframe was unmounted and **the cookie was never written**.
Users appeared logged in during the session (because `session_state.authenticated = True`)
but the browser had no cookie, so any page reload showed the login form again.

**Fix — `st.stop()` instead of `st.rerun()`:**

```
WRONG (race condition):
  cookie_manager.set(token)  →  st.rerun()
  ↑ new render arrives before iframe JS runs → cookie not written

CORRECT:
  cookie_manager.set(token)  →  st.stop()
  ↑ current render lands fully in browser
  ↑ iframe JS runs → document.cookie written
  ↑ setComponentValue() fires → natural rerun
  ↑ next render: authenticated=True → home page shown
```

The same fix applies to `cookie_manager.delete()` in the logout handler.

---

### Problem 3: Page reset to Home on every reload

`st.navigation()` was defined after the auth gate. Every `st.stop()` call in the
gate (the `cm_ready` wait, the login form stop) prevented `st.navigation()` from
ever running. Streamlit lost the current URL path and reset to the first page
(Home) on every render that hit a `st.stop()`.

**Fix — move `st.navigation()` before the auth gate with `position="hidden"`:**

```python
# Always runs — even on renders that hit st.stop() below
_PAGES = [
    st.Page("pages/home.py", title="Home", icon="🏠"),
    st.Page("pages/about.py", title="About", icon="ℹ️"),
]
pg = st.navigation(_PAGES, position="hidden")  # position="hidden": no auto sidebar nav

# ... auth gate with st.stop() calls ...

# Only reached when authenticated:
for page in _PAGES:
    st.page_link(page, ...)   # show nav links only to logged-in users
pg.run()                       # execute the page the URL points to
```

`position="hidden"` suppresses the automatically rendered sidebar navigation so
unauthenticated users don't see the nav. Authenticated users get it rendered
manually via `st.page_link()`.

---

## Complete Auth Flow

```
LOGIN
─────
User submits form
  → verify_user()          hash + compare against _USERS
  → create_session()       UUID token written to _SESSION_STORE with 24h expiry
  → cookie_manager.set()   iframe component queued in current render
  → session_state updated  authenticated=True, username, token
  → st.stop()              current render delivered to browser
  → iframe JS runs         document.cookie = "auth_session=<token>; expires=..."
  → setComponentValue()    triggers rerun
  → rerun                  authenticated=True → home page shown


RELOAD / NEW TAB
────────────────
New WebSocket connection → fresh session_state

Render #1:
  cm_ready=False → set True → st.stop()
  CookieManager JS reads browser cookies → setComponentValue({auth_session: token})
  → triggers rerun

Render #2:
  cm_ready=True
  cookie_manager.get("auth_session") → token string
  validate_session(token) → username (or None if expired)
  session_state.authenticated=True → home page shown at correct URL


DIFFERENT BROWSER / INCOGNITO
──────────────────────────────
No browser cookie → cookie_manager.get() → None → login form shown


LOGOUT
──────
Logout button clicked → _logout()
  → destroy_session(token)    removes token from _SESSION_STORE
  → cookie_manager.delete()   iframe component queued
  → session_state cleared     authenticated=False, cm_ready=False
  → st.stop()                 current render delivered to browser
  → iframe JS runs            document.cookie deleted
  → setComponentValue()       triggers rerun
  → rerun                     cm_ready=False → render #1 → stop
  → getAll JS                 reads cookies (none found) → rerun
  → render #2                 no cookie → login form shown
```

---

## Migrating to MySQL

Only `auth.py` needs to change. The rest of the app is unaffected.

**Step 1 — implement `get_db_connection()`:**

```python
import mysql.connector, os

def get_db_connection():
    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
    )
```

**Step 2 — replace `_USERS` lookups:**

```python
def verify_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT password_hash FROM users WHERE username = %s", (username,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    return row[0] == hashlib.sha256(password.encode()).hexdigest()
```

**Step 3 — replace `_SESSION_STORE` operations:**

```python
def create_session(username):
    token = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (token, username, expires_at) VALUES (%s, %s, %s)",
        (token, username, datetime.now() + timedelta(hours=SESSION_DURATION_HOURS))
    )
    conn.commit()
    conn.close()
    return token

# validate_session and destroy_session follow the same pattern
```

---

## Dependencies

```
streamlit>=1.35.0
extra-streamlit-components>=0.1.71
```
