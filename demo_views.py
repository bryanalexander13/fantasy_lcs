"""Streamlit views for the API-sourced Summer 2026 sample league."""

import copy
import os
import random
import sys
from datetime import datetime, timezone

import streamlit as st
from utils.player_images import render_player_image
from utils.team_images import normalize_team_image
from utils.champion_assets import champion_asset, champion_names
from storage import get_matchup_champion_choices, save_matchup_champion_choices

from demo_data import ROLE_LABELS, build_demo_data, load_summer_2026_data
from utils.fandom_images import find_player_images
from utils.lcs_api_wrapper import LoLEsportsAPIError


def is_demo_mode():
    return os.environ.get("FANTASY_DEMO", "").strip().lower() in {"1", "true", "yes"} or "--demo" in sys.argv


def _team_lookup(data):
    return {team["team_id"]: team for team in data["teams"]}


def _load_for_view(refresh=False):
    try:
        with st.spinner("Pulling LCS Summer 2026 game stats from the LoL Esports API…" if refresh else "Loading the LCS Summer 2026 API data…"):
            data = copy.deepcopy(build_demo_data(load_summer_2026_data(refresh=refresh)))
            for team in data.get("teams", []):
                override = st.session_state.get(f"demo_team_name_{team['team_id']}")
                if override:
                    team["team_name"] = override
            if not st.session_state.get("demo_team_images_initialized"):
                image_pool = [
                    team.get("org", {}).get("image_url", "")
                    for team in data.get("teams", [])
                    if team.get("org", {}).get("image_url")
                ]
                random.SystemRandom().shuffle(image_pool)
                for index, team in enumerate(data.get("teams", [])):
                    if image_pool:
                        st.session_state.setdefault(
                            f"demo_team_image_{team['team_id']}",
                            image_pool[index % len(image_pool)],
                        )
                st.session_state["demo_team_images_initialized"] = True
            return _apply_demo_champion_choices(data)
    except (LoLEsportsAPIError, OSError, ValueError) as exc:
        st.error(f"Couldn't load the Summer 2026 API data: {exc}")
        st.info("Check API access and the saved sample_data/lcs_summer_2026.json file, then refresh this page.")
        return None


def _champion_key(value):
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _apply_demo_champion_choices(data):
    records = {team["team_id"]: {"wins": 0, "losses": 0, "draws": 0} for team in data["teams"]}
    for week in data.get("weeks", []):
        week_choices = get_matchup_champion_choices(week["name"])
        for matchup in week.get("matchups", []):
            team_ids = (matchup["team_1_id"], matchup["team_2_id"])
            for team_id, opponent_id in (team_ids, tuple(reversed(team_ids))):
                own_choices = week_choices.get(team_id, {"picks": [], "bans": []})
                opponent_choices = week_choices.get(opponent_id, {"picks": [], "bans": []})
                box = matchup["box_scores"][team_id]
                for line in box.get("players", []):
                    role = line["role"]
                    for game in line.get("game_stats", []):
                        champion = _champion_key(game.get("champion"))
                        multiplier = 1.0
                        if any(
                            pick.get("role") == role and _champion_key(pick.get("champion")) == champion
                            for pick in own_choices.get("picks", [])
                        ):
                            multiplier *= 1.2
                        if any(
                            ban.get("role") == role and _champion_key(ban.get("champion")) == champion
                            for ban in opponent_choices.get("bans", [])
                        ):
                            multiplier *= 0.8
                        game["fantasy_multiplier"] = multiplier
                        game["fantasy_points"] = round(float(game.get("fantasy_points", 0)) * multiplier, 2)
                    game_lines = line.get("game_stats", [])
                    if game_lines:
                        line["fantasy_points"] = round(
                            sum(float(game.get("fantasy_points", 0)) for game in game_lines) / len(game_lines), 2
                        )
                box["score"] = round(
                    float(box.get("org", {}).get("fantasy_points", 0))
                    + sum(float(line.get("fantasy_points", 0)) for line in box.get("players", [])),
                    2,
                )

            left_score = matchup["box_scores"][team_ids[0]]["score"]
            right_score = matchup["box_scores"][team_ids[1]]["score"]
            if left_score > right_score:
                records[team_ids[0]]["wins"] += 1
                records[team_ids[1]]["losses"] += 1
            elif right_score > left_score:
                records[team_ids[1]]["wins"] += 1
                records[team_ids[0]]["losses"] += 1
            else:
                records[team_ids[0]]["draws"] += 1
                records[team_ids[1]]["draws"] += 1
        week["team_records"] = {team_id: dict(record) for team_id, record in records.items()}
    return data


def _week_match_start(week):
    raw_value = week.get("match_start")
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _demo_champion_options(data):
    champions = set(champion_names())
    for week in data.get("weeks", []):
        for matchup in week.get("matchups", []):
            for box in matchup.get("box_scores", {}).values():
                for line in box.get("players", []):
                    champions.update(
                        game.get("champion", "") for game in line.get("game_stats", [])
                        if game.get("champion")
                    )
    return sorted(champions, key=str.casefold)


def _render_demo_champion_controls(week, team_id, data):
    st.subheader("Champion picks and bans")
    st.caption(
        "Choose two champions to boost your selected roles and two to target the opponent's same roles. "
        "Picks apply a 1.2× multiplier; bans apply a 0.8× multiplier."
    )
    lock_time = _week_match_start(week)
    week_state = get_matchup_champion_choices(week["name"]).get(
        team_id, {"picks": [], "bans": []}
    )
    role_options = [("Top", "top"), ("Jungle", "jg"), ("Mid", "mid"), ("ADC", "adc"), ("Support", "sup")]
    role_labels = {value: label for label, value in role_options}
    if lock_time is None:
        st.info("Champion picks and bans are unavailable because this week's first match time is unknown.")
        return
    if datetime.now(timezone.utc) >= lock_time:
        st.info(f"Champion picks and bans locked before the first match at {lock_time.astimezone().strftime('%b %d, %I:%M %p %Z')}.")
        for kind, label in (("picks", "Picks"), ("bans", "Bans")):
            saved = week_state.get(kind, [])
            if saved:
                st.caption(f"{label}: " + " · ".join(
                    f"{role_labels.get(choice.get('role'), choice.get('role', '').upper())}: {choice.get('champion')}"
                    for choice in saved
                ))
        return

    options = _demo_champion_options(data)
    if not options:
        st.info("No champion names are available for selection yet.")
        return

    with st.form(f"champion_choices_{week['week']}_{team_id}"):
        form_values = {"picks": [], "bans": []}
        for kind, label in (("picks", "Picks"), ("bans", "Bans")):
            st.markdown(f"**{label}**")
            for index in range(2):
                saved = week_state.get(kind, [])
                choice = saved[index] if index < len(saved) else {}
                role_col, champion_col = st.columns([1, 2])
                saved_role = choice.get("role", "top")
                role = role_col.selectbox(
                    f"{label[:-1]} {index + 1} role",
                    [value for _, value in role_options],
                    index=[value for _, value in role_options].index(saved_role)
                    if saved_role in role_labels else 0,
                    format_func=lambda value: role_labels[value],
                    key=f"{kind}_{index}_role",
                )
                champion_options = list(options)
                saved_champion = choice.get("champion", "")
                if saved_champion and saved_champion not in champion_options:
                    champion_options.append(saved_champion)
                    champion_options.sort(key=str.casefold)
                champion = champion_col.selectbox(
                    f"{label[:-1]} {index + 1} champion",
                    champion_options,
                    index=champion_options.index(saved_champion) if saved_champion in champion_options else 0,
                    key=f"{kind}_{index}_champion",
                )
                form_values[kind].append({"role": role, "champion": champion})
        submitted = st.form_submit_button("Save picks and bans", type="primary")
    if submitted:
        for kind in ("picks", "bans"):
            selected_champions = [_champion_key(choice["champion"]) for choice in form_values[kind]]
            if len(set(selected_champions)) != 2:
                st.error(f"Choose two different champions for your {kind}.")
                return
        try:
            save_matchup_champion_choices(
                week["name"], team_id, form_values["picks"], form_values["bans"],
                str(week.get("match_start") or ""),
            )
            st.success("Champion picks and bans saved for this matchup week.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _render_role_champion_choices(week_name, team_id, opponent_id, role):
    week_choices = get_matchup_champion_choices(week_name)
    own_choices = week_choices.get(team_id, {"picks": [], "bans": []})
    opponent_choices = week_choices.get(opponent_id, {"picks": [], "bans": []})
    role_choices = []
    for label, selections in (
        ("Team pick", own_choices.get("picks", [])),
        ("Team ban", own_choices.get("bans", [])),
        ("Opponent pick", opponent_choices.get("picks", [])),
        ("Opponent ban", opponent_choices.get("bans", [])),
    ):
        role_choices.extend(
            (label, choice) for choice in selections if choice.get("role") == role
        )
    if not role_choices:
        return

    st.caption("Champion choices")
    choice_cols = st.columns(2, gap="small")
    for index, (label, choice) in enumerate(role_choices):
        with choice_cols[index % len(choice_cols)]:
            icon_col, name_col = st.columns([1, 3])
            asset = champion_asset(choice.get("champion"))
            if asset.get("icon_url"):
                icon_col.image(asset["icon_url"], width=34)
            name_col.caption(f"{label}: {asset.get('name') or choice.get('champion', 'Unknown')}")


def _player_rows(box):
    rows = []
    for line in box["players"]:
        season = line["season_average"]
        games = int(season.get("games", 0))
        deaths = int(season.get("deaths", 0))
        season_kda = round((season.get("kills", 0) + season.get("assists", 0)) / max(deaths, 1), 2)
        rows.append({
            "Slot": ROLE_LABELS[line["role"]], "Player": line["player_name"],
            "LCS team": line["league_team"], "Games this block": line["games"],
            "K": line["kills"], "D": line["deaths"], "A": line["assists"],
            "CS": line["cs"], "Fantasy points": line["fantasy_points"],
            "Summer games": games, "Summer KDA": season_kda,
            "Summer K/G": round(season.get("kills", 0) / max(games, 1), 2),
            "Summer D/G": round(season.get("deaths", 0) / max(games, 1), 2),
            "Summer A/G": round(season.get("assists", 0) / max(games, 1), 2),
        })
    return rows


def _format_record(record):
    if not record:
        return "0-0"
    result = f"{record['wins']}-{record['losses']}"
    if record.get("draws", 0):
        result += f"-{record['draws']}"
    return result


def _game_stat_text(game, field):
    value = game.get(field) if game else None
    return "—" if value is None else str(value)


def _fixed_player_game_rows(line):
    games_by_number = {
        int(game.get("game", index + 1)): game
        for index, game in enumerate(line.get("game_stats", []))
    }
    rows = []
    for game_number in (1, 2, 3):
        game = games_by_number.get(game_number)
        champion = champion_asset(game.get("champion")) if game else {"name": "", "icon_url": ""}
        rows.append({
            "Game": f"Game {game_number}",
            "Icon": champion["icon_url"],
            "Champion": champion["name"] or "—",
            "Opponent": game.get("opponent", "—") if game else "—",
            "Kills": _game_stat_text(game, "kills"),
            "Deaths": _game_stat_text(game, "deaths"),
            "Assists": _game_stat_text(game, "assists"),
            "CS": _game_stat_text(game, "creepScore"),
            "Multiplier": f"{float(game.get('fantasy_multiplier', 1.0)):.2f}×" if game else "—",
            "Fantasy points": _game_stat_text(game, "fantasy_points"),
        })
    return rows


def _fixed_org_game_rows(org):
    games_by_number = {int(game["Game"]): game for game in org.get("game_stats", [])}
    rows = []
    for game_number in (1, 2, 3):
        game = games_by_number.get(game_number)
        rows.append({
            "Game": f"Game {game_number}",
            "Opponent": game.get("Opponent", "—") if game else "—",
            "Towers": _game_stat_text(game, "Towers"),
            "Barons": _game_stat_text(game, "Barons"),
            "Dragons": _game_stat_text(game, "Dragons"),
            "Dragon Soul": ("Yes" if game.get("Dragon Soul") else "No") if game else "—",
            "Fantasy points": _game_stat_text(game, "Fantasy points"),
        })
    return rows


def _org_abbreviation(team_name):
    known_codes = {
        "flyquest": "FLY",
        "lyon": "LYON",
        "sentinels": "SEN",
        "dignitas": "DIG",
        "team liquid": "TL",
        "team liquid honda": "TL",
        "team liquid alienware": "TL",
        "cloud9 kia": "C9",
        "shopify rebellion": "SR",
        "disguised": "DSG",
    }
    name = str(team_name or "").strip()
    if name.casefold() in known_codes:
        return known_codes[name.casefold()]
    words = [word for word in name.split() if word.casefold() not in {"team", "gaming", "esports"}]
    return "".join(word[0] for word in words).upper()[:4]


def render_demo_matchups():
    st.title("Summer 2026 regular-season sample matchups")
    data = _load_for_view()
    if not data:
        return
    has_champions = any(
        player.get("champion")
        for week in data.get("weeks", [])
        for game in week.get("game_details", [])
        for player in (game.get("players") or {}).values()
    )
    if not has_champions:
        st.info("This saved API snapshot predates champion metadata. A commissioner can refresh the season data from the Commissioner page in the regular league app.")
    teams = _team_lookup(data)
    tournament = data.get("tournament", {})
    st.caption(
        f"Six sample teams · {data.get('games_loaded', 0)} of {data.get('games_expected', 0)} completed games loaded · "
        f"{len(data.get('games_skipped', []))} unavailable"
    )
    if data.get("pulled_at"):
        st.caption(f"API snapshot: {data['pulled_at']}")
    st.info(
        "Player and team statistics below are actual final-game totals from the LoL Esports API, "
        "grouped by its Summer 2026 regular-season match-week blocks. The six fantasy rosters and matchup pairings "
        "are sample data; their scores use the app's scoring.json rules. Each team's most-used player at a role "
        "is the primary, and same-role substitute stats are credited to that primary. Matchup box scores list "
        "each completed game in a series; a 2-0 series has no Game 3. Player and org fantasy points are averaged "
        "over the games played in that series."
    )
    if tournament.get("startDate") and tournament.get("endDate"):
        st.caption(f"API tournament: {tournament.get('slug')} · {tournament['startDate']} to {tournament['endDate']}")
    week_options = list(range(len(data["weeks"])))
    if not week_options:
        st.warning("The API snapshot contains no completed match-week blocks.")
        return
    week_index = st.selectbox(
        "Summer 2026 match block", week_options,
        format_func=lambda i: data["weeks"][i]["name"],
    )
    week = data["weeks"][week_index]
    st.subheader(f"{week['name']} · sample fantasy matchups")
    bonus_type = week.get("dragon_bonus_type", "")
    if bonus_type:
        st.caption(
            f"Weekly featured dragon: {bonus_type} dragons are worth 2 points each. "
            "Other dragons are worth 1 point each, Elder is worth 4, and Dragon Soul adds 4 at four or more dragons."
        )
    for matchup in week["matchups"]:
        left, right = teams[matchup["team_1_id"]], teams[matchup["team_2_id"]]
        left_box = matchup["box_scores"][left["team_id"]]
        right_box = matchup["box_scores"][right["team_id"]]
        left_record = _format_record(week.get("team_records", {}).get(left["team_id"]))
        right_record = _format_record(week.get("team_records", {}).get(right["team_id"]))
        cols = st.columns([5, 1, 5])
        with cols[0]:
            image_col, details_col = st.columns([1.3, 5])
            team_image = st.session_state.get(f"demo_team_image_{left['team_id']}")
            if team_image:
                image_col.image(team_image, width=96)
            details_col.markdown(f"### {left['team_name']}")
            details_col.caption(f"{left['owner']} · Record {left_record}")
            st.metric("Fantasy score", f"{left_box['score']:.2f}")
        with cols[1]:
            st.markdown("<div style='text-align:center;padding-top:1.5rem'>VS</div>", unsafe_allow_html=True)
        with cols[2]:
            image_col, details_col = st.columns([1.3, 5])
            team_image = st.session_state.get(f"demo_team_image_{right['team_id']}")
            if team_image:
                image_col.image(team_image, width=96)
            details_col.markdown(f"### {right['team_name']}")
            details_col.caption(f"{right['owner']} · Record {right_record}")
            st.metric("Fantasy score", f"{right_box['score']:.2f}")

    labels = [
        f"{teams[m['team_1_id']]['team_name']} vs {teams[m['team_2_id']]['team_name']}"
        for m in week["matchups"]
    ]
    st.subheader("View Match Up")
    chosen = st.selectbox(
        "Select a matchup", range(len(labels)), format_func=lambda i: labels[i], key="demo_boxscore"
    )
    matchup = week["matchups"][chosen]
    fantasy_ids = (matchup["team_1_id"], matchup["team_2_id"])
    matchup_player_context = {}
    for fantasy_id in fantasy_ids:
        for player in teams[fantasy_id]["roster"].values():
            matchup_player_context[player["player_name"]] = [
                player.get("team_name", ""), _org_abbreviation(player.get("team_name")),
            ]
    matchup_player_images = find_player_images(
        list(matchup_player_context), matchup_player_context,
    )
    box_cols = st.columns(2, gap="large")
    for box_col, fantasy_id in zip(box_cols, fantasy_ids):
        opponent_id = next(team_id for team_id in fantasy_ids if team_id != fantasy_id)
        team = teams[fantasy_id]
        box = matchup["box_scores"][fantasy_id]
        record = _format_record(week.get("team_records", {}).get(fantasy_id))
        with box_col:
            image_col, details_col = st.columns([1.3, 5])
            team_image = st.session_state.get(f"demo_team_image_{fantasy_id}")
            if team_image:
                image_col.image(team_image, width=96)
            details_col.subheader(team["team_name"])
            details_col.caption(f"{team['owner']} · Record through {week['name']}: {record}")
        org = box["org"]
        with box_col:
            with st.container(border=True):
                org_image_col, org_heading_col, org_points_col = st.columns([1.2, 3, 2])
                if org.get("image_url"):
                    org_image_col.image(org["image_url"], width=80)
                org_heading_col.markdown("### Org")
                org_heading_col.caption(org["name"])
                org_points_col.metric("Fantasy points / game", f"{org['fantasy_points']:.2f}")
                st.caption(
                    f"{org['games']} games · Towers {org['towers']} · Barons {org['barons']} · "
                    f"Dragons {org['dragon_count']} · Dragon Souls {org['dragon_souls']}"
                )
                st.dataframe(
                    _fixed_org_game_rows(org), hide_index=True, use_container_width=True, height=165,
                )
                with st.expander("Dragon types", expanded=False):
                    st.dataframe(org.get("dragon_type_rows", []), hide_index=True, use_container_width=True)

            players_by_role = {line["role"]: line for line in box["players"]}
            for role in ("top", "jg", "mid", "adc", "sup"):
                line = players_by_role.get(role, {})
                abbreviation = _org_abbreviation(line.get("league_team"))
                with st.container(border=True):
                    player_image_col, player_heading_col, player_points_col = st.columns([1.2, 3, 2])
                    with player_image_col:
                        render_player_image(
                            line.get("image_url") or matchup_player_images.get(line.get("player_name", "")),
                            size=80,
                        )
                    player_heading_col.markdown(f"### {ROLE_LABELS[role]}")
                    player_heading_col.caption(
                        f"{line.get('player_name', 'No player')} ({abbreviation})"
                        if line else "No player data"
                    )
                    game_count = len(line.get("game_stats", [])) if line else 0
                    player_points_col.metric(
                        "Fantasy points / game",
                        f"{line['fantasy_points']:.2f}" if game_count else "—",
                    )
                    _render_role_champion_choices(week["name"], fantasy_id, opponent_id, role)
                    compact_game_columns = {
                        "Game": st.column_config.TextColumn("Game", width="small"),
                        "Icon": st.column_config.ImageColumn("Icon", width="small"),
                        "Champion": st.column_config.TextColumn("Champion", width="small"),
                        "Opponent": st.column_config.TextColumn("Opponent", width="small"),
                        "Kills": st.column_config.TextColumn("Kills", width="small"),
                        "Deaths": st.column_config.TextColumn("Deaths", width="small"),
                        "Assists": st.column_config.TextColumn("Assists", width="small"),
                        "CS": st.column_config.TextColumn("CS", width="small"),
                        "Multiplier": st.column_config.TextColumn("Multiplier", width="small"),
                        "Fantasy points": st.column_config.TextColumn("Fantasy points", width="small"),
                    }
                    if line:
                        st.dataframe(
                            _fixed_player_game_rows(line), hide_index=True, use_container_width=True,
                            height=165,
                            column_config=compact_game_columns,
                        )
                    else:
                        st.dataframe(
                            _fixed_player_game_rows({}), hide_index=True, use_container_width=True,
                            height=165,
                            column_config=compact_game_columns,
                        )


def render_demo_my_matchup():
    data = _load_for_view()
    if not data or not data.get("teams"):
        return
    if not data.get("weeks"):
        st.title("My Matchup")
        st.info("There are no completed sample match weeks available yet.")
        return

    # Demo mode treats the first sample team as the authenticated user's team,
    # matching the My Team demo page.
    teams = _team_lookup(data)
    my_team = data["teams"][0]
    my_team_id = my_team["team_id"]
    week = data["weeks"][-1]
    matchup = next((
        item for item in week.get("matchups", [])
        if my_team_id in (item["team_1_id"], item["team_2_id"])
    ), None)

    st.title("My Matchup")
    st.caption(f"{week['name']} · latest available Summer 2026 match week")
    if not matchup:
        st.info(f"{my_team['team_name']} has no matchup in {week['name']}.")
        return

    opponent_id = (
        matchup["team_2_id"] if matchup["team_1_id"] == my_team_id else matchup["team_1_id"]
    )
    team_1 = teams[my_team_id]
    team_2 = teams[opponent_id]
    box_1 = matchup["box_scores"][team_1["team_id"]]
    box_2 = matchup["box_scores"][team_2["team_id"]]
    record_1 = _format_record(week.get("team_records", {}).get(team_1["team_id"]))
    record_2 = _format_record(week.get("team_records", {}).get(team_2["team_id"]))

    score_cols = st.columns([5, 1, 5])
    for column, team, box, record in (
        (score_cols[0], team_1, box_1, record_1),
        (score_cols[2], team_2, box_2, record_2),
    ):
        with column:
            image_col, details_col = st.columns([1.3, 5])
            team_image = st.session_state.get(f"demo_team_image_{team['team_id']}")
            if team_image:
                image_col.image(team_image, width=88)
            details_col.markdown(f"### {team['team_name']}")
            details_col.caption(f"{team['owner']} · Record {record}")
            st.metric("Fantasy score", f"{box['score']:.2f}")
    with score_cols[1]:
        st.markdown("<div style='text-align:center;padding-top:1.5rem'>VS</div>", unsafe_allow_html=True)

    bonus_type = week.get("dragon_bonus_type", "")
    if bonus_type:
        st.caption(
            f"Weekly featured dragon: {bonus_type} dragons are worth 2 points each. "
            "Other dragons are worth 1 point each, Elder is worth 4, and Dragon Soul adds 4 at four or more dragons."
        )

    _render_demo_champion_controls(week, my_team_id, data)

    st.subheader("View Match Up")
    matchup_player_context = {}
    for fantasy_id in (team_1["team_id"], team_2["team_id"]):
        for player in teams[fantasy_id]["roster"].values():
            matchup_player_context[player["player_name"]] = [
                player.get("team_name", ""), _org_abbreviation(player.get("team_name")),
            ]
    matchup_player_images = find_player_images(
        list(matchup_player_context), matchup_player_context,
    )
    box_cols = st.columns(2, gap="large")
    for box_col, fantasy_id in zip(box_cols, (team_1["team_id"], team_2["team_id"])):
        opponent_id = team_2["team_id"] if fantasy_id == team_1["team_id"] else team_1["team_id"]
        team = teams[fantasy_id]
        box = matchup["box_scores"][fantasy_id]
        record = _format_record(week.get("team_records", {}).get(fantasy_id))
        with box_col:
            image_col, details_col = st.columns([1.3, 5])
            team_image = st.session_state.get(f"demo_team_image_{fantasy_id}")
            if team_image:
                image_col.image(team_image, width=88)
            details_col.subheader(team["team_name"])
            details_col.caption(f"{team['owner']} · Record through {week['name']}: {record}")
        org = box["org"]
        with box_col:
            with st.container(border=True):
                org_image_col, org_heading_col, org_points_col = st.columns([1.2, 3, 2])
                if org.get("image_url"):
                    org_image_col.image(org["image_url"], width=72)
                org_heading_col.markdown("### Org")
                org_heading_col.caption(org["name"])
                org_points_col.metric("Fantasy points / game", f"{org['fantasy_points']:.2f}")
                st.caption(
                    f"{org['games']} games · Towers {org['towers']} · Barons {org['barons']} · "
                    f"Dragons {org['dragon_count']} · Dragon Souls {org['dragon_souls']}"
                )
                st.dataframe(
                    _fixed_org_game_rows(org), hide_index=True, use_container_width=True, height=165,
                )
                with st.expander("Dragon types", expanded=False):
                    st.dataframe(org.get("dragon_type_rows", []), hide_index=True, use_container_width=True)

            players_by_role = {line["role"]: line for line in box["players"]}
            for role in ("top", "jg", "mid", "adc", "sup"):
                line = players_by_role.get(role, {})
                abbreviation = _org_abbreviation(line.get("league_team"))
                with st.container(border=True):
                    player_image_col, player_heading_col, player_points_col = st.columns([1.2, 3, 2])
                    with player_image_col:
                        render_player_image(
                            line.get("image_url") or matchup_player_images.get(line.get("player_name", "")),
                            size=72,
                        )
                    player_heading_col.markdown(f"### {ROLE_LABELS[role]}")
                    player_heading_col.caption(
                        f"{line.get('player_name', 'No player')} ({abbreviation})"
                        if line else "No player data"
                    )
                    game_count = len(line.get("game_stats", [])) if line else 0
                    player_points_col.metric(
                        "Fantasy points / game",
                        f"{line['fantasy_points']:.2f}" if game_count else "—",
                    )
                    _render_role_champion_choices(week["name"], fantasy_id, opponent_id, role)
                    compact_game_columns = {
                        "Game": st.column_config.TextColumn("Game", width="small"),
                        "Icon": st.column_config.ImageColumn("Icon", width="small"),
                        "Champion": st.column_config.TextColumn("Champion", width="small"),
                        "Opponent": st.column_config.TextColumn("Opponent", width="small"),
                        "Kills": st.column_config.TextColumn("Kills", width="small"),
                        "Deaths": st.column_config.TextColumn("Deaths", width="small"),
                        "Assists": st.column_config.TextColumn("Assists", width="small"),
                        "CS": st.column_config.TextColumn("CS", width="small"),
                        "Multiplier": st.column_config.TextColumn("Multiplier", width="small"),
                        "Fantasy points": st.column_config.TextColumn("Fantasy points", width="small"),
                    }
                    st.dataframe(
                        _fixed_player_game_rows(line), hide_index=True, use_container_width=True,
                        height=165, column_config=compact_game_columns,
                    )


def render_demo_league():
    data = _load_for_view()
    if not data:
        return
    st.title("League")
    st.caption("Summer 2026 sample leaderboard, ranked by cumulative fantasy team record.")
    from scoring_rules import render_scoring_rules
    render_scoring_rules()
    if not data.get("weeks"):
        st.info("There are no completed fantasy matchups to rank yet.")
        return

    teams = _team_lookup(data)
    records = data["weeks"][-1].get("team_records", {})
    points = {team_id: 0.0 for team_id in teams}
    for week in data["weeks"]:
        for matchup in week["matchups"]:
            for team_id in (matchup["team_1_id"], matchup["team_2_id"]):
                points[team_id] += matchup["box_scores"][team_id]["score"]
    rows = []
    for team_id, team in teams.items():
        record = records.get(team_id, {"wins": 0, "losses": 0, "draws": 0})
        rows.append({
            "team_id": team_id, "team": team["team_name"], "owner": team["owner"],
            "wins": record["wins"], "losses": record["losses"],
            "points": round(points[team_id], 2),
        })
    rows.sort(key=lambda row: (-row["wins"], -row["points"], row["team"]))
    headers = st.columns([1, 5, 1, 1, 2])
    for column, label in zip(headers[1:], ("Team / owner", "Wins", "Losses", "Total points")):
        column.markdown(f"**{label}**")
    for row in rows:
        with st.container(border=True):
            image_col, team_col, wins_col, losses_col, points_col = st.columns([1, 5, 1, 1, 2])
            team_image = st.session_state.get(f"demo_team_image_{row['team_id']}")
            if team_image:
                image_col.image(team_image, width=64)
            team_col.page_link(
                "pages/1_Roster.py", label=row["team"],
                query_params={"team_id": row["team_id"]},
            )
            team_col.caption(row["owner"])
            wins_col.write(row["wins"])
            losses_col.write(row["losses"])
            points_col.write(f"{row['points']:.2f}")
    leader = rows[0]
    st.success(f"Current leader: {leader['team']} · {leader['wins']}-{leader['losses']}")


def render_demo_rosters(selected_team_id=None, data=None, title="Fantasy team rosters", show_selector=True, show_team_image=True):
    data = data or _load_for_view()
    if not data:
        return
    if title:
        st.title(title)
    if show_selector:
        st.caption("Choose a fantasy team to see its roster and regular-season stats for each Summer 2026 match week.")
    teams = _team_lookup(data)
    team_ids = list(teams)
    if show_selector:
        requested_team_id = str(st.query_params.get("team_id") or "")
        if requested_team_id in team_ids and st.session_state.get("roster_team_selector") != requested_team_id:
            st.session_state["roster_team_selector"] = requested_team_id
        selected_id = st.selectbox(
            "Fantasy team", team_ids,
            format_func=lambda team_id: f"{teams[team_id]['team_name']} · {teams[team_id]['owner']}",
            key="roster_team_selector",
        )
    else:
        selected_id = selected_team_id if selected_team_id in team_ids else team_ids[0]
    team = teams[selected_id]
    player_images = find_player_images([
        player["player_name"] for player in team["roster"].values()
    ], {
        player["player_name"]: [
            player.get("team_name", ""), _org_abbreviation(player.get("team_name"))
        ]
        for player in team["roster"].values()
    })
    image = st.session_state.get(f"demo_team_image_{selected_id}")
    if show_team_image and image:
        st.image(image, width=180)
    st.subheader(team["team_name"])
    st.caption(f"{team['owner']} · Org: {team['org']['team_name']}")
    latest_record = data["weeks"][-1].get("team_records", {}).get(selected_id, {}) if data["weeks"] else {}
    summary = st.columns([1, 2, 2])
    summary[0].metric("Season record", _format_record(latest_record))
    summary[1].metric("Player slots", len(team["roster"]))
    summary[2].metric("Team org", team["org"]["team_name"])

    weekly_player_stats = {role: [] for role in team["roster"]}
    org_rows = []
    for week in data["weeks"]:
        matchup = next((
            item for item in week["matchups"]
            if selected_id in (item["team_1_id"], item["team_2_id"])
        ), None)
        if not matchup:
            continue
        box = matchup["box_scores"][selected_id]
        for line in box["players"]:
            weekly_player_stats[line["role"]].append({
                "Week": week["name"],
                "Opponent": ", ".join(dict.fromkeys(
                    game.get("opponent", "") for game in line.get("game_stats", []) if game.get("opponent")
                )) or "—",
                "Games": line["games"],
                "Kills": line["kills"], "Deaths": line["deaths"],
                "Assists": line["assists"], "CS": line["cs"],
                "Avg fantasy points / game": line["fantasy_points"],
            })
        org = box["org"]
        dragon_type_summary = ", ".join(
            f"{dragon_type} × {count}"
            for dragon_type, count in sorted(
                org.get("dragon_type_counts", {}).items(), key=lambda item: item[0].casefold()
            )
        ) or "—"
        org_rows.append({
            "Week": week["name"],
            "Opponent": ", ".join(dict.fromkeys(
                game.get("Opponent", "") for game in org.get("game_stats", []) if game.get("Opponent")
            )) or "—",
            "Games": org["games"],
            "Towers": org["towers"], "Barons": org["barons"],
            "Dragons": org["dragon_count"], "Dragon Souls": org["dragon_souls"],
            "Dragon types": dragon_type_summary,
            "Bonus type": week.get("dragon_bonus_type", "—"),
            "Avg fantasy points / game": org["fantasy_points"],
        })
    st.subheader("Org stats by week")
    org_image_col, org_name_col = st.columns([1, 6])
    if team["org"].get("image_url"):
        org_image_col.image(team["org"]["image_url"], width=64)
    org_name_col.markdown(f"**{team['org']['team_name']}**")
    st.dataframe(org_rows, hide_index=True, use_container_width=True)

    st.subheader("Player stats by week")
    for role in team["roster"]:
        player = team["roster"][role]
        abbreviation = _org_abbreviation(player.get("team_name"))
        with st.container(border=True):
            image_col, player_col = st.columns([1, 6])
            with image_col:
                render_player_image(
                    player.get("image_url") or player_images.get(player["player_name"]),
                    size=76,
                )
            with player_col:
                st.markdown(f"### {ROLE_LABELS[role]} · {player['player_name']} ({abbreviation})")
            st.dataframe(
                weekly_player_stats[role], hide_index=True, use_container_width=True,
            )


def render_demo_my_team():
    data = _load_for_view()
    if not data or not data.get("teams"):
        return
    team = data["teams"][0]
    team_id = team["team_id"]
    image_key = f"demo_team_image_{team_id}"
    name_key = f"demo_team_name_{team_id}"
    name_width = min(max(len(team["team_name"]) * 0.26, 0.8), 12)
    title_col, edit_col, _ = st.columns([name_width, 0.5, 10])
    title_col.title(team["team_name"])
    with edit_col:
        with st.popover("✏️", help="Edit team name"):
            with st.form("demo_rename_team_form"):
                new_team_name = st.text_input("Team name", value=team["team_name"], max_chars=50)
                rename_submitted = st.form_submit_button("Save team name", type="primary")
            if rename_submitted:
                new_team_name = new_team_name.strip()
                if not new_team_name:
                    st.error("Enter a team name.")
                elif len(new_team_name) > 50:
                    st.error("Team names must be 50 characters or fewer.")
                else:
                    st.session_state[name_key] = new_team_name
                    st.success("Demo team name updated for this session.")
                    st.rerun()
    st.caption(f"Demo preview · {team['team_name']} · {team['owner']}")
    image_col, _ = st.columns([1, 3])
    uploaded = None
    save_image = False
    with image_col:
        preview_col, controls_col = st.columns([5, 1])
        remove_image = False
        if st.session_state.get(image_key):
            preview_col.image(st.session_state[image_key], width=180)
        else:
            preview_col.caption("No image")
        with controls_col:
            with st.popover("✏️", help="Edit team image", use_container_width=True):
                st.caption("Upload a PNG, JPG, or WebP image.")
                with st.form("demo_team_image_upload_form"):
                    uploaded = st.file_uploader(
                        "Choose a team image", type=["png", "jpg", "jpeg", "webp"], key="demo_team_image_upload"
                    )
                    save_image = st.form_submit_button("Save image", type="primary")
            if st.session_state.get(image_key):
                remove_image = st.button(
                    "🗑️", help="Remove team image", key="remove_demo_team_image", use_container_width=True
                )
    if save_image:
        if not uploaded:
            st.error("Choose an image first.")
        else:
            try:
                st.session_state[image_key] = normalize_team_image(uploaded)
                st.success("Team image saved for this demo session.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if remove_image:
        del st.session_state[image_key]
        st.rerun()
    st.divider()
    render_demo_rosters(selected_team_id=team_id, data=data, title=None, show_selector=False, show_team_image=False)
