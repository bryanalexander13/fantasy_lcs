"""Persistent live-match refresh with a terminal completed state."""

from datetime import datetime, timedelta, timezone

from storage import (
    get_cached_live_matches,
    get_in_progress_match_ids,
    get_live_match_cache,
    save_live_match,
)


def _state(value) -> str:
    return str(value or "").replace("_", "").replace(" ", "").casefold()


def _extract_events(response: dict) -> list[dict]:
    return response.get("data", {}).get("schedule", {}).get("events", []) or []


def _is_league_event(event: dict, league_id: str, league_name: str) -> bool:
    league = event.get("league") or {}
    match = event.get("match") or {}
    if league_id:
        ids = {str(league.get(key, "")) for key in ("id", "leagueId")}
        match_league = match.get("league") or {}
        ids.update(str(match_league.get(key, "")) for key in ("id", "leagueId"))
        if league_id in ids:
            return True
    target = (league_name or "LCS").casefold()
    values = [str(league.get(key, "")) for key in ("slug", "name")]
    match_league = match.get("league") or {}
    values.extend(str(match_league.get(key, "")) for key in ("slug", "name"))
    accepted = {target}
    if target == "lcs":
        accepted.add("league of legends championship series")
    return any(value.casefold() in accepted for value in values if value)


def _match_is_completed(event: dict, match: dict) -> bool:
    terminal = {"completed", "finished", "final"}
    if _state(event.get("state")) in terminal or _state(match.get("state")) in terminal:
        return True
    strategy = match.get("strategy") or (event.get("match") or {}).get("strategy") or {}
    game_count = int(strategy.get("count") or 1)
    wins_needed = game_count // 2 + 1
    teams = match.get("teams") or (event.get("match") or {}).get("teams") or []
    return any(int((team.get("result") or {}).get("gameWins") or 0) >= wins_needed for team in teams)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _feed_time() -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    now = now.replace(second=(now.second // 10) * 10)
    return now.isoformat(timespec="seconds").replace("+00:00", "Z")


def _final_frame_times(event_start_time: str, game_number: int) -> list[str]:
    try:
        start = datetime.fromisoformat(str(event_start_time).replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return [_feed_time()]
    first_offset = 15 + 45 * max(0, game_number - 1)
    return [
        (start + timedelta(minutes=first_offset + 15 * step))
        .astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        for step in range(7)
    ]


def _refresh_game_feeds(api, match: dict, feeds: dict,
                        event_start_time: str = "") -> dict:
    result = dict(feeds or {})
    for game in match.get("games") or []:
        game_id = str(game.get("id") or "")
        if not game_id:
            continue
        game_state = _state(game.get("state"))
        active = game_state in {"inprogress", "live", "started"}
        completed_game = game_state == "completed"
        previous = result.get(game_id, {})
        if not active and not completed_game:
            continue
        if completed_game and previous.get("state") == game.get("state") and previous.get("last_frame_at"):
            continue
        try:
            game_number = int(game.get("number") or 1)
            times = _final_frame_times(event_start_time, game_number) if completed_game else [_feed_time()]
            window, frames, starting_time = {}, [], times[0]
            for candidate_time in times:
                try:
                    candidate = api.get_window(game_id, start_time=candidate_time)
                except Exception:
                    continue
                candidate_frames = candidate.get("frames") or []
                if candidate_frames:
                    window, frames, starting_time = candidate, candidate_frames, candidate_time
                    if candidate_frames[-1].get("gameState") == "finished":
                        break
            details_response = api.get_details(game_id, start_time=starting_time) if frames else {}
            detail_frames = details_response.get("frames") or []
            result[game_id] = {
                "game_id": game_id,
                "state": game.get("state", ""),
                "window": window if frames else previous.get("window", {}),
                "details": details_response if detail_frames else previous.get("details", {}),
                "last_frame_at": (frames[-1].get("rfc460Timestamp") if frames else previous.get("last_frame_at")),
            }
        except Exception:
            # Keep the last successful frame during brief feed/API outages.
            continue
    return result


def refresh_live_matches(api, league_id: str = "", league_name: str = "LCS") -> int:
    """Refresh live and previously tracked matches; return the number updated.

    Completed matches are checked before any match-specific API call. The live
    schedule request is still used to discover current events, but cached final
    matches are never sent to getEventDetails/window/details again.
    """
    active_states = {"inprogress", "live", "started", "completed", "finished", "final"}
    live_events = []
    for event in _extract_events(api.get_live()):
        match_id = str((event.get("match") or {}).get("id") or "")
        if (match_id and _is_league_event(event, league_id, league_name)
                and _state(event.get("state")) in active_states):
            live_events.append(event)
    events_by_id = {str(event["match"]["id"]): event for event in live_events}
    candidate_ids = set(events_by_id)
    candidate_ids.update(get_in_progress_match_ids(league_id))

    updated = 0
    for match_id in sorted(candidate_ids):
        cached = get_live_match_cache(match_id)
        if cached and cached["match_state"] == "completed":
            continue
        event = events_by_id.get(match_id, {})
        try:
            response = api.get_event_details(match_id)
        except Exception:
            continue
        detailed_event = response.get("data", {}).get("event", {}) or event
        match = detailed_event.get("match") or event.get("match") or {}
        is_completed = _match_is_completed(detailed_event, match)
        previous_payload = cached.get("payload", {}) if cached else {}
        feeds = _refresh_game_feeds(
            api, match, previous_payload.get("game_feeds", {}),
            event_start_time=str(detailed_event.get("startTime") or event.get("startTime") or ""),
        )
        payload = {
            "event": detailed_event,
            "game_feeds": feeds,
            "league": detailed_event.get("league") or event.get("league") or {},
        }
        if save_live_match(match_id, league_id, "completed" if is_completed else "in_progress",
                           payload, _timestamp()):
            updated += 1
    return updated


def get_live_matches() -> list[dict]:
    return get_cached_live_matches()
