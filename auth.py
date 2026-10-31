import hashlib
import hmac
import secrets

import streamlit as st

from storage import create_user, find_user, get_user_access

_ITERATIONS = 310_000


def _hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return salt.hex(), digest.hex()


def _verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), _ITERATIONS)
    return hmac.compare_digest(digest.hex(), digest_hex)


def login_form() -> None:
    with st.form("login"):
        username = st.text_input("Username").strip().lower()
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary", use_container_width=True)
    if submitted:
        user = find_user(username)
        if user and _verify_password(password, user["password_salt"], user["password_hash"]):
            if not user.get("is_active", 1):
                st.error("This account has been removed. Contact the commissioner.")
                return
            if not user.get("is_approved", 1):
                st.info("Your account is waiting for commissioner approval.")
                return
            st.session_state["user_id"] = user["id"]
            st.session_state["display_name"] = user["display_name"]
            st.rerun()
        st.error("Username or password is incorrect.")


def register_form() -> None:
    with st.form("register"):
        display_name = st.text_input("Team owner name", max_chars=60).strip()
        username = st.text_input("Choose a username", max_chars=40).strip().lower()
        password = st.text_input("Choose a password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create account", type="primary", use_container_width=True)
    if not submitted:
        return
    if not display_name or len(username) < 3:
        st.error("Enter an owner name and a username with at least 3 characters.")
        return
    if len(password) < 12:
        st.error("Use a password with at least 12 characters.")
        return
    if password != confirm:
        st.error("The passwords do not match.")
        return
    salt, digest = _hash_password(password)
    try:
        user_id = create_user(username, display_name, salt, digest)
    except ValueError as exc:
        st.error(str(exc))
        return
    account = get_user_access(user_id)
    if account and account["is_approved"] and account["is_active"]:
        st.session_state["user_id"] = user_id
        st.session_state["display_name"] = display_name
        st.rerun()
    st.success("Account request submitted.")
    st.info("You can log in after the commissioner approves your account.")


def require_login() -> int:
    user_id = st.session_state.get("user_id")
    if user_id:
        account = get_user_access(int(user_id))
        if account and account["is_active"] and account["is_approved"]:
            st.session_state["display_name"] = account["display_name"]
            return int(user_id)
        st.session_state.pop("user_id", None)
        st.session_state.pop("display_name", None)
        if account and not account["is_approved"]:
            st.warning("Your account is waiting for commissioner approval.")
        else:
            st.warning("This account has been removed or is no longer active.")
    st.info("Log in from the Fantasy LCS home page to continue.")
    st.stop()
    raise RuntimeError("Authentication required")


def logout_button() -> None:
    if st.button("Log out", key="logout"):
        st.session_state.pop("user_id", None)
        st.session_state.pop("display_name", None)
        st.rerun()
