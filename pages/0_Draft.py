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


upcoming_picks_panel()

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
    def live_draft_board():
        automatic_pick = auto_pick_if_expired()
        auto_pick_made = bool(automatic_pick and not automatic_pick.get("error"))
        if automatic_pick:
            if automatic_pick.get("error"):
                st.error(automatic_pick["error"])
            else:
                slot_label = "Team org" if automatic_pick["slot"] == "team" else automatic_pick["slot"].upper()
                st.toast(
                    f"Time expired: {automatic_pick['user']} auto-picked {automatic_pick['player']} "
                    f"for {slot_label} ({automatic_pick['score']:.2f} Spring points)."
                )
        live_settings = get_settings()
        turn = get_current_turn()
        current_pool = get_pool()
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
            st.warning(f"{turn['seconds_remaining']} seconds left to make this pick.")
            st.progress(turn["seconds_remaining"] / DRAFT_PICK_SECONDS)
            if auto_pick_made:
                st.info("The previous turn timed out. The next pick is now on the clock.")
            if is_my_turn:
                st.success("It’s your turn to pick.")
                if not open_slots:
                    st.info("Your roster is full.")
            else:
                st.info(f"On the clock: {turn['display_name']}")
        available_col, picks_col = st.columns(2, gap="large")
        available_pool = [player for player in current_pool if not player["drafted_by"]]
        with available_col:
            st.subheader("Available player pool")
            pool_filters = [
                ("All", "all"), ("Org", "team"), ("Top", "top"),
                ("Jungle", "jg"), ("Mid", "mid"), ("ADC", "adc"),
                ("Support", "sup"), ("Flex", "flex"),
            ]
            if "draft_pool_filter" not in st.session_state:
                st.session_state["draft_pool_filter"] = "all"
            for start in range(0, len(pool_filters), 4):
                filter_cols = st.columns(4, gap="small")
                for column, (label, role_filter) in zip(filter_cols, pool_filters[start:start + 4]):
                    if column.button(
                        label,
                        key=f"draft_pool_filter_{role_filter}",
                        type="primary" if st.session_state["draft_pool_filter"] == role_filter else "secondary",
                        use_container_width=True,
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
                table_key = f"draft_pool_table_{role_filter}_{search.casefold()}"
                table_event = st.dataframe(
                    [{
                        "Logo": player.get("image_url", ""),
                        "Player / Org": player["player_name"],
                        "Role": role_labels.get(player["role"], player["role"].upper()),
                        "Team": player["team_name"] or "—",
                    } for player in visible_pool],
                    hide_index=True,
                    use_container_width=True,
                    height=520,
                    column_config={
                        "Logo": st.column_config.ImageColumn("Logo", width="small"),
                        "Player / Org": st.column_config.TextColumn("Player / Org", width="medium"),
                        "Role": st.column_config.TextColumn("Role", width="small"),
                        "Team": st.column_config.TextColumn("Team", width="medium"),
                    },
                    on_select="rerun",
                    selection_mode="single-row",
                    key=table_key,
                )
                selected_rows = table_event.selection.rows
                if is_my_turn and open_slots:
                    if selected_rows:
                        selected_player = visible_pool[selected_rows[0]]
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
                    height=520,
                )
            else:
                st.info("No picks have been made yet.")

        team_name = my_team_profile.get("team_name") or "Your team"
        st.subheader(f"{team_name} roster")
        roster_by_slot = {pick["roster_slot"]: pick for pick in user_picks}
        roster_labels = {"team": "Org", "top": "Top", "jg": "Jungle", "mid": "Mid", "adc": "ADC", "sup": "Support"}
        roster_cols = st.columns(3, gap="medium")
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

logout_button()
