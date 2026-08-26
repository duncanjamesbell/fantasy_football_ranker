"""
Lightweight shared-passphrase gate -- not real user accounts. Appropriate
for ~11 known league members, not a public product. The passphrase lives in
st.secrets (set via .streamlit/secrets.toml locally, gitignored; via the
Streamlit Community Cloud dashboard's Secrets panel when deployed) and is
never hardcoded or committed.
"""

import hmac

import streamlit as st


def require_passphrase() -> None:
    """Blocks the rest of the app (via st.stop()) until the correct
    passphrase is entered. Persists for the current browser session only."""
    if st.session_state.get("authed"):
        return

    st.title("PRE Fantasy Football Composite Ranks")
    # st.form makes Enter-to-submit native: pressing Enter while focused in a
    # form's text_input submits the form, same as clicking its submit button
    # -- a plain st.button alongside a bare text_input doesn't get that.
    with st.form("passphrase_form"):
        entered = st.text_input("Passphrase", type="password")
        submitted = st.form_submit_button("Enter")

    if submitted:
        expected = st.secrets.get("APP_PASSPHRASE", "")
        if expected and hmac.compare_digest(entered, expected):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect passphrase.")

    st.stop()
