import csv
import io
from datetime import date, datetime, time

import streamlit as st
from demo_views import is_demo_mode

if is_demo_mode():
    st.title("Draft preview")
    st.info("The demo uses six pre-filled sample rosters. Start the app without `--demo` to use your real league draft.")
    st.stop()

from auth import logout_button, require_login
from demo_data import build_summer_split_draft_pool_stats
from draft import (
    DRAFT_PICK_SECONDS,
    SLOT_ROLE,
    auto_pick_if_expired,
    get_current_turn,
    get_order,
    get_picks,
    get_pool,
    get_upcoming_picks,
    get_settings,
    get_user_picks,
    make_pick,
    replace_player_pool,
    randomize_draft_order,
    set_draft_schedule,
    start_draft,
)
from league_data import fetch_league_player_pool, get_regional_leagues
from storage import SLOTS, get_fantasy_team_profile, get_users, is_commissioner
from utils.champion_assets import random_champion_pick_quote
from utils.lcs_api_wrapper import LoLEsportsAPIError

COMMUNITY_DRAGON_SOUNDS = (
    "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-champ-select/"
    "global/default/sounds"
)
DRAFT_MUSIC_URL = f"{COMMUNITY_DRAGON_SOUNDS}/music-cs-draft-ban-base-layer-01.ogg"
PICK_CONFIRMATION_URL = f"{COMMUNITY_DRAGON_SOUNDS}/sfx-cs-draft-right-pick-single.ogg"

user_id = require_login()
settings = get_settings()
users = get_users()
commissioner = is_commissioner(user_id)
my_team_profile = get_fantasy_team_profile(user_id) or {}

st.title("League draft")
st.caption(
    f"Snake format · draft one org and five role-specific players · {DRAFT_PICK_SECONDS} seconds per pick. "
    "Expired turns auto-pick by Spring 2026 fantasy points."
)
if settings.get("scheduled_at"):
    st.info(f"Draft scheduled for {settings['scheduled_at']} (local time).")

@st.fragment(run_every="1s")
def upcoming_picks_panel():
    upcoming_picks = get_upcoming_picks(4)
    if upcoming_picks:
        with st.container(border=True):
            st.markdown("### Teams up next")
            next_cols = st.columns(len(upcoming_picks), gap="medium")
            for column, pick in zip(next_cols, upcoming_picks):
                with column:
                    st.caption(f"Pick {pick['overall_pick']} · Round {pick['round']}")
                    if pick.get("team_image"):
                        st.image(pick["team_image"], width=68)
                    else:
                        st.markdown("## 🛡️")
                    st.markdown(f"**{pick.get('team_name') or pick['display_name'] + ' Team'}**")
                    st.caption(pick["display_name"])


if commissioner and settings["status"] == "setup":
    with st.expander("Commissioner controls", expanded=True):
        st.subheader("Draft date and time")
        try:
            scheduled_value = datetime.fromisoformat(settings["scheduled_at"]) if settings.get("scheduled_at") else None
        except ValueError:
            scheduled_value = None
        with st.form("draft_schedule_form"):
            scheduled_date = st.date_input("Draft date", value=scheduled_value.date() if scheduled_value else date.today())
            scheduled_time = st.time_input("Draft time (local)", value=scheduled_value.time().replace(tzinfo=None) if scheduled_value else time(19, 0))
            save_schedule = st.form_submit_button("Save draft date and time")
        if save_schedule:
            try:
                set_draft_schedule(user_id, datetime.combine(scheduled_date, scheduled_time).isoformat(timespec="minutes"))
                st.success("Draft date and time saved.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        st.subheader("Player pool")
        st.write("Choose a regional league and import its teams and player rosters. You can also upload a complete CSV pool.")
        if st.button("Load regional leagues", key="load_leagues"):
            try:
                st.session_state["regional_leagues"] = get_regional_leagues()
                if not st.session_state["regional_leagues"]:
                    st.warning("The LoL Esports API returned no leagues.")
            except ValueError as exc:
                st.error(str(exc))
        leagues = st.session_state.get("regional_leagues", [])
        if leagues:
            selected_league = st.selectbox(
                "Regional league",
                leagues,
                format_func=lambda league: f"{league.get('name', 'League')} — {league.get('region', 'Region')}",
                key="regional_league",
            )
            if st.button("Import all league teams and players", type="primary", key="api_import"):
                try:
                    player_rows = fetch_league_player_pool(selected_league)
                    replace_player_pool(
                        player_rows,
                        str(selected_league.get("name", "Regional league")),
                        str(selected_league.get("id", "")),
                        str(selected_league.get("region", "Unknown")),
                    )
                    st.success(f"Imported {len(player_rows)} draftable pool entries.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        with st.form("pool_csv_form"):
            csv_league = st.text_input("CSV league name", value=settings["league_name"])
            csv_region = st.text_input("CSV region", value=settings["region"])
            uploaded = st.file_uploader("Player pool CSV", type=["csv"])
            csv_submit = st.form_submit_button("Import CSV pool")
        if csv_submit:
            try:
                if not uploaded:
                    raise ValueError("Choose a CSV file first.")
                if not csv_league.strip() or not csv_region.strip():
                    raise ValueError("Enter both the regional league name and region.")
                rows = list(csv.DictReader(io.StringIO(uploaded.getvalue().decode("utf-8-sig"))))
                required = {"player_id", "player_name", "role", "team_name"}
                if not rows or not required.issubset(rows[0]):
                    raise ValueError("CSV needs player_id, player_name, role, and team_name columns.")
                allowed_roles = set(SLOT_ROLE.values()) | {"flex"}
                cleaned = []
                seen = set()
                for row in rows:
                    item = {key: str(row.get(key, "")).strip() for key in required}
                    if not item["player_id"] or not item["player_name"]:
                        raise ValueError("Every row needs a player ID and display name.")
                    item["role"] = item["role"].lower()
                    if item["role"] not in allowed_roles:
                        raise ValueError("Roles must be team, top, jg, mid, adc, sup, or flex.")
                    if item["player_id"] in seen:
                        raise ValueError(f"Duplicate player ID in CSV: {item['player_id']}")
                    seen.add(item["player_id"])
                    cleaned.append(item)
                replace_player_pool(cleaned, csv_league.strip(), "", csv_region.strip())
                st.success(f"Imported {len(cleaned)} draftable pool entries.")
                st.rerun()
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(str(exc))

        st.subheader("Draft order")
        if not users:
            st.info("Create accounts for all league members before randomizing the order.")
        elif settings.get("draft_order_locked"):
            st.success("The draft order has been randomized and is locked.")
        else:
            st.caption("This can be done once. Registration closes when the order is randomized.")
            if st.button("Randomize draft order", type="primary", key="randomize_order"):
                try:
                    randomize_draft_order(user_id)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if st.button("Start snake draft", type="primary", key="start_draft"):
            try:
                start_draft()
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

pool = get_pool()
order = get_order()

st.subheader("Draft order")
if order:
    for row in order:
        team_name = row.get("team_name") or f"{row['display_name']}'s Team"
        st.write(f"**{row['position']}. {team_name}**")
        st.caption(row["display_name"])
    if settings.get("draft_order_locked"):
        st.caption("This order is fixed for the draft.")
elif users:
    st.info("The commissioner has not randomized the draft order yet.")
else:
    st.info("The draft order will appear here after league members create accounts and the commissioner randomizes it.")

if settings["status"] == "in_progress":
    upcoming_picks_panel()

if settings["status"] == "setup":
    st.subheader("Draft room")
    if not pool:
        st.info("The commissioner needs to import a player pool before the draft can start.")
    if pool:
        st.caption(f"{settings['league_name']} · {settings['region']} · {len(pool)} pool entries")
        st.dataframe(
            [{"Player": p["player_name"], "Role": p["role"].upper(), "Team": p["team_name"] or "—"}
             for p in pool],
            hide_index=True,
            use_container_width=True,
        )
else:
    @st.fragment(run_every="1s")
    def draft_turn_clock():
        automatic_pick = auto_pick_if_expired()
        if automatic_pick and automatic_pick.get("error"):
            st.error(automatic_pick["error"])
        elif automatic_pick:
            slot_label = "Team org" if automatic_pick["slot"] == "team" else automatic_pick["slot"].upper()
            st.toast(
                f"Time expired: {automatic_pick['user']} auto-picked {automatic_pick['player']} "
                f"for {slot_label} ({automatic_pick['score']:.2f} Spring points)."
            )
            st.rerun()

        turn = get_current_turn()
        if not turn:
            if settings["status"] == "in_progress":
                st.rerun()
            return

        # Refresh the non-fragment draft board once when the pick advances.
        turn_key = int(turn["overall_pick"])
        if st.session_state.get("draft_board_turn_key") != turn_key:
            st.session_state["draft_board_turn_key"] = turn_key
            st.rerun()

        st.subheader(f"Pick {turn['overall_pick']} · Round {turn['round']}")
        st.warning(f"{turn['seconds_remaining']} seconds left to make this pick.")
        st.progress(turn["seconds_remaining"] / DRAFT_PICK_SECONDS)

    draft_turn_clock()

    def live_draft_board():
        live_settings = get_settings()
        turn = get_current_turn()
        current_pool = get_pool()
        try:
            previous_split = build_summer_split_draft_pool_stats()
        except (LoLEsportsAPIError, ValueError) as exc:
            previous_split = {"players": {}, "teams": {}}
            st.warning(f"Summer 2026 stats are unavailable: {exc}")
        previous_players = previous_split["players"]
        previous_teams = previous_split["teams"]
        picks = get_picks()
        user_picks = get_user_picks(user_id)
        drafted_slots = {pick["roster_slot"] for pick in user_picks}
        open_slots = [slot for slot in SLOTS if slot not in drafted_slots]
        is_my_turn = bool(turn and turn["user_id"] == user_id)
        if not turn:
            st.success("Draft complete. Rosters are now locked.")
            st.caption(f"{live_settings['league_name']} · {live_settings['region']}")
        else:
            st.subheader(f"Pick {turn['overall_pick']} · Round {turn['round']}")
            if is_my_turn:
                st.success("It’s your turn to pick.")
                if not open_slots:
                    st.info("Your roster is full.")
            else:
                st.info(f"On the clock: {turn['display_name']}")
        picks_col, available_col = st.columns(2, gap="large")
        available_pool = [player for player in current_pool if not player["drafted_by"]]
        selected_player = None

        def previous_fantasy_points(player):
            if player["role"] == "team":
                team_id = str(player["player_id"]).removeprefix("team:")
                stats = previous_teams.get(team_id)
            else:
                stats = previous_players.get(str(player["player_id"]))
            return stats.get("fantasy_points") if stats else None

        def render_selected_pick_stats():
            st.subheader("Selected pick's previous split stats")
            if selected_player:
                if selected_player["role"] == "team":
                    team_id = str(selected_player["player_id"]).removeprefix("team:")
                    previous = previous_teams.get(team_id)
                    stat_values = [
                        ("Org", selected_player["player_name"]),
                        ("Games", previous.get("games") if previous else None),
                        ("Kills", previous.get("totalKills") if previous else None),
                        ("Towers", previous.get("towers") if previous else None),
                        ("Barons", previous.get("barons") if previous else None),
                        ("Dragons", previous.get("dragon_count") if previous else None),
                        ("Dragon Souls", previous.get("dragon_souls") if previous else None),
                        ("Fantasy Points", previous.get("fantasy_points") if previous else None),
                    ]
                else:
                    previous = previous_players.get(str(selected_player["player_id"]))
                    stat_values = [
                        ("Player", selected_player["player_name"]),
                        ("Role", role_labels.get(selected_player["role"], selected_player["role"].upper())),
                        ("Games", previous.get("games") if previous else None),
                        ("Kills", previous.get("kills") if previous else None),
                        ("Deaths", previous.get("deaths") if previous else None),
                        ("Assists", previous.get("assists") if previous else None),
                        ("Creep Score", previous.get("creepScore") if previous else None),
                        ("Fantasy Points", previous.get("fantasy_points") if previous else None),
                    ]
                if previous:
                    st.caption("Summer 2026")
                    st.dataframe(
                        [{"Stat": label, "Value": f"{value:.2f}" if isinstance(value, float) else str(value)}
                         for label, value in stat_values if value is not None],
                        hide_index=True,
                        width="stretch",
                        height=min(360, 38 * len(stat_values) + 38),
                    )
                else:
                    st.info("No Summer 2026 stats were found for this selection.")
            else:
                st.caption("Select any cell in an available-picks row to preview its Summer 2026 stats.")

        with available_col:
            st.subheader("Available player pool")
            pool_filters = [
                ("All", "all", "All roles"), ("Org", "team", "Organization"),
                ("Top", "top", "Top"), ("JG", "jg", "Jungle"),
                ("Mid", "mid", "Mid"), ("ADC", "adc", "ADC"),
                ("SUP", "sup", "Support"),
            ]
            allowed_pool_filters = {role_filter for _, role_filter, _ in pool_filters}
            if st.session_state.get("draft_pool_filter") not in allowed_pool_filters:
                st.session_state["draft_pool_filter"] = "all"
            filter_cols = st.columns(len(pool_filters), gap="small")
            for column, (label, role_filter, tooltip) in zip(filter_cols, pool_filters):
                if column.button(
                    label,
                    help=tooltip,
                    key=f"draft_pool_filter_{role_filter}",
                    type="primary" if st.session_state["draft_pool_filter"] == role_filter else "secondary",
                    width="stretch",
                ):
                    st.session_state["draft_pool_filter"] = role_filter
                    st.rerun()
            search = st.text_input("Search player, organization, or team", key="draft_pool_search")
            role_labels = {
                "team": "Org", "top": "Top", "jg": "Jungle", "mid": "Mid",
                "adc": "ADC", "sup": "Support", "flex": "Flex",
            }
            role_filter = st.session_state["draft_pool_filter"]
            query = search.casefold().strip()
            visible_pool = [
                player for player in available_pool
                if (role_filter == "all" or player["role"] == role_filter)
                and (not query or query in " ".join((
                    player["player_name"], player["team_name"], player["team_code"], player["role"],
                )).casefold())
            ]
            st.caption(f"Showing {len(visible_pool)} of {len(available_pool)} available picks")
            if visible_pool:
                draft_action_placeholder = st.container()
                table_key = f"draft_pool_table_{role_filter}_{search.casefold()}"
                table_event = st.dataframe(
                    [{
                        "Logo": player.get("image_url", ""),
                        "Player / Org": player["player_name"],
                        "Role": role_labels.get(player["role"], player["role"].upper()),
                        "Team": player["team_name"] or "—",
                        "Total Fantasy Points": previous_fantasy_points(player),
                    } for player in visible_pool],
                    hide_index=True,
                    use_container_width=True,
                    height=540,
                    column_config={
                        "Logo": st.column_config.ImageColumn("Logo", width="small"),
                        "Player / Org": st.column_config.TextColumn("Player / Org", width="medium"),
                        "Role": st.column_config.TextColumn("Role", width="small"),
                        "Team": st.column_config.TextColumn("Team", width="medium"),
                        "Total Fantasy Points": st.column_config.NumberColumn(
                            "Total Fantasy Points", format="%.2f", width="small"
                        ),
                    },
                    on_select="rerun",
                    selection_mode="single-row",
                    key=table_key,
                )
                selected_rows = table_event.selection.rows
                if selected_rows:
                    selected_player = visible_pool[selected_rows[0]]
                render_selected_pick_stats()
                with draft_action_placeholder:
                    if is_my_turn and open_slots:
                        if selected_player:
                            if selected_player["role"] == "flex":
                                eligible_flex_slots = [slot for slot in open_slots if slot != "team"]
                                slot = st.selectbox(
                                    "Choose an open roster slot for this flex player",
                                    eligible_flex_slots,
                                    format_func=lambda value: value.upper(),
                                    key=f"draft_flex_slot_{turn['overall_pick']}",
                                ) if eligible_flex_slots else None
                            else:
                                slot = selected_player["role"]
                            if slot not in open_slots:
                                st.warning("You already filled that roster slot. Select a pick for an open slot.")
                            elif st.button(
                                f"Draft {selected_player['player_name']}",
                                type="primary",
                                key=f"draft_selected_{turn['overall_pick']}",
                            ):
                                try:
                                    make_pick(
                                        user_id, selected_player["player_id"], slot,
                                        expected_overall=turn["overall_pick"],
                                    )
                                    st.rerun()
                                except ValueError as exc:
                                    st.error(str(exc))
                        else:
                            st.caption("Select a row, then draft that player or organization.")
            else:
                st.info("No available picks match these filters.")
                render_selected_pick_stats()
        with picks_col:
            st.subheader("Draft picks")
            if picks:
                st.dataframe(
                    [{"Pick": p["overall_pick"], "Round": p["round"], "Manager": p["display_name"],
                      "Slot": "Team org" if p["roster_slot"] == "team" else p["roster_slot"].upper(),
                      "Player": p["player_name"], "League team": p["team_name"] or "—",
                      "Pick type": "Auto" if p["is_auto_pick"] else "Manual"}
                     for p in picks],
                    hide_index=True,
                    use_container_width=True,
                    height=360,
                )
            else:
                st.info("No picks have been made yet.")

            roster_profiles = {}
            roster_owners = {}
            for owner in users:
                owner_profile = get_fantasy_team_profile(owner["id"])
                if owner_profile:
                    roster_profiles[owner["id"]] = owner_profile
                    roster_owners[owner["id"]] = owner
            if user_id not in roster_profiles:
                roster_profiles[user_id] = my_team_profile
                roster_owners[user_id] = {"id": user_id, "display_name": "You"}
            roster_owner_ids = list(roster_profiles)
            roster_index = roster_owner_ids.index(user_id)
            selected_roster_owner = st.selectbox(
                "View team roster",
                roster_owner_ids,
                index=roster_index,
                format_func=lambda owner_id: (
                    f"{roster_profiles[owner_id].get('team_name') or 'Fantasy team'}"
                    f" · {roster_owners[owner_id]['display_name']}"
                ),
                key=f"draft_roster_owner_{user_id}",
            )
            selected_roster_profile = roster_profiles[selected_roster_owner]
            selected_roster_picks = get_user_picks(selected_roster_owner)
            team_name = selected_roster_profile.get("team_name") or "Fantasy team"
            st.subheader(f"{team_name} roster")
            roster_by_slot = {pick["roster_slot"]: pick for pick in selected_roster_picks}
            roster_labels = {"team": "Org", "top": "Top", "jg": "Jungle", "mid": "Mid", "adc": "ADC", "sup": "Support"}
            roster_cols = st.columns(2, gap="small")
            for index, slot in enumerate(SLOTS):
                with roster_cols[index % len(roster_cols)]:
                    with st.container(border=True):
                        st.caption(roster_labels[slot])
                        pick = roster_by_slot.get(slot)
                        if pick:
                            if pick.get("image_url"):
                                st.image(pick["image_url"], width=64)
                            st.markdown(f"**{pick['player_name']}**")
                            if slot != "team":
                                st.caption(pick.get("team_name") or "—")
                        else:
                            st.caption("Not drafted yet")

    live_draft_board()

sound_enabled = st.toggle(
    "Enable draft music and sounds",
    value=True,
    key="draft_audio_enabled",
)

@st.fragment(run_every="1s")
def draft_pick_sound_watcher():
    picks_so_far = get_picks()
    latest_pick = max(
        (int(pick["overall_pick"]) for pick in picks_so_far),
        default=0,
    )
    last_seen_pick = st.session_state.get("draft_last_pick_sound_seen")
    if last_seen_pick is None:
        st.session_state["draft_last_pick_sound_seen"] = latest_pick
        return
    if latest_pick < last_seen_pick:
        st.session_state["draft_last_pick_sound_seen"] = latest_pick
        return
    if latest_pick == last_seen_pick:
        return

    new_picks = [
        pick for pick in picks_so_far
        if int(pick["overall_pick"]) > int(last_seen_pick)
    ]
    st.session_state["draft_last_pick_sound_seen"] = latest_pick
    if st.session_state.get("draft_audio_enabled", True):
        for _pick in new_picks:
            st.audio(
                PICK_CONFIRMATION_URL,
                format="audio/ogg",
                autoplay=True,
                alt="Draft pick confirmation sound",
            )

draft_pick_sound_watcher()


if sound_enabled and settings["status"] == "in_progress":
    st.audio(
        DRAFT_MUSIC_URL,
        format="audio/ogg",
        loop=True,
        autoplay=True,
        alt="League of Legends champion select draft music",
    )

current_turn = get_current_turn()
if sound_enabled and current_turn and current_turn["user_id"] == user_id:
    turn_key = int(current_turn["overall_pick"])
    if st.session_state.get("draft_quote_turn_key") != turn_key:
        st.session_state["draft_quote_turn_key"] = turn_key
        st.session_state["draft_quote_audio"] = random_champion_pick_quote()
        st.session_state["draft_quote_played_turn"] = None
    quote = st.session_state.get("draft_quote_audio")
    if quote:
        autoplay = st.session_state.get("draft_quote_played_turn") != turn_key
        st.audio(
            quote["url"],
            format="audio/ogg",
            autoplay=autoplay,
            alt=f"{quote['name']} champion selection quote",
        )
        if autoplay:
            st.session_state["draft_quote_played_turn"] = turn_key
        st.caption(f"Random champion selection quote · {quote['name']} (CommunityDragon)")
    else:
        st.caption("Champion quote audio is unavailable right now.")

logout_button()
