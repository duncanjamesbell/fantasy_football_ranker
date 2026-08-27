"""
Lightweight shared-passphrase gate -- not real user accounts. Appropriate
for ~11 known league members, not a public product. The passphrase lives in
st.secrets (set via .streamlit/secrets.toml locally, gitignored; via the
Streamlit Community Cloud dashboard's Secrets panel when deployed) and is
never hardcoded or committed.
"""

import hmac

import streamlit as st


def _autofocus_passphrase_input() -> None:
    """st.text_input has no native autofocus param. Works around it by
    embedding a hidden iframe whose script reaches into the parent document
    (same-origin as the app itself, so this is allowed) and focuses the
    passphrase field directly. Retries briefly since this iframe can mount
    before the input's own DOM node does."""
    st.iframe(
        """
        <script>
        (function focusPassphraseInput(attemptsLeft) {
            const input = window.parent.document.querySelector(".stTextInput input");
            if (input) {
                input.focus();
            } else if (attemptsLeft > 0) {
                setTimeout(() => focusPassphraseInput(attemptsLeft - 1), 100);
            }
        })(20);
        </script>
        """,
        height=1,
    )


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
    _autofocus_passphrase_input()

    if submitted:
        expected = st.secrets.get("APP_PASSPHRASE", "")
        if expected and hmac.compare_digest(entered, expected):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect passphrase.")

    st.stop()
