import streamlit as st

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
        st.caption("Match results will appear here when fantasy scoring is connected to this schedule.")

logout_button()
