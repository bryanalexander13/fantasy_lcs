import hashlib
import hmac
import secrets

import streamlit as st

from storage import (
    create_remember_token,
    create_user,
    find_user,
    get_user_access,
    get_user_by_remember_token,
    revoke_remember_token,
)

_ITERATIONS = 310_000
_REMEMBER_COOKIE = "fantasy_lcs_remember"
_REMEMBER_DAYS = 30
_COOKIE_MANAGER_STATE = "_fantasy_lcs_cookie_manager"


def _cookie_manager():
    manager = st.session_state.get(_COOKIE_MANAGER_STATE)
    if manager is None:
        import extra_streamlit_components as stx
        manager = stx.CookieManager(key="fantasy_lcs_auth_cookie_manager")
        st.session_state[_COOKIE_MANAGER_STATE] = manager
    if manager.cookies is None:
        manager.cookies = {}
    return manager


def _cookie_operation_key(token: str) -> str:
    token_id = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"fantasy_lcs_remember_{token_id}"


def _delete_remember_cookie(token: str, cookie_manager=None) -> None:
    manager = cookie_manager or _cookie_manager()
    # CookieManager.delete removes the name from its local map after asking the
    # browser to delete it; seed the map in case the component hasn't returned yet.
    if manager.cookies is None:
        manager.cookies = {}
    manager.cookies[_REMEMBER_COOKIE] = token
    manager.delete(_REMEMBER_COOKIE, key=_cookie_operation_key(token))


def _request_remember_cookie(cookie_manager=None) -> str | None:
    try:
        value = st.context.cookies.get(_REMEMBER_COOKIE)
    except Exception:
        value = None
    if value:
        return str(value)

    manager = cookie_manager or _cookie_manager()
    cookies = manager.get_all(key="fantasy_lcs_remember_cookie_reader") or {}
    manager.cookies = cookies
    value = cookies.get(_REMEMBER_COOKIE)
    return str(value) if value else None


def _cookie_is_secure() -> bool:
    try:
        return str(st.context.url).lower().startswith("https://")
    except Exception:
        return False


def _establish_login(user_id: int, display_name: str, keep_signed_in: bool, cookie_manager) -> None:
    st.session_state["user_id"] = int(user_id)
    st.session_state["display_name"] = display_name
    if keep_signed_in:
        token, expires_at = create_remember_token(user_id, _REMEMBER_DAYS)
        st.session_state["_remember_token"] = token
        cookie_manager.set(
            _REMEMBER_COOKIE,
            token,
            key=_cookie_operation_key(token),
            path="/",
            expires_at=expires_at,
            secure=_cookie_is_secure(),
            same_site="strict",
        )


def restore_login_from_cookie() -> int | None:
    """Restore an authenticated user from the optional 30-day browser cookie."""
    current_user_id = st.session_state.get("user_id")
    if current_user_id:
        account = get_user_access(int(current_user_id))
        if account and account["is_active"] and account["is_approved"]:
            return int(current_user_id)
        st.session_state.pop("user_id", None)
        st.session_state.pop("display_name", None)
        token = st.session_state.pop("_remember_token", None) or _request_remember_cookie()
        if token:
            revoke_remember_token(token)
            _delete_remember_cookie(token)
            return None

    token = _request_remember_cookie()
    if not token:
        return None
    account = get_user_by_remember_token(token)
    if account:
        st.session_state["user_id"] = account["id"]
        st.session_state["display_name"] = account["display_name"]
        st.session_state["_remember_token"] = token
        return int(account["id"])
    revoke_remember_token(token)
    _delete_remember_cookie(token)
    return None


def _hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return salt.hex(), digest.hex()


def _verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), _ITERATIONS)
    return hmac.compare_digest(digest.hex(), digest_hex)


def login_form() -> None:
    cookie_manager = _cookie_manager()
    with st.form("login"):
        username = st.text_input("Username").strip().lower()
        password = st.text_input("Password", type="password")
        keep_signed_in = st.checkbox("Keep me signed in on this device for 30 days", value=True)
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
            _establish_login(user["id"], user["display_name"], keep_signed_in, cookie_manager)
            if not keep_signed_in:
                st.rerun()
            return
        st.error("Username or password is incorrect.")


def register_form() -> None:
    cookie_manager = _cookie_manager()
    with st.form("register"):
        display_name = st.text_input("Team owner name", max_chars=60).strip()
        username = st.text_input("Choose a username", max_chars=40).strip().lower()
        password = st.text_input("Choose a password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        keep_signed_in = st.checkbox("Keep me signed in on this device for 30 days", value=True)
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
        _establish_login(user_id, display_name, keep_signed_in, cookie_manager)
        if not keep_signed_in:
            st.rerun()
        return
    st.success("Account request submitted.")
    st.info("You can log in after the commissioner approves your account.")


def require_login() -> int:
    restore_login_from_cookie()
    user_id = st.session_state.get("user_id")
    if user_id:
        account = get_user_access(int(user_id))
        if account and account["is_active"] and account["is_approved"]:
            st.session_state["display_name"] = account["display_name"]
            return int(user_id)
        st.session_state.pop("user_id", None)
        st.session_state.pop("display_name", None)
        token = st.session_state.pop("_remember_token", None)
        if token:
            revoke_remember_token(token)
            _delete_remember_cookie(token)
        if account and not account["is_approved"]:
            st.warning("Your account is waiting for commissioner approval.")
        else:
            st.warning("This account has been removed or is no longer active.")
    st.info("Log in from the Fantasy LCS home page to continue.")
    st.stop()
    raise RuntimeError("Authentication required")


def logout_button() -> None:
    token = st.session_state.get("_remember_token") or _request_remember_cookie()
    cookie_manager = _cookie_manager() if token else None
    if st.button("Log out", key="logout"):
        if token:
            revoke_remember_token(token)
            _delete_remember_cookie(token, cookie_manager)
        st.session_state.pop("user_id", None)
        st.session_state.pop("display_name", None)
        st.session_state.pop("_remember_token", None)
        st.rerun()
