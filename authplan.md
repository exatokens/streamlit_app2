# Auth Plan & Architecture

## Problem Statement

Streamlit re-runs the entire Python script on every user interaction and creates a
fresh `st.session_state` for each browser tab (WebSocket connection). This makes
authentication persistence genuinely hard:

| What we need | Streamlit default |
|---|---|
| Stay logged in across page reloads | `session_state` resets on reload |
| Stay logged in in new tabs | `session_state` is per-tab, not shared |
| Different browsers must log in separately | No built-in cross-browser isolation |

---

## Chosen Approach

**Browser cookie (hybrid read/write) + server-side session store.**

```
┌─────────────────────────────────────────────────────────────────┐
│  BROWSER                                                        │
│                                                                 │
│  Cookie: auth_session = "3f8a1c2d-..."  (UUID token)           │
│                                                                 │
│  Tab 1 ──┐                                                      │
│  Tab 2 ──┼──► shared cookie store  (per browser, not per tab)  │
│  Tab 3 ──┘                                                      │
└─────────────────────────────┬───────────────────────────────────┘
                              │ HTTP request carries cookie
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  SERVER  (Python process — single Streamlit instance)           │
│                                                                 │
│  auth.py  _SESSION_STORE = {                                    │
│               "3f8a1c2d-...": {                                 │
│                   "username":   "test1",                        │
│                   "created_at": datetime(2026, 2, 19, 20, 30),  │
│                   "expires_at": datetime(2026, 2, 20, 20, 30),  │
│               }                                                 │
│           }                                                     │
│                                                                 │
│  auth.py  _USERS = {                                            │
│               "test1": sha256("test1"),                         │
│               "test2": sha256("test2"),                         │
│           }                                                     │
└─────────────────────────────────────────────────────────────────┘
```

**Why this works per scenario:**

| Scenario | Mechanism |
|---|---|
| Same tab, reload | Fresh `session_state`, but cookie survives → token re-validated → auto-login |
| Same browser, new tab | Browser shares cookie store across tabs → same token → auto-login |
| Different browser | Separate cookie store → no cookie found → login form |
| Incognito window | Separate temporary cookie store → login form |
| Server restart | `_SESSION_STORE` cleared (module re-imported) → token invalid → login form |
| Token expiry (24 h) | `validate_session()` detects expiry → login form |

---

## Cookie API Design

### Why not pure `extra-streamlit-components` CookieManager

The community `CookieManager` library uses an iframe to read AND write cookies.
Using `.get()` for reading caused three bugs requiring workarounds:

| Bug | Workaround required |
|---|---|
| `.get()` returns `None` on render #1 (JS not loaded yet) | `cm_ready` flag + `st.stop()` wait |
| `st.rerun()` races the iframe — cookie never written | Replace `st.rerun()` with `st.stop()` |
| `st.stop()` before `st.navigation()` resets URL to page #1 | Hoist `st.navigation()` before auth gate |

### Why not pure `st.components.v1.html()` JS injection

`st.components.v1.html()` renders an iframe sandboxed with only `allow-scripts`
(no `allow-same-origin`). This means:

| Attempt | Why it fails |
|---|---|
| `document.cookie = ...` inside iframe | Iframe has no same-origin access — writes to a separate, invisible cookie jar |
| `window.location.reload()` inside iframe | Only reloads the tiny 0px iframe, not the main browser page |

### The working hybrid approach (Streamlit 1.37+)

```
READ   → st.context.cookies.get(name)
         Official API. Reads from the HTTP request headers on every render.
         Synchronous. No timing issues. No first-render delay.
         Eliminates the cm_ready flag entirely.

WRITE  → cookie_manager.set(name, value, expires_at=...)
         extra-streamlit-components CookieManager — a *custom* Streamlit
         component. Custom components are sandboxed with allow-same-origin,
         so document.cookie in the iframe reaches the main page's cookie jar.
         After writing, the iframe calls Streamlit.setComponentValue() to
         trigger a natural rerun. st.stop() lets the iframe JS execute first.

DELETE → cookie_manager.delete(name)
         Same mechanism as WRITE — allow-same-origin iframe expires the cookie.
```

**Why this hybrid eliminates all three old workarounds:**

| Old workaround | Why no longer needed |
|---|---|
| `cm_ready` flag | READ uses `st.context.cookies` (synchronous) — no JS timing involved |
| `st.stop()` instead of `st.rerun()` | `st.stop()` is still used, but for the right reason: let iframe JS run |
| `st.navigation()` hoisted before auth gate | No `cm_ready` wait means no `st.stop()` on initial render of existing sessions |

---

## Data Models

### `_USERS` (simulates `users` table)

```python
{
    "test1": "1b4f0e9851971998e732078544c96b36c3d01cedf7caa332359d6f1d83567014",
    "test2": "60303ae22b998861bce3b28f33eec1be758a213c86c93c076dbe9f558c11c752",
}
# key   = username (str)
# value = SHA-256 hex digest of the password (str)
```

### `_SESSION_STORE` (simulates `sessions` table)

```python
{
    "3f8a1c2d-4b5e-6c7d-8e9f-0a1b2c3d4e5f": {
        "username":   "test1",
        "created_at": datetime(2026, 2, 19, 20, 30, 0),
        "expires_at": datetime(2026, 2, 20, 20, 30, 0),
    }
}
# key   = UUID4 session token (str)
# value = session metadata dict
```

Both are module-level, so they persist across Streamlit reruns within the same
server process. Multiple browser tabs connect to the same process and therefore
see the same store.

---

## auth.py — Function Reference

### `get_db_connection()`
```
Purpose : Placeholder for MySQL connection. Returns None until implemented.
Returns : None
Replace : Implement with mysql-connector-python or SQLAlchemy when DB is ready.
```

### `verify_user(username, password) → bool`
```
Purpose  : Check credentials.
Process  : SHA-256 hash the plain-text password, compare to stored hash in _USERS.
Returns  : True if match, False otherwise (including unknown username).
DB equiv : SELECT 1 FROM users WHERE username = %s AND password_hash = %s
```

### `create_session(username) → str`
```
Purpose  : Create a new authenticated session.
Process  : Generate UUID4 token, write to _SESSION_STORE with 24h expiry.
Returns  : The UUID token string (caller stores it as a browser cookie).
DB equiv : INSERT INTO sessions (token, username, created_at, expires_at) VALUES (...)
```

### `validate_session(token) → str | None`
```
Purpose  : Validate a session token read from a cookie.
Process  : Look up token in _SESSION_STORE. If found and not expired, return username.
           If expired, delete from store and return None.
Returns  : username str if valid, None if missing/expired/invalid.
DB equiv : SELECT username, expires_at FROM sessions WHERE token = %s
```

### `destroy_session(token) → None`
```
Purpose  : Invalidate a session (logout).
Process  : Remove token from _SESSION_STORE.
Returns  : None
DB equiv : DELETE FROM sessions WHERE token = %s
```

---

## app.py — Render Sequence

Every time the Streamlit script runs (a "render"), the following executes
top-to-bottom. `st.stop()` exits early; `pg.run()` executes the active page.

```
Every render:
─────────────
1. set_page_config()          (must be first Streamlit call)
2. Logging config             (idempotent)
3. cookie_manager instantiation  stx.CookieManager(key="cm_singleton")
                                  renders an invisible iframe (write/delete only)
4. _init_session_state()      (sets defaults; no-op if keys exist)
5. Auth gate:
     token = st.context.cookies.get(COOKIE_NAME)    ← synchronous, always correct
     if token valid → set session_state (authenticated, username, token)
     if not authenticated → _show_login_form() → st.stop()
6. st.navigation(position="hidden")   ← only reached when authenticated
7. Sidebar (Welcome + nav links + Logout button)
8. pg.run()                           ← executes the page the URL points to
```

### `st.session_state` keys

| Key | Type | Initial | Meaning |
|---|---|---|---|
| `authenticated` | bool | False | True once the user has a valid session this tab |
| `username` | str \| None | None | Logged-in username |
| `token` | str \| None | None | Active session UUID |

No `cm_ready` flag. No render-count tracking. No timing workarounds.

---

## Cookie Helpers

### Write — `cookie_manager.set(name, value, expires_at)`

```python
# Instantiated once at module scope (used for write/delete only):
cookie_manager = stx.CookieManager(key="cm_singleton")

# In the login success handler:
cookie_manager.set(
    COOKIE_NAME,
    token,
    expires_at=datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS),
)
st.stop()
# CookieManager iframe JS runs: writes document.cookie (allow-same-origin)
# → calls Streamlit.setComponentValue() → triggers rerun
# → session_state.authenticated=True → home page shown
```

### Delete — `cookie_manager.delete(name)`

```python
# In the logout handler:
cookie_manager.delete(COOKIE_NAME)
st.stop()
# CookieManager iframe JS runs: expires document.cookie
# → calls Streamlit.setComponentValue() → triggers rerun
# → st.context.cookies.get() returns None → login form shown
```

`st.stop()` after each call ensures no further Streamlit output is produced in
the current render. The CookieManager iframe is already in the output buffer,
its JS executes in the browser, and `setComponentValue()` triggers the next rerun.

---

## Complete Auth Flow

### Login

```
User enters username + password, clicks Login
  │
  ├─ verify_user(username, password)
  │    sha256(password) == _USERS[username]  ?
  │    No  → log warning, st.error()  → return (form stays visible)
  │    Yes → continue
  │
  ├─ create_session(username)
  │    token = uuid4()
  │    _SESSION_STORE[token] = { username, created_at, expires_at=now+24h }
  │    return token
  │
  ├─ session_state.authenticated = True
  │    session_state.username = username
  │    session_state.token = token
  │
  └─ cookie_manager.set(COOKIE_NAME, token, expires_at=now+24h)
       st.stop()  ← current render output (login form + CookieManager iframe) sent to browser
       │
       CookieManager iframe JS executes (allow-same-origin):
         document.cookie = "auth_session=<token>; expires=<24h>"
         Streamlit.setComponentValue(...)  ← triggers natural Streamlit rerun
       │
       Rerun arrives at Streamlit server
       session_state.authenticated = True  (already set)
       →  sidebar + home page shown immediately
       │
       (Cookie now also in browser for future reloads/new tabs)
```

### Page Reload / New Tab (existing session)

```
Browser makes HTTP request (reload or new tab)
  │
  ├─ New WebSocket connection → fresh session_state
  │    authenticated = False
  │
  ├─ Auth gate runs:
  │    token = st.context.cookies.get("auth_session")   ← from HTTP request headers
  │    validate_session(token)  →  username
  │    session_state.authenticated = True
  │
  └─ pg.run()  →  correct page rendered at current URL
```

No render #1 / render #2 cycle. No wait. Instant.

### New Browser / Incognito

```
Browser makes HTTP request (no cookie)
  │
  ├─ Auth gate:
  │    st.context.cookies.get("auth_session")  →  None
  │    authenticated = False
  │
  └─ _show_login_form() shown
```

### Logout

```
User clicks Logout button
  │
  ├─ destroy_session(token)      del _SESSION_STORE[token]
  ├─ session_state cleared
  │
  └─ cookie_manager.delete(COOKIE_NAME)
       st.stop()  ← current render output sent to browser
       │
       CookieManager iframe JS executes (allow-same-origin):
         document.cookie = "auth_session=; expires=1970-01-01"
         Streamlit.setComponentValue(...)  ← triggers natural Streamlit rerun
       │
       Rerun arrives at Streamlit server
       session_state.authenticated = False  (already cleared)
       st.context.cookies.get("auth_session")  →  None
       →  login form shown
```

### Session Expiry (no user action)

```
User has a cookie but > 24 hours have passed
  │
  ├─ Auth gate:
  │    st.context.cookies.get("auth_session")  →  token (cookie still in browser)
  │    validate_session(token)
  │      now > expires_at  →  del _SESSION_STORE[token]  →  return None
  │    username = None  →  authenticated = False
  │    log warning "Cookie present but invalid/expired — ignoring"
  │
  └─ _show_login_form() shown
     (stale cookie expires naturally in browser per its expires attribute)
```

---

## What Was Removed vs Previous Approach

| Previous (pure `extra-streamlit-components`) | Current (hybrid) |
|---|---|
| `cookie_manager.get()` for reading | `st.context.cookies.get(name)` — synchronous |
| `cm_ready` flag in session_state | Not needed |
| Render #1 wait (`st.stop()` + `cm_ready` check) | Not needed |
| `st.rerun()` → `st.stop()` workaround in login | `st.stop()` only — same as before, correct reason |
| `st.navigation()` hoisted before auth gate | Natural position, after auth gate |
| `cookie_manager.set()` for writing | `cookie_manager.set()` — unchanged (still needed) |
| `cookie_manager.delete()` for deleting | `cookie_manager.delete()` — unchanged (still needed) |

**What stayed**: `extra-streamlit-components` is still a dependency, used exclusively for **writing and deleting** cookies (its `allow-same-origin` iframe is required for that). The key elimination is `cookie_manager.get()` for reading, replaced by the synchronous `st.context.cookies` API.

---

## MySQL Migration Plan

Only `auth.py` needs to change. `app.py` and pages are unaffected.

### Step 1 — Implement `get_db_connection()`

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

### Step 2 — Replace `verify_user()`

```python
def verify_user(username: str, password: str) -> bool:
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM users WHERE username = %s AND password_hash = %s",
        (username, password_hash),
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None
```

### Step 3 — Replace `create_session()`

```python
def create_session(username: str) -> str:
    token = str(uuid.uuid4())
    expires_at = datetime.now() + timedelta(hours=SESSION_DURATION_HOURS)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (token, username, created_at, expires_at) "
        "VALUES (%s, %s, %s, %s)",
        (token, username, datetime.now(), expires_at),
    )
    conn.commit()
    conn.close()
    return token
```

### Step 4 — Replace `validate_session()`

```python
def validate_session(token: str) -> Optional[str]:
    if not token:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, expires_at FROM sessions WHERE token = %s", (token,)
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    username, expires_at = row
    if datetime.now() > expires_at:
        cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))
        conn.commit()
        conn.close()
        return None
    conn.close()
    return username
```

### Step 5 — Replace `destroy_session()`

```python
def destroy_session(token: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))
    conn.commit()
    conn.close()
```

### Suggested MySQL schema

```sql
CREATE TABLE users (
    username      VARCHAR(64) PRIMARY KEY,
    password_hash CHAR(64) NOT NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sessions (
    token      CHAR(36) PRIMARY KEY,
    username   VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE,
    INDEX idx_expires_at (expires_at)
);
```

---

## Dependencies

```
streamlit>=1.37.0
extra-streamlit-components>=0.1.71
```

For MySQL migration, add:
```
mysql-connector-python>=8.0
```
