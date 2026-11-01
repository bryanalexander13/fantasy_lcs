import streamlit as st
import json
from pathlib import Path
from demo_views import is_demo_mode, render_demo_matchups

if is_demo_mode():
    render_demo_matchups()
    st.stop()

from auth import logout_button, require_login
from storage import get_fantasy_matchup_schedule, get_matchup_weeks, get_matchups, get_weekly_dragon_bonus
from draft import get_settings
from scoring_rules import player_game_points, render_weekly_dragon_bonus
from live_matches import get_live_matches, refresh_live_matches
from utils.lcs_api_wrapper import LoLEsportsAPI, LoLEsportsAPIError
from utils.champion_assets import champion_asset

require_login()
st.title("Matchups")
generated_schedule = get_fantasy_matchup_schedule()
if generated_schedule:
    st.caption("Randomized fantasy schedule generated when the draft completed. Every team meets all opponents before any rematch.")
    schedule_weeks = sorted({row["week_number"] for row in generated_schedule})
    selected_schedule_week = st.selectbox(
        "Fantasy schedule week", schedule_weeks,
        format_func=lambda value: f"Week {value}",
    )
    render_weekly_dragon_bonus(get_weekly_dragon_bonus(selected_schedule_week))
    st.dataframe([{
        "Matchup": row["matchup_number"],
        "Team 1": row["team_1_name"],
        "Owner 1": row["team_1_owner"],
        "Team 2": row["team_2_name"] or "Bye",
        "Owner 2": row["team_2_owner"] or "—",
    } for row in generated_schedule if row["week_number"] == selected_schedule_week],
        hide_index=True, use_container_width=True)
else:
    st.caption("No generated league schedule yet. The legacy sample schedule is shown until the draft completes.")
    weeks = get_matchup_weeks()
    if not weeks:
        st.info("No matchup schedule is configured yet. A randomized schedule will be created when the draft finishes.")
    else:
        week = st.selectbox("Week", weeks)
        render_weekly_dragon_bonus(get_weekly_dragon_bonus(week))
        matchups = get_matchups(week)
        if matchups:
            st.dataframe([{
                "Matchup": i + 1,
                "Team 1": m["team_1"] or "TBD",
                "Owner 1": m["owner_1"] or "—",
                "Score 1": "—",
                "Team 2": m["team_2"] or "TBD",
                "Owner 2": m["owner_2"] or "—",
                "Score 2": "—",
            } for i, m in enumerate(matchups)], hide_index=True, use_container_width=True)
        else:
            st.info("There are no matchups for this week.")
st.caption("The live panel below reads current match and game feeds from the LoL Esports API.")


def _series_text(event: dict) -> str:
    match = event.get("match") or {}
    return "  •  ".join(
        f"{team.get('name', 'Team')} {int((team.get('result') or {}).get('gameWins') or 0)}"
        for team in match.get("teams") or []
    ) or "Teams pending"


@st.cache_data
def _load_scoring_rules() -> dict:
    scoring_path = Path(__file__).resolve().parents[1] / "scoring.json"
    return json.loads(scoring_path.read_text(encoding="utf-8"))


def _render_player_side(team_name: str, team_metadata: dict, team_stats: dict,
                        details_frame: dict, scoring_rules: dict):
    st.markdown(f"#### {team_name}")
    participants = team_metadata.get("participantMetadata") or []
    detailed_stats = {
        int(player.get("participantId", 0)): player
        for player in details_frame.get("participants", [])
    }
    window_stats = {
        int(player.get("participantId", 0)): player
        for player in team_stats.get("participants", [])
    }
    if not participants:
        st.caption("Player details are not available yet.")
        return

    roles = {"top": "TOP", "jungle": "JNG", "jg": "JNG", "mid": "MID",
             "middle": "MID", "bot": "BOT", "adc": "BOT", "support": "SUP", "sup": "SUP"}
    for participant in participants:
        participant_id = int(participant.get("participantId", 0))
        stats = detailed_stats.get(participant_id) or window_stats.get(participant_id) or {}
        has_stats = bool(stats)
        kills = float(stats.get("kills") or 0)
        deaths = float(stats.get("deaths") or 0)
        assists = float(stats.get("assists") or 0)
        creep_score = float(stats.get("creepScore") or 0)
        points = player_game_points(stats, scoring_rules)
        role = roles.get(str(participant.get("role") or "").casefold(), "")
        player_name = participant.get("summonerName") or "Unknown player"
        champion_name = participant.get("championId") or participant.get("championName")
        stat_label = f"{role} · {player_name}" if role else player_name
        st.markdown(
            f"<div style='display:flex;align-items:center;justify-content:space-between;"
            f"padding:.55rem .7rem .1rem;border-top:1px solid rgba(128,128,128,.28)'>"
            f"<span style='font-size:1rem;font-weight:600'>{stat_label}</span>"
            f"<span style='font-size:.82rem;opacity:.7'>{'Live' if has_stats else 'Waiting for stats'}</span></div>",
            unsafe_allow_html=True,
        )
        if champion_name:
            champion = champion_asset(champion_name)
            icon_col, name_col = st.columns([1.5, 8])
            if champion["icon_url"]:
                icon_col.image(champion["icon_url"], width=48)
            name_col.caption(f"Champion: {champion['name']}")
        kda_col, cs_col, points_col = st.columns([1, 0.8, 1])
        kda_text = f"{int(kills)} / {int(deaths)} / {int(assists)}" if has_stats else "—"
        cs_text = f"{int(creep_score)}" if has_stats else "—"
        points_text = f"{points:.2f}" if has_stats else "—"
        kda_col.markdown(
            f"<div style='font-size:.78rem;opacity:.75'>K / D / A</div>"
            f"<div style='font-size:1.18rem;font-weight:600'>{kda_text}</div>",
            unsafe_allow_html=True,
        )
        cs_col.markdown(
            f"<div style='font-size:.78rem;opacity:.75'>CS</div>"
            f"<div style='font-size:1.18rem;font-weight:600'>{cs_text}</div>",
            unsafe_allow_html=True,
        )
        points_col.markdown(
            f"<div style='font-size:.78rem;opacity:.75'>Fantasy points</div>"
            f"<div style='font-size:1.65rem;line-height:1.2;font-weight:750'>{points_text}</div>",
            unsafe_allow_html=True,
        )


@st.fragment(run_every="30s")
def live_match_panel():
    settings = get_settings()
    league_id = str(settings.get("league_id") or "")
    league_name = str(settings.get("league_name") or "LCS")
    try:
        refresh_live_matches(LoLEsportsAPI(), league_id=league_id, league_name=league_name)
        st.caption("Live results refresh every 30 seconds while this page is open.")
    except LoLEsportsAPIError as exc:
        st.warning(f"Live match refresh is unavailable: {exc}")
    except Exception as exc:
        st.warning(f"Live match refresh failed: {exc}")

    matches = get_live_matches()
    if not matches:
        st.info(f"No {league_name} matches have been cached yet. In-progress matches will appear here when they are available.")
        return
    for cached in matches:
        payload = cached["payload"]
        event = payload.get("event") or {}
        match = event.get("match") or {}
        state_label = "Completed · final" if cached["match_state"] == "completed" else "In progress"
        title = f"{_series_text(event)}  |  {state_label}"
        with st.expander(title, expanded=cached["match_state"] == "in_progress"):
            st.caption(
                f"Match {cached['match_id']} · last updated {cached['updated_at']} UTC"
                + (f" · completed {cached['completed_at']} UTC" if cached.get("completed_at") else "")
            )
            games = match.get("games") or []
            feeds = payload.get("game_feeds") or {}
            scoring_rules = _load_scoring_rules()
            if not games:
                st.info("The API has not published game details for this match yet.")
            for game in games:
                game_id = str(game.get("id") or "")
                feed = feeds.get(game_id, {})
                window = feed.get("window") or {}
                frames = window.get("frames") or []
                latest = frames[-1] if frames else {}
                metadata = window.get("gameMetadata") or {}
                team_names = {str(team.get("id") or ""): team.get("name", "Team") for team in match.get("teams") or []}
                blue_metadata = metadata.get("blueTeamMetadata") or {}
                red_metadata = metadata.get("redTeamMetadata") or {}
                blue_id = str(blue_metadata.get("esportsTeamId") or "")
                red_id = str(red_metadata.get("esportsTeamId") or "")
                st.markdown(f"**Game {game.get('number', '?')} · {game.get('state', 'scheduled')}**")
                if feed.get("last_frame_at"):
                    st.caption(f"Latest live frame: {feed['last_frame_at']}")
                blue_col, red_col = st.columns(2, gap="large")
                details_frames = (feed.get("details") or {}).get("frames") or []
                latest_details = details_frames[-1] if details_frames else {}
                with blue_col:
                    _render_player_side(
                        team_names.get(blue_id, "Blue team"), blue_metadata,
                        latest.get("blueTeam") or {}, latest_details, scoring_rules,
                    )
                with red_col:
                    _render_player_side(
                        team_names.get(red_id, "Red team"), red_metadata,
                        latest.get("redTeam") or {}, latest_details, scoring_rules,
                    )


st.subheader("Live match updates")
live_match_panel()
logout_button()
