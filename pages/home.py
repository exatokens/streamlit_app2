"""
pages/home.py — Home page of the application.

Displays a personalised welcome message using the authenticated username from
st.session_state. Authentication is guaranteed by the gate in app.py, so this
page can safely read st.session_state.username without additional checks.
"""

import streamlit as st
from datetime import datetime


def render() -> None:
    """Render the Home page content.

    Reads the current user's name from st.session_state and displays a
    personalised greeting along with placeholder dashboard content.

    Returns:
        None
    """
    username = st.session_state.get("username", "User")

    st.title("🏠 Home")
    st.markdown(f"Hello, **{username}**! You are successfully logged in.")
    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(label="Active Users", value="42", delta="+3")
    with col2:
        st.metric(label="Tasks Completed", value="128", delta="+12")
    with col3:
        st.metric(label="Uptime", value="99.9%", delta="0.1%")

    st.markdown("---")
    st.subheader("Quick Notes")
    st.info(
        "This is the **Home** page. "
        "Use the sidebar to navigate to other pages. "
        "Your session is preserved across page reloads and new tabs "
        "within the same browser."
    )

    st.markdown("#### Session Details")
    st.markdown(f"- **Logged in as:** `{username}`")
    st.markdown(f"- **Current time:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    st.markdown(
        "- **Token (first 8 chars):** "
        f"`{str(st.session_state.get('token', ''))[:8]}...`"
    )


render()
