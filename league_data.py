import streamlit as st

from utils.lcs_api_wrapper import LoLEsportsAPI, LoLEsportsAPIError


def get_regional_leagues() -> list[dict]:
    """Return league and region choices from the configured LoL Esports API."""
    try:
        return LoLEsportsAPI().get_regional_leagues()
    except LoLEsportsAPIError as exc:
        raise ValueError(str(exc)) from exc


def fetch_league_player_pool(league: dict) -> list[dict]:
    """Load current-season organizations and players through the shared API wrapper."""
    try:
        return LoLEsportsAPI().get_players_for_league(league)
    except LoLEsportsAPIError as exc:
        raise ValueError(str(exc)) from exc


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_league_org_logos(league_id: str, league_name: str, region: str) -> dict[str, str]:
    """Fetch team logo URLs only, for backfilling older pools with missing logos."""
    try:
        rows = LoLEsportsAPI().get_players_for_league(
            {"id": league_id, "name": league_name, "region": region},
            include_player_images=False,
        )
    except LoLEsportsAPIError as exc:
        raise ValueError(str(exc)) from exc

    logos = {}
    for row in rows:
        if row.get("role") != "team" or not row.get("image_url"):
            continue
        image_url = str(row["image_url"]).strip()
        if image_url.lower().startswith("http://"):
            image_url = "https://" + image_url[len("http://"):]
        for value in (row.get("team_code"), row.get("player_name"), row.get("team_name")):
            key = str(value or "").strip().casefold()
            if key:
                logos[key] = image_url
    return logos
