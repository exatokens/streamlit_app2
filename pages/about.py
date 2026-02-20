"""
pages/about.py — About page of the application.

Displays static application information such as version, tech stack, and
a description of how the authentication system works. Authentication is
guaranteed by the gate in app.py.
"""

import streamlit as st


def render() -> None:
    """Render the About page content.

    Shows app description, version info, and an explanation of the
    session/cookie-based authentication mechanism.

    Returns:
        None
    """
    st.title("ℹ️ About")
    st.markdown("---")

    st.subheader("Application")
    st.markdown(
        """
        This is a demo Streamlit app showcasing browser-cookie-based authentication
        with server-side session management.
        """
    )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Version:** `1.0.0`")
        st.markdown("**Framework:** Streamlit")
    with col2:
        st.markdown("**Auth:** Cookie + Server-side sessions")
        st.markdown("**Storage:** In-memory (MySQL-ready)")

    st.markdown("---")
    st.subheader("How Authentication Works")

    st.markdown(
        """
        | Scenario | Behaviour |
        |---|---|
        | Login | Generates a UUID session token, stores it server-side, sets a browser cookie |
        | Page reload | Reads cookie → validates token → restores session automatically |
        | New tab (same browser) | Browser shares cookie → same token → auto-login, no prompt |
        | Different browser | No shared cookie → must log in separately |
        | Server restart | In-memory store cleared → cookie token invalid → must re-login |
        | Logout | Deletes server-side session + browser cookie |
        """
    )

    st.markdown("---")
    st.subheader("Tech Stack")
    st.markdown(
        """
        - **[Streamlit](https://streamlit.io)** — UI framework
        - **[extra-streamlit-components](https://github.com/nicedouble/StreamlitAntdComponents)** — Cookie management
        - **Python stdlib** — `uuid`, `hashlib`, `datetime`
        - **MySQL** *(planned)* — Replace in-memory dicts via `get_db_connection()`
        """
    )

    st.info(
        "To upgrade to a real MySQL database, implement `get_db_connection()` "
        "in `auth.py` and replace the `_USERS` / `_SESSION_STORE` lookups with "
        "SQL queries."
    )


render()
