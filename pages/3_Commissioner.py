import streamlit as st
from demo_views import is_demo_mode

if is_demo_mode():
    st.title("Commissioner")
    st.info("Commissioner controls are available in a regular league, not in the read-only demo.")
    st.stop()

from auth import logout_button, require_login
from draft import get_settings, get_trade_proposals, resolve_trade
from demo_data import load_spring_2026_data, load_summer_2026_data
from storage import (
    approve_user_account,
    get_user_accounts,
    is_commissioner,
    remove_user_account,
    clear_draft_results,
    reset_league_information,
)
from utils.lcs_api_wrapper import LoLEsportsAPIError

user_id = require_login()
if not is_commissioner(user_id):
    st.title("Commissioner")
    st.info("This page is available to the league commissioner.")
    logout_button()
    st.stop()

settings = get_settings()
st.title("Commissioner")
st.caption("Manage trade approvals and review the league draft schedule.")

st.subheader("Accounts")
accounts = get_user_accounts()
pending_accounts = [account for account in accounts
                    if account["is_active"] and not account["is_approved"]]
active_accounts = [account for account in accounts
                   if account["is_active"] and account["is_approved"]]
if pending_accounts:
    st.markdown("**Waiting for approval**")
    for account in pending_accounts:
        with st.container(border=True):
            name_col, approve_col, remove_col = st.columns([5, 1.4, 1.6])
            name_col.markdown(f"**{account['display_name']}** · @{account['username']}")
            name_col.caption(f"Requested {account['created_at']}")
            if approve_col.button("Approve", key=f"approve_account_{account['id']}", type="primary"):
                try:
                    approve_user_account(user_id, account["id"])
                    st.success(f"Approved {account['display_name']}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            with remove_col.popover("Remove account"):
                st.caption("This deletes the pending account and its login.")
                with st.form(f"remove_pending_account_form_{account['id']}"):
                    confirm_remove = st.checkbox("Confirm removal", key=f"confirm_pending_{account['id']}")
                    remove_submitted = st.form_submit_button("Remove account", type="primary")
                if remove_submitted:
                    if not confirm_remove:
                        st.error("Confirm removal before continuing.")
                    else:
                        try:
                            remove_user_account(user_id, account["id"])
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
else:
    st.caption("There are no accounts waiting for approval.")

st.markdown("**League accounts**")
for account in active_accounts:
    with st.container(border=True):
        name_col, role_col, action_col = st.columns([5, 1.6, 1.8])
        name_col.markdown(f"**{account['display_name']}** · @{account['username']}")
        role_col.caption("Commissioner" if is_commissioner(account["id"]) else "Team owner")
        if account["id"] == user_id:
            action_col.caption("Your account")
        else:
            with action_col.popover("Remove account"):
                if settings.get("status") == "complete":
                    st.caption("Sign-in will be disabled and the team removed from Draft order. Its saved rosters and league history will remain.")
                elif settings.get("status") == "setup":
                    st.caption("This deletes the account. If the draft order was locked, it will need to be randomized again.")
                else:
                    st.caption("Accounts cannot be removed during an active draft.")
                with st.form(f"remove_account_form_{account['id']}"):
                    confirm_remove = st.checkbox("Confirm removal", key=f"confirm_account_{account['id']}")
                    remove_submitted = st.form_submit_button(
                        "Remove account", type="primary",
                        disabled=settings.get("status") == "in_progress",
                    )
                if remove_submitted:
                    if not confirm_remove:
                        st.error("Confirm removal before continuing.")
                    else:
                        try:
                            result = remove_user_account(user_id, account["id"])
                            if result == "deleted":
                                st.success(f"Removed {account['display_name']}.")
                            else:
                                st.success(f"Removed {account['display_name']}'s sign-in; league history was preserved.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))

st.subheader("Season data")
st.caption("Refresh the saved regular-season API data. Other league members can view the refreshed stats.")
summer_col, spring_col = st.columns(2)
with summer_col:
    if st.button("Load Summer 2026 data from API", key="load_summer_api"):
        try:
            with st.spinner("Loading Summer 2026 data from the LoL Esports API…"):
                data = load_summer_2026_data(refresh=True)
            st.success(f"Saved {data.get('games_loaded', 0)} Summer 2026 games.")
        except (LoLEsportsAPIError, OSError, ValueError) as exc:
            st.error(f"Couldn't load Summer 2026 data: {exc}")
with spring_col:
    if st.button("Load Spring 2026 data from API", key="load_spring_api"):
        try:
            with st.spinner("Loading Spring 2026 data from the LoL Esports API…"):
                data = load_spring_2026_data(refresh=True)
            st.success(f"Saved {data.get('games_loaded', 0)} Spring 2026 games.")
        except (LoLEsportsAPIError, OSError, ValueError) as exc:
            st.error(f"Couldn't load Spring 2026 data: {exc}")

if settings.get("scheduled_at"):
    st.metric("Draft date and time", f"{settings['scheduled_at']} (local time)")
else:
    st.info("No draft date and time has been set yet. Set it in the Draft page commissioner controls.")

st.subheader("League controls")
control_cols = st.columns(2, gap="large")
with control_cols[0]:
    with st.popover("Clear draft results", width="stretch"):
        st.caption(
            "Removes drafted rosters, schedule, trades, champion picks/bans, and the saved draft order, then reopens the draft. "
            "The imported player pool is kept, and the commissioner can randomize a new order."
        )
        with st.form("clear_draft_results_form"):
            confirm_clear_draft = st.checkbox("I understand this clears draft results, matchup data, and the saved draft order.")
            clear_draft_submitted = st.form_submit_button(
                "Clear draft results",
                type="primary",
                disabled=settings.get("status") == "in_progress",
                width="stretch",
            )
        if settings.get("status") == "in_progress":
            st.warning("Finish or stop the active draft before clearing its results.")
        if clear_draft_submitted:
            if not confirm_clear_draft:
                st.error("Confirm that you want to clear draft results before continuing.")
            else:
                try:
                    clear_draft_results(user_id)
                    st.success("Draft results and order cleared. The imported player pool is ready for a new draft order.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
with control_cols[1]:
    with st.popover("Reset league information", width="stretch"):
        st.caption(
            "Clears the player pool, draft order and results, league schedule, trades, matchup picks/bans, "
            "and custom team names/images. Member accounts, sign-ins, saved API match history, and past-season stats remain."
        )
        with st.form("reset_league_information_form"):
            reset_phrase = st.text_input("Type RESET to confirm")
            reset_league_submitted = st.form_submit_button(
                "Reset league information",
                type="primary",
                disabled=settings.get("status") == "in_progress",
                width="stretch",
            )
        if settings.get("status") == "in_progress":
            st.warning("Finish or stop the active draft before resetting the league.")
        if reset_league_submitted:
            if reset_phrase.strip().upper() != "RESET":
                st.error("Type RESET to confirm the league reset.")
            else:
                try:
                    reset_league_information(user_id)
                    st.success("League information reset. Member accounts and saved API history were preserved.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

st.subheader("Trade proposals awaiting review")
pending = get_trade_proposals(pending_only=True)
if not pending:
    st.info("There are no trades awaiting review.")
else:
    for trade in pending:
        offered_role = "Team org" if trade["offered_role"] == "team" else trade["offered_role"].upper()
        requested_role = "Team org" if trade["requested_role"] == "team" else trade["requested_role"].upper()
        with st.container(border=True):
            st.markdown(
                f"**{trade['proposer_name']}** offers **{trade['offered_player_name']}** "
                f"({offered_role}, {trade['offered_team']}) for **{trade['requested_player_name']}** "
                f"({requested_role}, {trade['requested_team']}) from **{trade['recipient_name']}**."
            )
            if trade["status"] == "proposed":
                st.caption(f"Waiting for {trade['recipient_name']} to accept or decline · proposed {trade['created_at']}")
            else:
                st.caption(f"Accepted by {trade['recipient_name']} · proposed {trade['created_at']}")
            approve_col, reject_col = st.columns(2)
            approve_disabled = trade["status"] != "accepted"
            if approve_col.button("Approve trade", key=f"approve_trade_{trade['id']}",
                                  type="primary", disabled=approve_disabled):
                try:
                    resolve_trade(trade["id"], user_id, approve=True)
                    st.success("Trade approved and rosters updated.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if reject_col.button("Reject trade", key=f"reject_trade_{trade['id']}"):
                try:
                    resolve_trade(trade["id"], user_id, approve=False)
                    st.success("Trade rejected.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

st.subheader("Recent trade decisions")
history = [trade for trade in get_trade_proposals() if trade["status"] in {"approved", "rejected", "cancelled"}]
if history:
    st.dataframe([{
        "Proposer": trade["proposer_name"], "Recipient": trade["recipient_name"],
        "Offer": trade["offered_player_name"], "Requested": trade["requested_player_name"],
        "Status": trade["status"].title(), "Updated": trade["resolved_at"] or trade["created_at"],
    } for trade in history[:20]], hide_index=True, use_container_width=True)
else:
    st.caption("No completed trade decisions yet.")

logout_button()
