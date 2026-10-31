import streamlit as st
from demo_data import ROLE_LABELS, build_previous_season_player_stats
from demo_views import is_demo_mode

if not is_demo_mode():
    from auth import logout_button, require_login
    from draft import get_settings

    require_login()
    settings = get_settings()
    league_name = str(settings.get("league_name") or "").casefold()
    if "lcs" not in league_name:
        st.title("Players")
        st.info("Previous-season player stats are currently available for LCS Summer 2026 only.")
        logout_button()
        st.stop()

st.title("Previous season player stats")
try:
    season = build_previous_season_player_stats()
except (OSError, ValueError) as exc:
    st.error(f"Couldn't load previous-season stats: {exc}")
    st.info("Check the API settings or use the Matchups page to refresh the saved Summer 2026 data.")
    if not is_demo_mode():
        logout_button()
    st.stop()

players = season["players"]
st.caption(
    f"{season['season']} regular season · cumulative stats and fantasy points · "
    "players and substitutes are listed separately."
)
if not players:
    st.info("No player statistics are available for this season.")
    if not is_demo_mode():
        logout_button()
    st.stop()

if not is_demo_mode():
    from draft import exchange_rostered_player, get_pool, get_user_picks

    active_players = {
        str(player["player_id"]): player
        for player in players if int(player.get("games", 0)) > 0
    }
    all_pool_players = get_pool()
    own_picks = get_user_picks(st.session_state["user_id"])
    active_roster_players = [
        pick for pick in own_picks
        if pick.get("roster_slot") != "team" and str(pick["player_id"]) in active_players
    ]
    unowned_active_pool = [
        player for player in all_pool_players
        if player.get("role") != "team"
        and player.get("drafted_by") is None
        and str(player["player_id"]) in active_players
    ]

    with st.expander("Exchange a player", expanded=False):
        if settings.get("status") != "complete":
            st.info("Player exchanges open after the draft is complete.")
        elif not active_roster_players:
            st.info("You have no rostered players who played in this split to exchange.")
        elif not unowned_active_pool:
            st.info("There are no undrafted active players available for exchange.")
        else:
            active_roster_by_id = {str(pick["player_id"]): pick for pick in active_roster_players}
            outgoing_id = st.selectbox(
                "Exchange a player on your roster",
                list(active_roster_by_id),
                format_func=lambda player_id: (
                    f"{active_roster_by_id[player_id]['player_name']} · "
                    f"{ROLE_LABELS.get(active_roster_by_id[player_id]['roster_slot'], active_roster_by_id[player_id]['roster_slot'])}"
                ),
                key="player_exchange_outgoing",
            )
            outgoing_pick = active_roster_by_id[outgoing_id]
            slot_role = outgoing_pick["roster_slot"]
            eligible_incoming = [
                player for player in unowned_active_pool
                if player["role"] in {slot_role, "flex"}
            ]
            if not eligible_incoming:
                st.info("There are no undrafted active players available for that role.")
            else:
                incoming_by_id = {str(player["player_id"]): player for player in eligible_incoming}
                with st.form("player_exchange_form"):
                    incoming_id = st.selectbox(
                        "Exchange for an undrafted active player",
                        list(incoming_by_id),
                        format_func=lambda player_id: (
                            f"{incoming_by_id[player_id]['player_name']} · "
                            f"{incoming_by_id[player_id]['team_name']}"
                        ),
                    )
                    submit_exchange = st.form_submit_button("Exchange players", type="primary")
                st.caption(
                    f"Both players must have played in {season['season']}. "
                    "The exchange stays within the same roster role; the outgoing player becomes available."
                )
                if submit_exchange:
                    try:
                        exchange_rostered_player(
                            int(st.session_state["user_id"]), outgoing_id, incoming_id,
                            active_players.keys(), season["season"],
                        )
                        st.success("Player exchange completed.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

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

st.caption(f"Showing {len(filtered)} of {len(players)} players")
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

if not is_demo_mode():
    logout_button()
