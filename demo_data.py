"""API-sourced LCS Summer 2026 data and deterministic sample fantasy league."""

from __future__ import annotations

import json
import hashlib
import random
import re
from pathlib import Path

import streamlit as st

from utils.lcs_api_wrapper import LoLEsportsAPI
from scoring_rules import player_game_points


SAMPLE_PATH = Path(__file__).resolve().parent / "sample_data" / "lcs_summer_2026.json"
SPRING_SAMPLE_PATH = Path(__file__).resolve().parent / "sample_data" / "lcs_spring_2026.json"
ROLES = ("top", "jg", "mid", "adc", "sup")
ROLE_LABELS = {"team": "Team org", "top": "Top", "jg": "Jungle", "mid": "Mid", "adc": "Bot", "sup": "Support"}
DRAGON_TYPE_NAMES = ("Cloud", "Chemtech", "Hextech", "Infernal", "Mountain", "Ocean", "Elder")
DRAGON_TYPE_ALIASES = {
    "air": "Cloud", "cloud": "Cloud",
    "chemtech": "Chemtech",
    "hextech": "Hextech",
    "fire": "Infernal", "infernal": "Infernal",
    "earth": "Mountain", "mountain": "Mountain",
    "water": "Ocean", "ocean": "Ocean",
    "elder": "Elder",
}
FANTASY_TEAM_NAMES = [
    "Blue Buff Bandits", "Baron Brawlers", "Nexus Navigators",
    "River Scuttlers", "Final Draft", "Wardens of Top Lane",
]


@st.cache_data(show_spinner=False, max_entries=8)
def _read_snapshot_cached(path: str, fingerprint: str):
    """Parse a saved API snapshot once per content version."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_snapshot(path: Path):
    fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
    return _read_snapshot_cached(str(path), fingerprint)


def load_summer_2026_data(refresh=False, progress_callback=None):
    """Load the saved API pull, or fetch it through the shared wrapper."""
    if not refresh and SAMPLE_PATH.exists():
        return _read_snapshot(SAMPLE_PATH)

    snapshot = LoLEsportsAPI().get_lcs_summer_2026_stats(progress_callback=progress_callback)
    SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = SAMPLE_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    temporary_path.replace(SAMPLE_PATH)
    return snapshot


def load_spring_2026_data(refresh=False, progress_callback=None):
    """Load or fetch the LCS Spring 2026 regular-season API snapshot."""
    if not refresh and SPRING_SAMPLE_PATH.exists():
        return _read_snapshot(SPRING_SAMPLE_PATH)

    snapshot = LoLEsportsAPI().get_lcs_spring_2026_stats(progress_callback=progress_callback)
    SPRING_SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = SPRING_SAMPLE_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    temporary_path.replace(SPRING_SAMPLE_PATH)
    return snapshot


def _score(stats, weights):
    return sum(float(stats.get(key, 0)) * float(weight) for key, weight in weights.items())


def _dragon_type_counts(raw_types):
    counts = {}
    for value in raw_types or []:
        if isinstance(value, dict):
            value = value.get("type") or value.get("name") or value.get("dragonType") or ""
        raw_name = str(value or "").strip()
        if not raw_name:
            continue
        name = DRAGON_TYPE_ALIASES.get(raw_name.casefold(), raw_name.title())
        counts[name] = counts.get(name, 0) + 1
    return counts


def _org_game_points(objectives, dragon_type_counts, bonus_type, weights):
    points = _score(objectives, weights)
    for dragon_type, count in dragon_type_counts.items():
        if dragon_type == "Elder":
            points += count * float(weights.get("elder_dragon_bonus", 4))
        elif dragon_type == bonus_type:
            points += count * float(weights.get("dragon_type_weekly_bonus", 1))
    return round(points, 2)


@st.cache_data(show_spinner=False, max_entries=8)
def _regular_season_data(season_data):
    weeks = [
        week for week in season_data.get("weeks", [])
        if re.match(r"^Week\s+\d+\b", str(week.get("name", "")).strip(), re.IGNORECASE)
    ]
    if not weeks:
        raise ValueError("The API snapshot has no regular-season match weeks.")

    raw_player_stats = {}
    team_stats = {}
    player_fields = ("games", "kills", "deaths", "assists", "creepScore", "totalGoldEarned", "wardsPlaced", "wardsDestroyed")
    team_fields = ("games", "towers", "barons", "dragon_count", "dragon_souls", "totalKills")
    for week in weeks:
        for player_id, stats in week.get("players", {}).items():
            total = raw_player_stats.setdefault(player_id, {
                key: stats.get(key) for key in ("player_id", "player_name", "role", "team_id", "team_name")
            })
            for key in player_fields:
                total[key] = int(total.get(key, 0)) + int(stats.get(key, 0))
        week_souls = {}
        week_dragon_types = {}
        for game in week.get("game_details", []):
            for team_id, stats in (game.get("teams") or {}).items():
                if int(stats.get("dragon_count", 0)) >= 4:
                    week_souls[team_id] = week_souls.get(team_id, 0) + 1
                game_counts = _dragon_type_counts(stats.get("dragon_types"))
                team_counts = week_dragon_types.setdefault(team_id, {})
                for dragon_type, amount in game_counts.items():
                    team_counts[dragon_type] = team_counts.get(dragon_type, 0) + amount
        for team_id, stats in week.get("teams", {}).items():
            stats["dragon_souls"] = week_souls.get(team_id, 0)
            stats["dragon_type_counts"] = week_dragon_types.get(team_id, {})
            total = team_stats.setdefault(team_id, {
                key: stats.get(key) for key in ("team_id", "team_name")
            })
            if stats.get("image_url"):
                total["image_url"] = stats["image_url"]
            for key in team_fields:
                amount = week_souls.get(team_id, 0) if key == "dragon_souls" else stats.get(key, 0)
                total[key] = int(total.get(key, 0)) + int(amount)
            total_types = total.setdefault("dragon_type_counts", {})
            for dragon_type, amount in stats["dragon_type_counts"].items():
                total_types[dragon_type] = int(total_types.get(dragon_type, 0)) + int(amount)

    # The player with the most regular-season games at a team/role is the
    # first-string primary. Credit every same-team, same-role substitute game
    # to that primary slot for roster selection and fantasy scoring.
    primary_by_slot = {}
    for player in raw_player_stats.values():
        slot = (player.get("team_id"), player.get("role"))
        current_id = primary_by_slot.get(slot)
        current = raw_player_stats.get(current_id) if current_id else None
        if current is None or int(player.get("games", 0)) > int(current.get("games", 0)):
            primary_by_slot[slot] = player["player_id"]

    merged_player_stats = {}
    merged_weeks = []
    for week in weeks:
        week_players = {}
        for stats in week.get("players", {}).values():
            slot = (stats.get("team_id"), stats.get("role"))
            primary_id = primary_by_slot.get(slot)
            if not primary_id:
                continue
            primary = raw_player_stats[primary_id]
            weekly_total = week_players.setdefault(primary_id, {
                key: primary.get(key) for key in ("player_id", "player_name", "role", "team_id", "team_name")
            })
            season_total = merged_player_stats.setdefault(primary_id, {
                key: primary.get(key) for key in ("player_id", "player_name", "role", "team_id", "team_name")
            })
            for key in player_fields:
                amount = int(stats.get(key, 0))
                weekly_total[key] = int(weekly_total.get(key, 0)) + amount
                season_total[key] = int(season_total.get(key, 0)) + amount

        merged_game_details = []
        for game in week.get("game_details", []):
            game_players = {}
            for stats in (game.get("players") or {}).values():
                slot = (stats.get("team_id"), stats.get("role"))
                primary_id = primary_by_slot.get(slot)
                if not primary_id:
                    continue
                primary = raw_player_stats[primary_id]
                target = game_players.setdefault(primary_id, {
                    key: primary.get(key) for key in ("player_id", "player_name", "role", "team_id", "team_name")
                })
                target["champion"] = stats.get("champion") or target.get("champion", "")
                for key in player_fields:
                    target[key] = int(target.get(key, 0)) + int(stats.get(key, 0))
            merged_game_details.append({**game, "players": game_players})
        merged_weeks.append({**week, "players": week_players, "game_details": merged_game_details})

    return {
        **season_data, "weeks": merged_weeks,
        "players": list(merged_player_stats.values()), "teams": list(team_stats.values()),
    }


def _round_robin(team_ids, rounds):
    """Return one 3-matchup round per API block, repeating the circle as needed."""
    rotation = list(team_ids)
    schedule = []
    for _ in range(5):
        schedule.append([(rotation[i], rotation[-1 - i]) for i in range(3)])
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    return [schedule[index % len(schedule)] for index in range(rounds)]


def build_demo_data(season_data=None, seed=2026):
    """Create six unique rosters and matchup scores from actual tournament blocks."""
    season_data = season_data or load_summer_2026_data()
    scoring_path = Path(__file__).resolve().with_name("scoring.json")
    scoring = json.loads(scoring_path.read_text(encoding="utf-8"))
    return _build_demo_data_cached(season_data, seed, scoring)


@st.cache_data(show_spinner=False, max_entries=8)
def _build_demo_data_cached(season_data, seed, scoring):
    season_data = _regular_season_data(season_data)
    rng = random.Random(seed)
    players = [player for player in season_data.get("players", []) if player.get("role") in ROLES]
    by_role = {role: [player for player in players if player["role"] == role] for role in ROLES}
    too_small = [ROLE_LABELS[role] for role in ROLES if len(by_role[role]) < 6]
    if too_small:
        raise ValueError(f"The API returned fewer than six Summer 2026 players for: {', '.join(too_small)}.")

    orgs = season_data.get("teams", [])
    if len(orgs) < 6:
        raise ValueError("The API returned fewer than six LCS organizations for Summer 2026.")
    fantasy_teams = []
    for index, team_name in enumerate(FANTASY_TEAM_NAMES, start=1):
        fantasy_teams.append({
            "team_id": f"demo-{index}", "team_name": team_name,
            "owner": f"Demo Manager {index}", "roster": {},
        })
    for role in ROLES:
        for fantasy_team, player in zip(fantasy_teams, rng.sample(by_role[role], 6)):
            fantasy_team["roster"][role] = player
    for fantasy_team, org in zip(fantasy_teams, rng.sample(orgs, 6)):
        fantasy_team["org"] = org

    team_by_id = {team["team_id"]: team for team in fantasy_teams}
    rounds = _round_robin(list(team_by_id), len(season_data.get("weeks", [])))
    weeks = []
    records = {team_id: {"wins": 0, "losses": 0, "draws": 0} for team_id in team_by_id}
    for week_index, (source_week, pairings) in enumerate(zip(season_data.get("weeks", []), rounds), start=1):
        weekly_bonus_type = rng.choice(DRAGON_TYPE_NAMES[:-1])
        matchups = []
        source_players = source_week.get("players", {})
        source_teams = source_week.get("teams", {})
        for game_index, (left_id, right_id) in enumerate(pairings, start=1):
            box_scores = {}
            for fantasy_id in (left_id, right_id):
                fantasy_team = team_by_id[fantasy_id]
                player_lines = []
                total = 0.0
                for role in ROLES:
                    player = fantasy_team["roster"][role]
                    stats = source_players.get(player["player_id"], {})
                    team_id = str(player.get("team_id") or "")
                    series_games = sorted(
                        [game for game in source_week.get("game_details", []) if team_id in game.get("team_ids", [])],
                        key=lambda game: int(game.get("number") or 0),
                    )
                    game_lines = []
                    for game in series_games:
                        game_stats = (game.get("players") or {}).get(player["player_id"], {})
                        raw_game = {key: int(game_stats.get(key, 0)) for key in ("kills", "deaths", "assists", "creepScore")}
                        opponents = [
                            str((source_teams.get(opponent_id) or {}).get("team_name") or opponent_id)
                            for opponent_id in game.get("team_ids", [])
                            if opponent_id != team_id
                        ]
                        game_lines.append({
                            "game": int(game.get("number") or len(game_lines) + 1),
                            "opponent": ", ".join(opponents),
                            "champion": game_stats.get("champion", ""),
                            **raw_game,
                            "fantasy_points": player_game_points(raw_game, scoring),
                        })
                    raw = {key: int(stats.get(key, 0)) for key in ("kills", "deaths", "assists", "creepScore")}
                    games_played = len(series_games) or int(stats.get("games", 0))
                    total_points = (
                        sum(line["fantasy_points"] for line in game_lines)
                        if game_lines else _score(raw, scoring["player"])
                    )
                    points = total_points / games_played if games_played else 0.0
                    total += points
                    player_lines.append({
                        "role": role, "player_name": player["player_name"],
                        "league_team": player["team_name"], "games": int(stats.get("games", 0)),
                        "kills": raw["kills"], "deaths": raw["deaths"],
                        "assists": raw["assists"], "cs": raw["creepScore"],
                        "fantasy_points": round(points, 2), "game_stats": game_lines,
                        "season_average": player,
                    })

                org = fantasy_team["org"]
                org_stats = source_teams.get(org["team_id"], {})
                org_game_lines = []
                org_game_type_counts = {}
                for source_game in source_week.get("game_details", []):
                    game_org_stats = (source_game.get("teams") or {}).get(org["team_id"])
                    if not game_org_stats:
                        continue
                    dragon_count = int(game_org_stats.get("dragon_count", 0))
                    dragon_type_counts = _dragon_type_counts(game_org_stats.get("dragon_types"))
                    org_game_type_counts[int(source_game.get("number") or len(org_game_lines) + 1)] = dragon_type_counts
                    game_objectives = {
                        "towers": int(game_org_stats.get("towers", 0)),
                        "barons": int(game_org_stats.get("barons", 0)),
                        "dragon_count": dragon_count,
                        "dragon_souls": int(dragon_count >= 4),
                    }
                    opponent_id = next((
                        team_id for team_id in source_game.get("team_ids", [])
                        if team_id != org["team_id"]
                    ), "")
                    opponent = source_teams.get(opponent_id, {}).get("team_name", "—")
                    org_game_lines.append({
                        "Game": int(source_game.get("number") or len(org_game_lines) + 1),
                        "Opponent": opponent,
                        "Towers": game_objectives["towers"],
                        "Barons": game_objectives["barons"],
                        "Dragons": dragon_count,
                        "Dragon Soul": dragon_count >= 4,
                        "Fantasy points": _org_game_points(
                            game_objectives, dragon_type_counts, weekly_bonus_type, scoring["team"]
                        ),
                    })
                dragon_types = list(DRAGON_TYPE_NAMES)
                for game_counts in org_game_type_counts.values():
                    for dragon_type in game_counts:
                        if dragon_type not in dragon_types:
                            dragon_types.append(dragon_type)
                dragon_type_rows = []
                for dragon_type in dragon_types:
                    row = {"Dragon type": dragon_type}
                    total_dragons = 0
                    for game_number in (1, 2, 3):
                        count = org_game_type_counts.get(game_number, {}).get(dragon_type, 0)
                        row[f"Game {game_number}"] = count
                        total_dragons += count
                    row["Total"] = total_dragons
                    points_per_dragon = float(scoring["team"].get("dragon_count", 1))
                    if dragon_type == "Elder":
                        points_per_dragon += float(scoring["team"].get("elder_dragon_bonus", 4))
                    elif dragon_type == weekly_bonus_type:
                        points_per_dragon += float(scoring["team"].get("dragon_type_weekly_bonus", 1))
                    row["Points / dragon"] = round(points_per_dragon, 2)
                    row["Fantasy points"] = round(total_dragons * points_per_dragon, 2)
                    dragon_type_rows.append(row)
                objectives = {
                    key: int(org_stats.get(key, 0))
                    for key in ("towers", "barons", "dragon_count", "dragon_souls")
                }
                org_games = int(org_stats.get("games", 0))
                org_points = (
                    sum(line["Fantasy points"] for line in org_game_lines) / org_games
                    if org_games and org_game_lines
                    else _score(objectives, scoring["team"]) / org_games if org_games else 0.0
                )
                total += org_points
                box_scores[fantasy_id] = {
                    "score": round(total, 2), "players": player_lines,
                    "org": {"name": org["team_name"], "games": int(org_stats.get("games", 0)),
                            "image_url": org.get("image_url", ""),
                            **objectives, "game_stats": org_game_lines,
                            "dragon_type_counts": dict(org_stats.get("dragon_type_counts", {})),
                            "dragon_type_rows": dragon_type_rows,
                            "fantasy_points": round(org_points, 2)},
                }
            matchups.append({
                "matchup_id": f"w{week_index}-m{game_index}",
                "team_1_id": left_id, "team_2_id": right_id, "box_scores": box_scores,
            })
            left_score = box_scores[left_id]["score"]
            right_score = box_scores[right_id]["score"]
            if left_score > right_score:
                records[left_id]["wins"] += 1
                records[right_id]["losses"] += 1
            elif right_score > left_score:
                records[right_id]["wins"] += 1
                records[left_id]["losses"] += 1
            else:
                records[left_id]["draws"] += 1
                records[right_id]["draws"] += 1
        weeks.append({
            "week": week_index, "name": source_week["name"], "matchups": matchups,
            "match_start": source_week.get("start_time"),
            "dragon_bonus_type": weekly_bonus_type,
            # Cumulative fantasy record through the selected match block.
            "team_records": {team_id: dict(record) for team_id, record in records.items()},
        })

    return {
        "season": season_data.get("season", "LCS Summer 2026"),
        "source": "LoL Esports API via utils/lcs_api_wrapper.py",
        "tournament": season_data.get("tournament", {}),
        "pulled_at": season_data.get("pulled_at"),
        "games_loaded": season_data.get("games_loaded", 0),
        "games_expected": season_data.get("games_expected", 0),
        "games_skipped": season_data.get("games_skipped", []),
        "teams": fantasy_teams, "players": players, "weeks": weeks,
    }


def build_previous_season_player_stats(season_data=None):
    """Return all primary player totals and cumulative fantasy points."""
    return build_season_player_stats(season_data or load_summer_2026_data())


def build_spring_split_player_stats(season_data=None):
    """Return LCS Spring 2026 primary player totals and fantasy points."""
    return build_season_player_stats(season_data or load_spring_2026_data())


def build_spring_split_draft_scores():
    """Return cumulative Spring split fantasy points for players and orgs."""
    season_data = _regular_season_data(load_spring_2026_data())
    scoring = json.loads(Path(__file__).resolve().with_name("scoring.json").read_text(encoding="utf-8"))
    bonus_counts = _player_bonus_game_counts(season_data, scoring.get("player_bonus", {}))
    player_points = {
        str(player["player_id"]): round(
            _score(player, scoring["player"])
            + bonus_counts.get(str(player["player_id"]), 0) * float(scoring.get("player_bonus", {}).get("points", 0)),
            2,
        )
        for player in season_data.get("players", [])
    }
    team_points = {
        f"team:{team['team_id']}": _score(team, scoring["team"])
        for team in season_data.get("teams", [])
    }
    return {"players": player_points, "teams": team_points}


def build_summer_split_draft_pool_stats():
    """Return individual player and org stats with fantasy points from Summer 2026."""
    season_data = load_summer_2026_data()
    scoring = json.loads(Path(__file__).resolve().with_name("scoring.json").read_text(encoding="utf-8"))
    return _cached_summer_split_draft_pool_stats(season_data, scoring)


@st.cache_data(show_spinner=False, max_entries=2)
def _cached_summer_split_draft_pool_stats(season_data, scoring):
    player_data = _cached_player_score_totals(season_data, scoring)
    regular_season = _regular_season_data(season_data)
    players = {str(row["player_id"]): row for row in player_data["players"]}
    teams = {}
    for team in regular_season.get("teams", []):
        team_id = str(team["team_id"])
        teams[team_id] = {
            **team,
            "fantasy_points": round(_score(team, scoring["team"]), 2),
        }
    return {"players": players, "teams": teams}


def build_season_player_stats(season_data):
    scoring_path = Path(__file__).resolve().with_name("scoring.json")
    scoring = json.loads(scoring_path.read_text(encoding="utf-8"))
    return _cached_player_score_totals(season_data, scoring)


@st.cache_data(show_spinner=False, max_entries=8)
def _cached_player_score_totals(season_data, scoring):
    players = []
    bonus_counts = _player_bonus_game_counts(season_data, scoring.get("player_bonus", {}))
    for stats in season_data.get("players", []):
        if stats.get("role") not in ROLES:
            continue
        players.append({
            "player_id": stats["player_id"],
            "player_name": stats["player_name"],
            "role": stats["role"],
            "team_name": stats["team_name"],
            "games": int(stats.get("games", 0)),
            "kills": int(stats.get("kills", 0)),
            "deaths": int(stats.get("deaths", 0)),
            "assists": int(stats.get("assists", 0)),
            "creepScore": int(stats.get("creepScore", 0)),
            "totalGoldEarned": int(stats.get("totalGoldEarned", 0)),
            "wardsPlaced": int(stats.get("wardsPlaced", 0)),
            "wardsDestroyed": int(stats.get("wardsDestroyed", 0)),
            "fantasy_points": round(
                _score(stats, scoring["player"])
                + bonus_counts.get(str(stats["player_id"]), 0) * float(scoring.get("player_bonus", {}).get("points", 0)),
                2,
            ),
        })
    players.sort(key=lambda player: (-player["fantasy_points"], player["player_name"].casefold()))
    return {"season": season_data.get("season", "LCS Summer 2026"), "players": players}


def _player_bonus_game_counts(season_data, bonus_rules):
    """Count qualifying games by player ID from archived per-game records."""
    threshold = float(bonus_rules.get("kill_or_assist_threshold", 10))
    counts = {}
    for week in season_data.get("weeks", []):
        for game in week.get("game_details", []):
            for player_id, stats in (game.get("players") or {}).items():
                if (float(stats.get("kills", 0) or 0) >= threshold
                        or float(stats.get("assists", 0) or 0) >= threshold):
                    key = str(player_id)
                    counts[key] = counts.get(key, 0) + 1
    return counts
