"""Shared rendering for the league's fantasy scoring rules."""

import json
from pathlib import Path

import streamlit as st


def load_scoring_rules() -> dict:
    path = Path(__file__).resolve().with_name("scoring.json")
    return _load_scoring_rules(path.stat().st_mtime_ns)


@st.cache_data
def _load_scoring_rules(modified_at: int) -> dict:
    path = Path(__file__).resolve().with_name("scoring.json")
    return json.loads(path.read_text(encoding="utf-8"))


def player_game_points(stats: dict, rules: dict) -> float:
    """Score one player's game, including at most one kill/assist threshold bonus."""
    player_rules = rules.get("player", {})
    points = sum(float(stats.get(key, 0) or 0) * float(weight) for key, weight in player_rules.items())
    bonus = rules.get("player_bonus", {})
    threshold = float(bonus.get("kill_or_assist_threshold", 10))
    if float(stats.get("kills", 0) or 0) >= threshold or float(stats.get("assists", 0) or 0) >= threshold:
        points += float(bonus.get("points", 2))
    return round(points, 2)


def render_scoring_rules() -> None:
    rules = load_scoring_rules()
    player = rules["player"]
    team = rules["team"]
    with st.expander("Scoring rules"):
        player_col, org_col = st.columns(2)
        with player_col:
            st.markdown("#### Player slots")
            st.markdown(
                f"- Kill: **{player['kills']:+g}**\n"
                f"- Death: **{player['deaths']:+g}**\n"
                f"- Assist: **{player['assists']:+g}**\n"
                f"- Creep score: **{player['creepScore']:+g} per CS**\n"
                f"- 10+ kills or 10+ assists: **+{rules['player_bonus']['points']:g} points once per game**"
            )
        with org_col:
            st.markdown("#### Org slot")
            st.markdown(
                f"- Tower: **{team['towers']:+g}**\n"
                f"- Baron: **{team['barons']:+g}**\n"
                f"- Dragon: **{team['dragon_count']:+g} each**\n"
                f"- Dragon Soul: **+{team['dragon_souls']:g}**\n"
                f"- Weekly featured dragon: **+{team['dragon_type_weekly_bonus']:g} bonus each** of the randomly selected type\n"
                f"- Elder Dragon: **+{team['elder_dragon_bonus']:g} bonus each**"
            )
        st.caption("Player and Org slot points are averaged over the games played in the series.")


def render_weekly_dragon_bonus(dragon_type: str | None) -> None:
    if dragon_type:
        st.info(f"Weekly featured dragon: **{dragon_type}** — featured dragons are worth double points.")
