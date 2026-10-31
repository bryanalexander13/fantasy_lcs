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
