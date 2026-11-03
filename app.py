import os
import sys

# Streamlit passes arguments after `--` through to the app script. Persist the
# choice in this process so all multipage views use the same mode.
if "--demo" in sys.argv:
    os.environ["FANTASY_DEMO"] = "1"

import asyncio

if sys.platform == 'win32':
    # Forces Windows to use a selector loop that handles remote resets gracefully
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import streamlit as st
from demo_views import is_demo_mode, render_demo_league
from storage import (
    get_fantasy_matchup_records, get_fantasy_team_profile, get_users,
    initialize_database, is_commissioner,
)

demo_mode = is_demo_mode()
if not demo_mode:
    initialize_database()
    from draft_timer import start_draft_timer_worker
    start_draft_timer_worker()

st.set_page_config(page_title="League | Fantasy LCS", page_icon="🎮", layout="wide")


def league_page():
    if demo_mode:
        render_demo_league()
        return

    from auth import login_form, register_form, logout_button, restore_login_from_cookie
    restore_login_from_cookie()
    from draft import get_settings, get_trade_proposals
    from scoring_rules import render_scoring_rules

    st.title("League")
    st.caption("League of Legends fantasy standings")
    if st.session_state.get("user_id"):
        user_id = int(st.session_state["user_id"])
        st.success(f"Signed in as {st.session_state['display_name']}.")
        if is_commissioner(user_id):
            st.caption("League role: Commissioner")
        settings = get_settings()
        st.subheader("Leaderboard")
        owners = get_users()
        fantasy_records = get_fantasy_matchup_records()
        if owners:
            headers = st.columns([1, 5, 1, 1, 2])
            for column, label in zip(headers[1:], ("Team / owner", "Wins", "Losses", "Total points")):
                column.markdown(f"**{label}**")
            leaderboard = [{
                "owner": owner,
                "wins": fantasy_records.get(owner["id"], {}).get("wins", 0),
                "losses": fantasy_records.get(owner["id"], {}).get("losses", 0),
                "points": fantasy_records.get(owner["id"], {}).get("points", 0.0),
            } for owner in owners]
            leaderboard.sort(key=lambda row: (-row["wins"], -row["points"], row["owner"]["display_name"].casefold()))
            for row in leaderboard:
                owner = row["owner"]
                with st.container(border=True):
                    image_col, team_col, wins_col, losses_col, points_col = st.columns([1, 5, 1, 1, 2])
                    profile = get_fantasy_team_profile(owner["id"])
                    if profile and profile.get("team_image"):
                        image_col.image(profile["team_image"], width=64)
                    team_col.page_link(
                        "pages/1_Roster.py",
                        label=profile["team_name"] if profile else f"{owner['display_name']} Team",
                        query_params={"owner_id": owner["id"]},
                    )
                    team_col.caption(owner["display_name"])
                    wins_col.write(row["wins"])
                    losses_col.write(row["losses"])
                    points_col.write(f"{row['points']:.2f}")
            st.caption("Matchup records and total points reflect the latest commissioner scoring refresh.")

            completed_trades = [
                trade for trade in get_trade_proposals()
                if trade["status"] == "approved"
            ]
            st.subheader("Completed trades")
            if completed_trades:
                role_labels = {
                    "team": "Org", "top": "Top", "jg": "Jungle",
                    "mid": "Mid", "adc": "Bot", "sup": "Support",
                }
                for trade in completed_trades:
                    offered_role = role_labels.get(trade["offered_role"], trade["offered_role"].upper())
                    requested_role = role_labels.get(trade["requested_role"], trade["requested_role"].upper())
                    with st.container(border=True):
                        st.markdown(
                            f"**{trade['proposer_name']}** traded **{trade['offered_player_name']}** "
                            f"({offered_role} · {trade['offered_team']}) to **{trade['recipient_name']}** "
                            f"for **{trade['requested_player_name']}** "
                            f"({requested_role} · {trade['requested_team']})."
                        )
                        if trade.get("resolved_at"):
                            st.caption(f"Approved {trade['resolved_at']} UTC")
            else:
                st.caption("No trades have been completed yet.")
        else:
            st.info("Create league owner accounts to populate the leaderboard.")
        st.caption(f"{settings['league_name']} · {settings['region']}")
        render_scoring_rules()
        st.write("Use **Draft** to set up or make picks, **Roster** to manage your team, and **Matchups** to follow games.")
        logout_button()
    else:
        login_tab, register_tab = st.tabs(["Log in", "Create account"])
        with login_tab:
            login_form()
        with register_tab:
            register_form()


navigation = st.navigation([
    st.Page(league_page, title="League", icon="🏆", default=True),
    st.Page("pages/0_Draft.py", title="Draft", icon="📝"),
    st.Page("pages/6_My_Team.py", title="My Team", icon="🛡️"),
    st.Page("pages/7_My_Matchup.py", title="My Matchup", icon="⚔️"),
    st.Page("pages/1_Roster.py", title="Roster", icon="👥"),
    st.Page("pages/2_Matchups.py", title="Matchups", icon="⚔️"),
    st.Page("pages/3_Commissioner.py", title="Commissioner", icon="👑"),
    st.Page("pages/4_Players.py", title="Players", icon="📊"),
    st.Page("pages/5_Past_Stats.py", title="Past Stats", icon="📚"),
])
navigation.run()
