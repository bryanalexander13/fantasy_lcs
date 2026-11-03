import streamlit as st
import json

from demo_views import is_demo_mode, render_demo_my_matchup


if is_demo_mode():
    render_demo_my_matchup()
    st.stop()

from auth import logout_button, require_login
from storage import get_fantasy_team_profile, get_user_fantasy_matchup_schedule, get_weekly_dragon_bonus
from scoring_rules import render_weekly_dragon_bonus

user_id = require_login()
profile = get_fantasy_team_profile(user_id) or {}

st.title("My Matchup")
team_name = profile.get("team_name") or "Your team"
if profile.get("team_image"):
    st.image(profile["team_image"], width=112)
st.subheader(team_name)
schedule = get_user_fantasy_matchup_schedule(user_id)
if not schedule:
    st.info("Your fantasy schedule will appear here once the draft is complete.")
else:
    weeks = sorted({row["week_number"] for row in schedule})
    week = st.selectbox("Schedule week", weeks, format_func=lambda value: f"Week {value}")
    render_weekly_dragon_bonus(get_weekly_dragon_bonus(week))
    matchup = next(row for row in schedule if row["week_number"] == week)
    is_team_1 = int(matchup["team_1_user_id"]) == int(user_id)
    if is_team_1:
        opponent_name = matchup["team_2_name"]
        opponent_owner = matchup["team_2_owner"]
        is_bye = matchup["team_2_user_id"] is None
    else:
        opponent_name = matchup["team_1_name"]
        opponent_owner = matchup["team_1_owner"]
        is_bye = False
    st.markdown(f"### Week {week}")
    if is_bye:
        st.info("Your team has a bye this week.")
    else:
        st.markdown(f"**Opponent:** {opponent_name}  \n**Owner:** {opponent_owner}")
        if matchup.get("team_1_score") is None or matchup.get("team_2_score") is None:
            st.info("Matchup points will appear after the commissioner refreshes current split data and fantasy points.")
        else:
            my_score = matchup["team_1_score"] if is_team_1 else matchup["team_2_score"]
            opponent_score = matchup["team_2_score"] if is_team_1 else matchup["team_1_score"]
            winner = matchup.get("winner_user_id")
            result_label = (
                "Tie" if winner is None else
                "Win" if int(winner) == int(user_id) else "Loss"
            )
            my_col, opponent_col = st.columns(2, gap="large")
            my_col.metric(f"{team_name} · {result_label}", f"{my_score:.2f}")
            opponent_col.metric(opponent_name, f"{opponent_score:.2f}")
            st.caption(
                f"{matchup.get('split_name', 'Current split')} · points refreshed "
                f"{matchup.get('score_updated_at', 'recently')} UTC"
            )
            mine_json = matchup.get("team_1_breakdown_json" if is_team_1 else "team_2_breakdown_json") or "[]"
            opponent_json = matchup.get("team_2_breakdown_json" if is_team_1 else "team_1_breakdown_json") or "[]"
            try:
                mine = json.loads(mine_json)
                theirs = json.loads(opponent_json)
            except (TypeError, ValueError):
                mine, theirs = [], []
            if mine or theirs:
                my_details, opponent_details = st.columns(2, gap="large")
                with my_details:
                    st.markdown(f"**{team_name} roster points**")
                    st.dataframe(mine, hide_index=True)
                with opponent_details:
                    st.markdown(f"**{opponent_name} roster points**")
                    st.dataframe(theirs, hide_index=True)

logout_button()
