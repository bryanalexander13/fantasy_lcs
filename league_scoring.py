"""Recompute fantasy matchup results from the current split snapshot."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from demo_data import _regular_season_data
from scoring_rules import player_game_points
from storage import (
    get_fantasy_matchup_schedule,
    get_fantasy_roster_assignments,
    get_matchup_champion_choice_rows,
    get_weekly_dragon_bonus,
    replace_fantasy_matchup_results,
)


SCORING_PATH = Path(__file__).resolve().with_name("scoring.json")
ROLE_LABELS = {"team": "Org", "top": "Top", "jg": "Jungle", "mid": "Mid", "adc": "Bot", "sup": "Support"}
DRAGON_ALIASES = {
    "air": "cloud", "cloud": "cloud", "chemtech": "chemtech", "hextech": "hextech",
    "fire": "infernal", "infernal": "infernal", "earth": "mountain", "mountain": "mountain",
    "water": "ocean", "ocean": "ocean", "elder": "elder",
}


def _canonical(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _week_number(name: object) -> int | None:
    match = re.match(r"^Week\s+(\d+)\b", str(name or "").strip(), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _dragon_counts(values) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in values or []:
        if isinstance(item, dict):
            item = item.get("type") or item.get("name") or item.get("dragonType") or ""
        raw = str(item or "").strip().casefold()
        if raw:
            counts[DRAGON_ALIASES.get(raw, raw)] += 1
    return counts


def _org_game_points(stats: dict, featured_dragon: str | None, scoring: dict) -> float:
    team_rules = scoring.get("team", {})
    dragons = int(stats.get("dragon_count", 0) or 0)
    points = sum(float(stats.get(key, 0) or 0) * float(value)
                 for key, value in team_rules.items()
                 if key in {"towers", "barons", "dragon_count"})
    if dragons >= 4:
        points += float(team_rules.get("dragon_souls", 0))
    dragon_types = _dragon_counts(stats.get("dragon_types"))
    points += dragon_types.get("elder", 0) * float(team_rules.get("elder_dragon_bonus", 0))
    if featured_dragon:
        points += dragon_types.get(_canonical(featured_dragon), 0) * float(
            team_rules.get("dragon_type_weekly_bonus", 0)
        )
    return points


def _slot_points(roster_pick: dict, week: dict, scoring: dict, featured_dragon: str | None,
                 role_picks: dict[str, set[str]], role_bans: dict[str, set[str]]) -> tuple[float, int]:
    slot = str(roster_pick["roster_slot"])
    player_id = str(roster_pick["player_id"])
    games = []
    if slot == "team":
        org_id = player_id.removeprefix("team:")
        for game in week.get("game_details", []):
            stats = (game.get("teams") or {}).get(org_id)
            if stats:
                games.append(_org_game_points(stats, featured_dragon, scoring))
    else:
        role = slot
        for game in week.get("game_details", []):
            stats = (game.get("players") or {}).get(player_id)
            if not stats:
                continue
            points = player_game_points(stats, scoring)
            champion = _canonical(stats.get("champion"))
            if champion and champion in role_picks.get(role, set()):
                points *= 1.2
            if champion and champion in role_bans.get(role, set()):
                points *= 0.8
            games.append(points)
    if not games:
        return 0.0, 0
    return sum(games) / len(games), len(games)


def refresh_fantasy_matchup_points(commissioner_id: int, season_snapshot: dict) -> dict:
    """Re-score scheduled matchups and persist the resulting scores and records."""
    schedule = get_fantasy_matchup_schedule()
    if not schedule:
        raise ValueError("A draft must finish and create the fantasy schedule before points can be refreshed.")
    roster_by_owner: dict[int, list[dict]] = defaultdict(list)
    for pick in get_fantasy_roster_assignments():
        roster_by_owner[int(pick["user_id"])].append(pick)
    if not roster_by_owner:
        raise ValueError("No drafted rosters were found to score.")

    raw_weeks = _regular_season_data(season_snapshot).get("weeks", [])
    weeks_by_number = {
        number: week for week in raw_weeks
        if (number := _week_number(week.get("name"))) is not None
    }
    if not weeks_by_number:
        raise ValueError("The current split snapshot contains no regular-season weeks.")

    with SCORING_PATH.open("r", encoding="utf-8") as handle:
        scoring = json.load(handle)
    choices_by_owner_week: dict[tuple[int, int], dict[str, dict[str, set[str]]]] = defaultdict(
        lambda: {"pick": defaultdict(set), "ban": defaultdict(set)}
    )
    for choice in get_matchup_champion_choice_rows():
        week_number = _week_number(choice.get("week"))
        if week_number is None:
            continue
        owner_id = int(choice["fantasy_team_id"])
        choices_by_owner_week[(week_number, owner_id)][choice["choice_type"]][choice["role"]].add(
            _canonical(choice["champion_name"])
        )

    results = []
    for matchup in schedule:
        week_number = int(matchup["week_number"])
        week = weeks_by_number.get(week_number)
        if not week:
            continue
        first_id = int(matchup["team_1_user_id"])
        second_id = int(matchup["team_2_user_id"]) if matchup.get("team_2_user_id") is not None else None
        featured = get_weekly_dragon_bonus(week_number)

        def calculate_team(owner_id: int, opponent_id: int | None):
            picks = choices_by_owner_week[(week_number, owner_id)]["pick"]
            opponent_bans = choices_by_owner_week[(week_number, opponent_id)]["ban"] if opponent_id is not None else {}
            breakdown = []
            total = 0.0
            for roster_pick in roster_by_owner.get(owner_id, []):
                points, games = _slot_points(
                    roster_pick, week, scoring, featured, picks, opponent_bans,
                )
                points = round(points, 2)
                total += points
                breakdown.append({
                    "slot": ROLE_LABELS.get(roster_pick["roster_slot"], roster_pick["roster_slot"]),
                    "player": roster_pick["player_name"],
                    "points": points,
                    "games": games,
                })
            return round(total, 2), breakdown

        first_score, first_breakdown = calculate_team(first_id, second_id)
        second_score = None
        second_breakdown = []
        winner_id = None
        if second_id is not None:
            second_score, second_breakdown = calculate_team(second_id, first_id)
            if first_score > second_score:
                winner_id = first_id
            elif second_score > first_score:
                winner_id = second_id
        results.append({
            "week_number": week_number,
            "matchup_number": int(matchup["matchup_number"]),
            "team_1_score": first_score,
            "team_2_score": second_score,
            "team_1_breakdown": first_breakdown,
            "team_2_breakdown": second_breakdown,
            "winner_user_id": winner_id,
        })

    if not results:
        raise ValueError("The saved current-split data does not overlap any scheduled fantasy weeks.")
    split_name = str(season_snapshot.get("season") or "Current split")
    replace_fantasy_matchup_results(commissioner_id, split_name, results)
    return {"split": split_name, "matchups": len(results), "weeks": len({row['week_number'] for row in results})}
