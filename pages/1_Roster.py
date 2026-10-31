import streamlit as st
from demo_views import is_demo_mode, render_demo_rosters

if is_demo_mode():
    render_demo_rosters()
    st.stop()

from auth import logout_button, require_login
from draft import (
    cancel_trade,
    get_settings,
    get_trade_proposals,
    get_user_picks,
    propose_trade,
    respond_to_trade,
)
from storage import SLOTS, get_fantasy_team_profile, get_users
from utils.player_images import render_player_image

user_id = require_login()
settings = get_settings()
users = {u["id"]: u for u in get_users()}
roster_owner_id = user_id
requested_owner_id = st.query_params.get("owner_id")
if requested_owner_id:
    try:
        candidate_owner_id = int(requested_owner_id)
        if candidate_owner_id in users:
            roster_owner_id = candidate_owner_id
    except (TypeError, ValueError):
        pass

st.title("Roster")
st.caption("Drafted roster slots stay fixed. Approved trades and eligible player exchanges can change their players.")
team_profile = get_fantasy_team_profile(roster_owner_id)
if team_profile and team_profile.get("team_image"):
    st.image(team_profile["team_image"], width=180)
if settings["status"] == "setup":
    st.info("The commissioner has not started the draft. Your roster will be filled through the snake draft.")
else:
    user = users.get(roster_owner_id)
    if user:
        st.subheader(team_profile["team_name"] if team_profile else f"{user['display_name']} Team")
        st.caption(user["display_name"])
        if roster_owner_id != user_id:
            st.caption("Viewing another team’s roster.")
    st.caption(f"{settings['league_name']} · {settings['region']}")
    picks = get_user_picks(roster_owner_id)
    by_slot = {pick["roster_slot"]: pick for pick in picks}
    cols = st.columns(3)
    for index, slot in enumerate(SLOTS):
        with cols[index % 3]:
            pick = by_slot.get(slot)
            st.subheader("Team org" if slot == "team" else slot.upper())
            if pick:
                if slot != "team":
                    image_col, player_col = st.columns([1, 3])
                    with image_col:
                        render_player_image(pick.get("image_url"), size=76)
                    with player_col:
                        st.write(f"**{pick['player_name']}**")
                        if pick["team_name"]:
                            st.caption(pick["team_name"])
                else:
                    st.write(f"**{pick['player_name']}**")
            else:
                st.caption("Waiting for draft pick")
    st.caption(f"{len(picks)} of {len(SLOTS)} roster slots drafted.")

    if settings["status"] == "complete" and roster_owner_id == user_id:
        st.divider()
        st.subheader("Propose a trade")
        opponents = [other for other in users.values() if other["id"] != user_id]
        if not opponents:
            st.info("There are no other team owners to trade with yet.")
        elif not picks:
            st.info("Your roster is empty, so you cannot propose a trade.")
        else:
            opponent_id = st.selectbox(
                "Trade with",
                [other["id"] for other in opponents],
                format_func=lambda value: users[value]["display_name"],
                key="trade_opponent",
            )
            opponent_picks = get_user_picks(opponent_id)
            tradable_slots = [
                pick["roster_slot"] for pick in picks
                if any(other_pick["roster_slot"] == pick["roster_slot"] for other_pick in opponent_picks)
            ]
            if not tradable_slots:
                st.info("No matching roster slots are available for a one-for-one trade.")
            else:
                slot = st.selectbox(
                    "Roster slot", tradable_slots,
                    format_func=lambda value: "Team org" if value == "team" else value.upper(),
                    key="trade_slot",
                )
                offered_choices = [pick for pick in picks if pick["roster_slot"] == slot]
                requested_choices = [pick for pick in opponent_picks if pick["roster_slot"] == slot]
                offered_by_id = {pick["player_id"]: pick for pick in offered_choices}
                requested_by_id = {pick["player_id"]: pick for pick in requested_choices}
                offered = st.selectbox(
                    "You offer",
                    list(offered_by_id),
                    format_func=lambda player_id: f"{offered_by_id[player_id]['player_name']} · {offered_by_id[player_id]['team_name'] or 'Team org'}",
                    key="trade_offered_player",
                )
                with st.form("propose_trade_form"):
                    requested = st.selectbox(
                        f"Request from {users[opponent_id]['display_name']}",
                        list(requested_by_id),
                        format_func=lambda player_id: f"{requested_by_id[player_id]['player_name']} · {requested_by_id[player_id]['team_name'] or 'Team org'}",
                    )
                    submit_trade = st.form_submit_button("Send trade proposal", type="primary")
                st.caption("The other owner must accept first. The commissioner must then approve it before rosters change.")
                if submit_trade:
                    try:
                        propose_trade(user_id, opponent_id, offered, requested)
                        st.success("Trade proposal sent.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

        st.subheader("Your trade proposals")
        proposals = get_trade_proposals(user_id)
        if not proposals:
            st.caption("You have no trade proposals yet.")
        for trade in proposals:
            is_recipient = trade["recipient_user_id"] == user_id
            is_proposer = trade["proposer_user_id"] == user_id
            other_owner = trade["proposer_name"] if is_recipient else trade["recipient_name"]
            owner_verb = "from" if is_recipient else "to"
            offered_role = "Org" if trade["offered_role"] == "team" else trade["offered_role"].upper()
            requested_role = "Org" if trade["requested_role"] == "team" else trade["requested_role"].upper()
            with st.container(border=True):
                st.markdown(
                    f"**{trade['proposer_name']}** offers {trade['offered_player_name']} ({offered_role}) "
                    f"for {trade['requested_player_name']} ({requested_role}) · {owner_verb} **{other_owner}**"
                )
                st.caption(f"Status: {trade['status'].replace('_', ' ').title()} · {trade['created_at']}")
                if is_recipient and trade["status"] == "proposed":
                    accept_col, decline_col = st.columns(2)
                    if accept_col.button("Accept", key=f"accept_trade_{trade['id']}", type="primary"):
                        try:
                            respond_to_trade(trade["id"], user_id, accept=True)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                    if decline_col.button("Decline", key=f"decline_trade_{trade['id']}"):
                        try:
                            respond_to_trade(trade["id"], user_id, accept=False)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                elif is_proposer and trade["status"] in {"proposed", "accepted"}:
                    if st.button("Cancel proposal", key=f"cancel_trade_{trade['id']}"):
                        try:
                            cancel_trade(trade["id"], user_id)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
    elif settings["status"] == "complete" and roster_owner_id != user_id:
        st.caption("Return to your own roster to propose or respond to trades.")
logout_button()
