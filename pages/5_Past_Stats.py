import streamlit as st
from demo_data import ROLE_LABELS, build_spring_split_player_stats, load_spring_2026_data
from demo_views import is_demo_mode
from utils.lcs_api_wrapper import LoLEsportsAPIError

if not is_demo_mode():
    from auth import logout_button, require_login
    from draft import get_settings

    require_login()
    settings = get_settings()
    league_name = str(settings.get("league_name") or "").casefold()
    if "lcs" not in league_name:
        st.title("Past Stats")
        st.info("Past split statistics are currently available for LCS Spring 2026 only.")
        logout_button()
        st.stop()

st.title("Past Stats · LCS Spring 2026")
st.caption(
    "Spring split regular-season totals only. Playoffs and Finals are excluded; "
    "players and substitutes are listed separately."
)
try:
    with st.spinner("Loading LCS Spring 2026 stats…"):
        spring_data = load_spring_2026_data()
        season = build_spring_split_player_stats(spring_data)
except (LoLEsportsAPIError, OSError, ValueError) as exc:
    st.error(f"Couldn't load LCS Spring 2026 stats: {exc}")
    st.info("Ask the commissioner to load or refresh the saved Spring 2026 data from the Commissioner page.")
    if not is_demo_mode():
        logout_button()
    st.stop()

players = season["players"]
st.caption(f"{len(players)} primary players in the saved Spring 2026 regular-season data")
search_col, role_col, org_col = st.columns([2, 1, 1])
search = search_col.text_input("Search players")
roles = sorted({player["role"] for player in players})
selected_role = role_col.selectbox(
    "Role", ["All roles", *roles],
    format_func=lambda role: "All roles" if role == "All roles" else ROLE_LABELS.get(role, role.upper()),
)
orgs = sorted({player["team_name"] for player in players})
selected_org = org_col.selectbox("LCS team", ["All teams", *orgs])
filtered = [player for player in players
            if (not search or search.casefold() in player["player_name"].casefold())
            and (selected_role == "All roles" or player["role"] == selected_role)
            and (selected_org == "All teams" or player["team_name"] == selected_org)]

st.dataframe([{
    "Player": player["player_name"],
    "Role": ROLE_LABELS[player["role"]],
    "LCS team": player["team_name"],
    "Games": player["games"],
    "Kills": player["kills"],
    "Deaths": player["deaths"],
    "Assists": player["assists"],
    "CS": player["creepScore"],
    "Gold": player["totalGoldEarned"],
    "Wards placed": player["wardsPlaced"],
    "Wards destroyed": player["wardsDestroyed"],
    "Total fantasy points": player["fantasy_points"],
} for player in filtered], hide_index=True, use_container_width=True, height=800)
st.caption(f"Showing {len(filtered)} of {len(players)} players")

if not is_demo_mode():
    logout_button()
