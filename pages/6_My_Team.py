import streamlit as st

from auth import logout_button, require_login
from demo_views import is_demo_mode, render_demo_my_team
from draft import get_settings, get_user_picks
from storage import (
    SLOTS,
    clear_fantasy_team_image,
    get_fantasy_team_profile,
    rename_fantasy_team,
    save_fantasy_team_image,
)
from utils.player_images import render_org_logo, render_player_image
from utils.team_images import normalize_team_image


if is_demo_mode():
    render_demo_my_team()
    st.stop()

user_id = require_login()
settings = get_settings()
profile = get_fantasy_team_profile(user_id)
if not profile:
    st.error("Your fantasy team profile could not be found.")
    st.stop()

name_width = min(max(len(profile["team_name"]) * 0.26, 0.8), 12)
title_col, edit_col, _ = st.columns([name_width, 0.5, 10])
title_col.title(profile["team_name"])
with edit_col:
    with st.popover("✏️", help="Edit team name", width="content"):
        with st.form("rename_team_form"):
            new_team_name = st.text_input("Team name", value=profile["team_name"], max_chars=50)
            rename_submitted = st.form_submit_button("Save team name", type="primary")
        if rename_submitted:
            try:
                rename_fantasy_team(user_id, new_team_name)
                st.success("Team name updated.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
st.caption(f"{settings['league_name']} · {settings['region']}")

image_col, _ = st.columns([1, 3])
uploaded = None
save_image = False
with image_col:
    preview_col, controls_col = st.columns([5, 1])
    if profile.get("team_image"):
        preview_col.image(profile["team_image"], width=180)
    else:
        preview_col.caption("No image")
    with controls_col:
        with st.popover("✏️", help="Edit team image", width="content"):
            st.caption("Upload a PNG, JPG, or WebP image.")
            with st.form("team_image_upload_form"):
                uploaded = st.file_uploader(
                    "Choose an image", type=["png", "jpg", "jpeg", "webp"], key="team_image_upload"
                )
                save_image = st.form_submit_button("Save image", type="primary")
        if profile.get("team_image") and st.button(
            "🗑️", help="Remove team image", key="remove_team_image", width="content"
        ):
            clear_fantasy_team_image(user_id)
            st.rerun()
    if save_image:
        if not uploaded:
            st.error("Choose an image first.")
        else:
            try:
                normalized = normalize_team_image(uploaded)
                save_fantasy_team_image(user_id, normalized)
                st.success("Team image saved.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
st.divider()
st.subheader("Your roster")
if settings["status"] == "setup":
    st.info("Your roster will be filled through the snake draft once the commissioner starts it.")
else:
    picks = get_user_picks(user_id)
    by_slot = {pick["roster_slot"]: pick for pick in picks}
    cols = st.columns(3)
    for index, slot in enumerate(SLOTS):
        with cols[index % 3]:
            pick = by_slot.get(slot)
            st.subheader("Team org" if slot == "team" else slot.upper())
            if pick:
                if slot != "team":
                    player_image_col, player_col = st.columns([1, 3])
                    with player_image_col:
                        render_player_image(pick.get("image_url"), size=76)
                    with player_col:
                        st.write(f"**{pick['player_name']}**")
                        if pick.get("team_name"):
                            st.caption(pick["team_name"])
                else:
                    org_image_col, org_col = st.columns([1, 3])
                    with org_image_col:
                        render_org_logo(pick.get("image_url"), size=76)
                    with org_col:
                        st.write(f"**{pick['player_name']}**")
            else:
                st.caption("Waiting for draft pick")
    st.caption(f"{len(picks)} of {len(SLOTS)} roster slots drafted.")

logout_button()
