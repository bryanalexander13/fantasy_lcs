import sqlite3
import math
import random
from datetime import datetime, timezone
from functools import lru_cache

from storage import SLOTS, connect, is_commissioner
from matchup_schedule import create_random_schedule

SLOT_ROLE = {"team": "team", "top": "top", "jg": "jg", "mid": "mid", "adc": "adc", "sup": "sup"}
DRAFT_PICK_SECONDS = 45


def get_settings() -> dict:
    with connect() as db:
        return dict(db.execute("SELECT * FROM draft_settings WHERE id = 1").fetchone())


def set_draft_schedule(user_id: int, scheduled_at: str | None) -> None:
    if not is_commissioner(user_id):
        raise ValueError("Only the commissioner can set the draft date and time.")
    with connect() as db:
        settings = db.execute("SELECT status FROM draft_settings WHERE id = 1").fetchone()
        if not settings or settings["status"] != "setup":
            raise ValueError("The draft date and time are locked after the draft starts.")
        db.execute("UPDATE draft_settings SET scheduled_at = ? WHERE id = 1", (scheduled_at or None,))


def propose_trade(proposer_user_id: int, recipient_user_id: int,
                  offered_player_id: str, requested_player_id: str) -> int:
    if proposer_user_id == recipient_user_id:
        raise ValueError("You cannot propose a trade with your own team.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        settings = db.execute("SELECT status FROM draft_settings WHERE id = 1").fetchone()
        if not settings or settings["status"] != "complete":
            raise ValueError("Trades open after the draft is complete.")
        offer = db.execute(
            "SELECT roster_slot FROM draft_picks WHERE user_id = ? AND player_id = ?",
            (proposer_user_id, str(offered_player_id)),
        ).fetchone()
        request = db.execute(
            "SELECT roster_slot FROM draft_picks WHERE user_id = ? AND player_id = ?",
            (recipient_user_id, str(requested_player_id)),
        ).fetchone()
        if not offer or not request:
            raise ValueError("Each player must currently belong to the selected team owner.")
        if offer["roster_slot"] != request["roster_slot"]:
            raise ValueError("For now, a trade must exchange players from the same roster slot.")
        cur = db.execute("""
            INSERT INTO trade_proposals(
                proposer_user_id, recipient_user_id, offered_player_id, requested_player_id
            ) VALUES (?, ?, ?, ?)
        """, (proposer_user_id, recipient_user_id, str(offered_player_id), str(requested_player_id)))
        return int(cur.lastrowid)


def exchange_rostered_player(user_id: int, outgoing_player_id: str,
                             incoming_player_id: str, active_player_ids,
                             split_name: str) -> None:
    """Swap an active roster player for an undrafted active player in the same slot."""
    outgoing_player_id = str(outgoing_player_id)
    incoming_player_id = str(incoming_player_id)
    active_ids = {str(player_id) for player_id in active_player_ids}
    if outgoing_player_id == incoming_player_id:
        raise ValueError("Choose two different players.")
    if outgoing_player_id not in active_ids or incoming_player_id not in active_ids:
        raise ValueError("Both players must have played in the selected split.")

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        settings = db.execute("SELECT status FROM draft_settings WHERE id = 1").fetchone()
        if not settings or settings["status"] != "complete":
            raise ValueError("Player exchanges open after the draft is complete.")
        outgoing = db.execute("""
            SELECT k.overall_pick, k.roster_slot, p.role
            FROM draft_picks k JOIN player_pool p ON p.player_id = k.player_id
            WHERE k.user_id = ? AND k.player_id = ?
        """, (int(user_id), outgoing_player_id)).fetchone()
        if not outgoing:
            raise ValueError("The outgoing player is not on your roster.")
        if outgoing["roster_slot"] == "team":
            raise ValueError("The Org slot cannot be exchanged on the Players page.")
        incoming = db.execute("""
            SELECT p.role FROM player_pool p
            LEFT JOIN draft_picks k ON k.player_id = p.player_id
            WHERE p.player_id = ? AND k.player_id IS NULL
        """, (incoming_player_id,)).fetchone()
        if not incoming:
            raise ValueError("The incoming player has already been drafted or is not in this league's player pool.")
        expected_role = SLOT_ROLE[outgoing["roster_slot"]]
        if outgoing["role"] not in {expected_role, "flex"} or incoming["role"] not in {expected_role, "flex"}:
            raise ValueError("Players can only be exchanged within the same roster role.")

        db.execute("UPDATE draft_picks SET player_id = ? WHERE overall_pick = ?",
                   (incoming_player_id, int(outgoing["overall_pick"])))
        db.execute("""
            INSERT INTO roster_exchanges(
                user_id, roster_slot, outgoing_player_id, incoming_player_id, split_name
            ) VALUES (?, ?, ?, ?, ?)
        """, (int(user_id), outgoing["roster_slot"], outgoing_player_id,
              incoming_player_id, str(split_name or "")))


def get_trade_proposals(user_id: int | None = None, pending_only: bool = False) -> list[dict]:
    clauses, params = [], []
    if user_id is not None:
        clauses.append("(t.proposer_user_id = ? OR t.recipient_user_id = ?)")
        params.extend([int(user_id), int(user_id)])
    if pending_only:
        clauses.append("t.status IN ('proposed', 'accepted')")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as db:
        return [dict(row) for row in db.execute(f"""
            SELECT t.id, t.proposer_user_id, t.recipient_user_id,
                   proposer.display_name AS proposer_name,
                   recipient.display_name AS recipient_name,
                   offered.player_id AS offered_player_id,
                   offered.player_name AS offered_player_name,
                   offered.role AS offered_role, offered.team_name AS offered_team,
                   requested.player_id AS requested_player_id,
                   requested.player_name AS requested_player_name,
                   requested.role AS requested_role, requested.team_name AS requested_team,
                   t.status, t.created_at, t.resolved_at
            FROM trade_proposals t
            JOIN users proposer ON proposer.id = t.proposer_user_id
            JOIN users recipient ON recipient.id = t.recipient_user_id
            JOIN player_pool offered ON offered.player_id = t.offered_player_id
            JOIN player_pool requested ON requested.player_id = t.requested_player_id
            {where}
            ORDER BY CASE WHEN t.status IN ('proposed', 'accepted') THEN 0 ELSE 1 END,
                     t.created_at DESC, t.id DESC
        """, params)]


def respond_to_trade(trade_id: int, recipient_user_id: int, accept: bool) -> None:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        trade = db.execute("SELECT * FROM trade_proposals WHERE id = ?", (trade_id,)).fetchone()
        if not trade or trade["recipient_user_id"] != recipient_user_id:
            raise ValueError("This trade was not sent to your team.")
        if trade["status"] != "proposed":
            raise ValueError("This proposal is no longer awaiting your response.")
        db.execute("""UPDATE trade_proposals SET status = ?,
            resolved_at = CASE WHEN ? THEN resolved_at ELSE CURRENT_TIMESTAMP END
            WHERE id = ?""", ("accepted" if accept else "rejected", int(accept), trade_id))


def cancel_trade(trade_id: int, proposer_user_id: int) -> None:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        trade = db.execute("SELECT * FROM trade_proposals WHERE id = ?", (trade_id,)).fetchone()
        if not trade or trade["proposer_user_id"] != proposer_user_id:
            raise ValueError("You can only cancel your own trade proposal.")
        if trade["status"] not in {"proposed", "accepted"}:
            raise ValueError("This proposal can no longer be cancelled.")
        db.execute("UPDATE trade_proposals SET status = 'cancelled', resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                   (trade_id,))


def resolve_trade(trade_id: int, commissioner_user_id: int, approve: bool) -> None:
    if not is_commissioner(commissioner_user_id):
        raise ValueError("Only the commissioner can review trades.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        trade = db.execute("SELECT * FROM trade_proposals WHERE id = ?", (trade_id,)).fetchone()
        if not trade or trade["status"] not in {"proposed", "accepted"}:
            raise ValueError("This trade is no longer awaiting commissioner review.")
        if approve:
            if trade["status"] != "accepted":
                raise ValueError("The recipient must accept the proposal before it can be approved.")
            settings = db.execute("SELECT status FROM draft_settings WHERE id = 1").fetchone()
            if not settings or settings["status"] != "complete":
                raise ValueError("Trades can only be completed after the draft finishes.")
            picks = db.execute("""
                SELECT * FROM draft_picks
                WHERE (user_id = ? AND player_id = ?) OR (user_id = ? AND player_id = ?)
                ORDER BY user_id
            """, (trade["proposer_user_id"], trade["offered_player_id"],
                  trade["recipient_user_id"], trade["requested_player_id"])).fetchall()
            if len(picks) != 2:
                raise ValueError("The players are no longer on the teams in this offer.")
            first, second = [dict(row) for row in picks]
            if first["roster_slot"] != second["roster_slot"]:
                raise ValueError("The players no longer match the same roster slot.")
            swapped = [
                (first["overall_pick"], first["round"], first["pick_in_round"], first["user_id"],
                 second["player_id"], first["roster_slot"], first["picked_at"], first["is_auto_pick"]),
                (second["overall_pick"], second["round"], second["pick_in_round"], second["user_id"],
                 first["player_id"], second["roster_slot"], second["picked_at"], second["is_auto_pick"]),
            ]
            db.execute("DELETE FROM draft_picks WHERE overall_pick IN (?, ?)",
                       (first["overall_pick"], second["overall_pick"]))
            db.executemany("""
                INSERT INTO draft_picks(
                    overall_pick, round, pick_in_round, user_id, player_id, roster_slot, picked_at, is_auto_pick
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, swapped)
        elif trade["status"] not in {"proposed", "accepted"}:
            raise ValueError("This trade cannot be rejected in its current state.")
        db.execute("""
            UPDATE trade_proposals SET status = ?, resolved_at = CURRENT_TIMESTAMP, resolved_by = ?
            WHERE id = ?
        """, ("approved" if approve else "rejected", commissioner_user_id, trade_id))


def get_order() -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute("""
            SELECT u.id AS user_id, u.username, u.display_name,
                   ft.team_name, ft.team_image, d.position
            FROM draft_order d
            JOIN users u ON u.id = d.user_id
            LEFT JOIN fantasy_teams ft ON ft.user_id = u.id
            ORDER BY d.position
        """)]


def randomize_draft_order(user_id: int) -> list[dict]:
    if not is_commissioner(user_id):
        raise ValueError("Only the commissioner can randomize the draft order.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        settings = db.execute(
            "SELECT status, draft_order_locked FROM draft_settings WHERE id = 1"
        ).fetchone()
        if not settings or settings["status"] != "setup":
            raise ValueError("The draft order can only be randomized during setup.")
        if settings["draft_order_locked"]:
            raise ValueError("The draft order has already been randomized and is immutable.")
        if db.execute("SELECT 1 FROM draft_picks LIMIT 1").fetchone():
            raise ValueError("The draft order cannot change after a pick has been made.")
        pending = db.execute(
            "SELECT COUNT(*) FROM users WHERE is_active = 1 AND is_approved = 0"
        ).fetchone()[0]
        if pending:
            raise ValueError("Approve or remove pending accounts before randomizing the draft order.")
        user_ids = [int(row[0]) for row in db.execute(
            "SELECT id FROM users WHERE is_active = 1 AND is_approved = 1"
        )]
        if not user_ids:
            raise ValueError("Create accounts for all league members before randomizing the order.")
        random.SystemRandom().shuffle(user_ids)
        db.execute("DELETE FROM draft_order")
        db.executemany("INSERT INTO draft_order(user_id, position) VALUES (?, ?)",
                       [(user_id, position) for position, user_id in enumerate(user_ids, start=1)])
        db.execute("UPDATE draft_settings SET draft_order_locked = 1 WHERE id = 1")
        rows = db.execute("""
            SELECT u.id AS user_id, u.username, u.display_name,
                   ft.team_name, ft.team_image, d.position
            FROM draft_order d
            JOIN users u ON u.id = d.user_id
            LEFT JOIN fantasy_teams ft ON ft.user_id = u.id
            ORDER BY d.position
        """).fetchall()
        return [dict(row) for row in rows]


def get_upcoming_picks(limit: int = 4) -> list[dict]:
    """Return the next scheduled snake picks, including fantasy team identities."""
    order = get_order()
    if not order or limit <= 0:
        return []
    with connect() as db:
        settings = db.execute("SELECT status FROM draft_settings WHERE id = 1").fetchone()
        total_picks = int(db.execute("SELECT COUNT(*) FROM draft_picks").fetchone()[0])
    if not settings or settings["status"] == "complete":
        return []

    upcoming = []
    for offset in range(int(limit)):
        overall_pick = total_picks + offset + 1
        round_number = (overall_pick - 1) // len(order) + 1
        pick_in_round = (overall_pick - 1) % len(order) + 1
        round_order = order if round_number % 2 else list(reversed(order))
        upcoming.append({
            **round_order[pick_in_round - 1],
            "overall_pick": overall_pick,
            "round": round_number,
        })
    return upcoming


def replace_player_pool(players: list[dict], league_name: str, league_id: str, region: str) -> None:
    if not players:
        raise ValueError("The player pool is empty.")
    with connect() as db:
        settings = db.execute("SELECT status FROM draft_settings WHERE id = 1").fetchone()
        if not settings or settings["status"] != "setup":
            raise ValueError("The player pool is locked after the draft starts.")
        if db.execute("SELECT 1 FROM draft_picks LIMIT 1").fetchone():
            raise ValueError("The player pool cannot change after a pick has been made.")
        db.execute("DELETE FROM player_pool")
        db.executemany("""
            INSERT INTO player_pool(player_id, player_name, role, team_name, team_code, league_name, region, image_url)
            VALUES (:player_id, :player_name, :role, :team_name, :team_code, :league_name, :region, :image_url)
        """, [
            {
                "player_id": str(p["player_id"]).strip(),
                "player_name": str(p["player_name"]).strip(),
                "role": str(p["role"]).strip().lower(),
                "team_name": str(p.get("team_name", "")).strip(),
                "team_code": str(p.get("team_code", "")).strip(),
                "league_name": league_name,
                "region": region,
                "image_url": str(p.get("image_url") or p.get("photo_url") or "").strip(),
            } for p in players
        ])
        db.execute("UPDATE draft_settings SET league_name = ?, league_id = ?, region = ? WHERE id = 1",
                   (league_name, league_id, region))


def get_pool() -> list[dict]:
    with connect() as db:
        rows = db.execute("""
            SELECT p.player_id, p.player_name, p.role, p.team_name,
                   p.team_code, p.image_url, d.display_name AS drafted_by
            FROM player_pool p
            LEFT JOIN draft_picks k ON k.player_id = p.player_id
            LEFT JOIN users d ON d.id = k.user_id
            ORDER BY p.role, p.player_name COLLATE NOCASE
        """).fetchall()
        pool = [dict(row) for row in rows]

    orgs = [player for player in pool if player["role"] == "team"]
    missing_logos = [player for player in orgs if not player.get("image_url")]
    if missing_logos:
        settings = get_settings()
        if settings.get("league_id"):
            from league_data import fetch_league_org_logos

            try:
                logos = fetch_league_org_logos(
                    str(settings["league_id"]),
                    str(settings["league_name"]),
                    str(settings["region"]),
                )
            except ValueError:
                logos = {}

            for player in missing_logos:
                player["image_url"] = (
                    logos.get(str(player.get("team_code") or "").casefold())
                    or logos.get(str(player.get("team_name") or player["player_name"]).casefold())
                    or logos.get(str(player["player_name"]).casefold())
                    or ""
                )

            updates = [
                (player["image_url"], player["player_id"])
                for player in missing_logos if player["image_url"]
            ]
            if updates:
                with connect() as db:
                    db.executemany(
                        "UPDATE player_pool SET image_url = ? WHERE player_id = ? AND COALESCE(image_url, '') = ''",
                        updates,
                    )

    # Upgrade already-saved organization URLs to HTTPS for mixed-content-safe rendering.
    insecure_orgs = [
        player for player in orgs
        if str(player.get("image_url") or "").lower().startswith("http://")
    ]
    for player in insecure_orgs:
        player["image_url"] = "https://" + player["image_url"][len("http://"):]
    if insecure_orgs:
        with connect() as db:
            db.executemany(
                "UPDATE player_pool SET image_url = ? WHERE player_id = ?",
                [(player["image_url"], player["player_id"]) for player in insecure_orgs],
            )
    return pool


def get_available_players(slot: str) -> list[dict]:
    role = SLOT_ROLE[slot]
    with connect() as db:
        rows = db.execute("""
            SELECT p.player_id, p.player_name, p.role, p.team_name
            FROM player_pool p
            LEFT JOIN draft_picks k ON k.player_id = p.player_id
            WHERE k.player_id IS NULL AND (p.role = ? OR p.role = 'flex')
            ORDER BY p.player_name COLLATE NOCASE
        """, (role,)).fetchall()
        return [dict(row) for row in rows]


def get_user_picks(user_id: int) -> list[dict]:
    # Fill missing org logos and upgrade legacy HTTP org URLs before reading picks.
    get_pool()
    with connect() as db:
        rows = db.execute("""
            SELECT k.overall_pick, k.round, k.pick_in_round, k.roster_slot,
                   p.player_id, p.player_name, p.role, p.team_name, p.team_code, p.image_url
            FROM draft_picks k JOIN player_pool p ON p.player_id = k.player_id
            WHERE k.user_id = ?
            ORDER BY k.overall_pick
        """, (user_id,)).fetchall()
        picks = [dict(row) for row in rows]

    # Older drafts may predate image URLs. Enrich the selected players lazily so
    # their roster portraits can still be filled without reopening the draft.
    missing = [pick for pick in picks if pick["role"] != "team" and not pick.get("image_url")]
    if missing:
        from utils.fandom_images import find_player_images

        images = find_player_images(
            [pick["player_name"] for pick in missing],
            {
                pick["player_name"]: [pick.get("team_name", ""), pick.get("team_code", "")]
                for pick in missing
            },
        )
        for pick in missing:
            pick["image_url"] = images.get(pick["player_name"], "")
        with connect() as db:
            db.executemany(
                "UPDATE player_pool SET image_url = ? WHERE player_id = ? AND COALESCE(image_url, '') = ''",
                [(pick["image_url"], pick["player_id"]) for pick in missing if pick["image_url"]],
            )
    return picks


def get_picks() -> list[dict]:
    with connect() as db:
        rows = db.execute("""
            SELECT k.overall_pick, k.round, k.pick_in_round, k.roster_slot, k.is_auto_pick,
                   u.display_name, u.username, p.player_name, p.role, p.team_name
            FROM draft_picks k
            JOIN users u ON u.id = k.user_id
            JOIN player_pool p ON p.player_id = k.player_id
            ORDER BY k.overall_pick
        """).fetchall()
        return [dict(row) for row in rows]


def get_current_turn() -> dict | None:
    with connect() as db:
        settings = db.execute("SELECT status, turn_started_at FROM draft_settings WHERE id = 1").fetchone()
        if not settings or settings["status"] != "in_progress":
            return None
        order = [dict(row) for row in db.execute("""
            SELECT u.id AS user_id, u.display_name, u.username, d.position
            FROM draft_order d JOIN users u ON u.id = d.user_id ORDER BY d.position
        """)]
        if not order:
            return None
        total = db.execute("SELECT COUNT(*) FROM draft_picks").fetchone()[0]
        overall = int(total) + 1
        round_number = (overall - 1) // len(order) + 1
        pick_in_round = (overall - 1) % len(order) + 1
        round_order = order if round_number % 2 else list(reversed(order))
        seconds_remaining = _seconds_remaining(settings["turn_started_at"])
        return {
            "overall_pick": overall,
            "round": round_number,
            "pick_in_round": pick_in_round,
            "user_id": round_order[pick_in_round - 1]["user_id"],
            "display_name": round_order[pick_in_round - 1]["display_name"],
            "seconds_remaining": seconds_remaining,
        }


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _seconds_remaining(turn_started_at: str | None) -> int:
    started = _parse_timestamp(turn_started_at)
    if started is None:
        return DRAFT_PICK_SECONDS
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    return min(DRAFT_PICK_SECONDS, max(0, math.ceil(DRAFT_PICK_SECONDS - elapsed)))


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@lru_cache(maxsize=1)
def _spring_split_draft_scores() -> dict:
    try:
        from demo_data import build_spring_split_draft_scores
        return build_spring_split_draft_scores()
    except (OSError, ValueError, KeyError, RuntimeError):
        return {"players": {}, "teams": {}}


def auto_pick_if_expired() -> dict | None:
    """Make the Spring-split highest-score legal pick once a turn timer expires."""
    with connect() as db:
        settings = db.execute("SELECT status, turn_started_at FROM draft_settings WHERE id = 1").fetchone()
        if not settings or settings["status"] != "in_progress" or _seconds_remaining(settings["turn_started_at"]) > 0:
            return None
    scores = _spring_split_draft_scores()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        settings = db.execute("SELECT status, turn_started_at FROM draft_settings WHERE id = 1").fetchone()
        if not settings or settings["status"] != "in_progress" or _seconds_remaining(settings["turn_started_at"]) > 0:
            return None

        order = [dict(row) for row in db.execute("""
            SELECT u.id AS user_id, u.display_name
            FROM draft_order d JOIN users u ON u.id = d.user_id ORDER BY d.position
        """)]
        if not order:
            return None
        total = int(db.execute("SELECT COUNT(*) FROM draft_picks").fetchone()[0])
        round_number = total // len(order) + 1
        pick_in_round = total % len(order) + 1
        round_order = order if round_number % 2 else list(reversed(order))
        current_user = round_order[pick_in_round - 1]
        owned_slots = {row[0] for row in db.execute(
            "SELECT roster_slot FROM draft_picks WHERE user_id = ?", (current_user["user_id"],)
        )}
        available = [dict(row) for row in db.execute("""
            SELECT p.player_id, p.player_name, p.role, p.team_name
            FROM player_pool p LEFT JOIN draft_picks k ON k.player_id = p.player_id
            WHERE k.player_id IS NULL
        """)]
        options = []
        for slot_index, slot in enumerate(SLOTS):
            if slot in owned_slots:
                continue
            eligible_role = SLOT_ROLE[slot]
            for player in available:
                if player["role"] not in {eligible_role, "flex"}:
                    continue
                score_map = scores["teams"] if slot == "team" else scores["players"]
                score = float(score_map.get(str(player["player_id"]), 0.0))
                options.append((-
                    score, slot_index, player["player_name"].casefold(), player, slot
                ))
        if not options:
            # Keep the room live if the imported pool unexpectedly cannot fill
            # this slot; the commissioner can resolve the pool configuration.
            db.execute("UPDATE draft_settings SET turn_started_at = ? WHERE id = 1", (_now_utc(),))
            return {"error": f"No eligible players remain for {current_user['display_name']}."}

        negative_score, _, _, player, slot = min(options, key=lambda option: option[:3])
        overall = total + 1
        db.execute("""
            INSERT INTO draft_picks(
                overall_pick, round, pick_in_round, user_id, player_id, roster_slot, is_auto_pick
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (overall, round_number, pick_in_round, current_user["user_id"], player["player_id"], slot))
        total += 1
        if total == len(order) * len(SLOTS):
            db.execute("UPDATE draft_settings SET status = 'complete', completed_at = CURRENT_TIMESTAMP, turn_started_at = NULL WHERE id = 1")
            create_random_schedule(db, [row["user_id"] for row in order])
        else:
            db.execute("UPDATE draft_settings SET turn_started_at = ? WHERE id = 1", (_now_utc(),))
        return {
            "user": current_user["display_name"], "player": player["player_name"],
            "slot": slot, "score": round(-negative_score, 2),
        }


def start_draft() -> None:
    with connect() as db:
        settings = db.execute("SELECT status, draft_order_locked FROM draft_settings WHERE id = 1").fetchone()
        if not settings or settings["status"] != "setup":
            raise ValueError("The draft can only be started once from setup.")
        if not settings["draft_order_locked"]:
            raise ValueError("The commissioner must randomize the draft order before starting.")
        if db.execute("SELECT 1 FROM draft_picks LIMIT 1").fetchone():
            raise ValueError("This draft already has picks.")
        pending = db.execute(
            "SELECT COUNT(*) FROM users WHERE is_active = 1 AND is_approved = 0"
        ).fetchone()[0]
        if pending:
            raise ValueError("Approve or remove pending accounts before starting the draft.")
        users = [r[0] for r in db.execute(
            "SELECT id FROM users WHERE is_active = 1 AND is_approved = 1"
        )]
        order = [r[0] for r in db.execute("SELECT user_id FROM draft_order")]
        if not users or len(order) != len(users) or set(order) != set(users):
            raise ValueError("The draft order must include every registered user. Contact the commissioner.")
        counts = {r["role"]: r["n"] for r in db.execute(
            "SELECT role, COUNT(*) AS n FROM player_pool GROUP BY role")}
        for slot, role in SLOT_ROLE.items():
            if counts.get(role, 0) < len(users):
                raise ValueError(f"The pool needs at least {len(users)} eligible picks for the {slot} slot.")
        db.execute("""UPDATE draft_settings SET status = 'in_progress', started_at = CURRENT_TIMESTAMP,
            turn_started_at = ? WHERE id = 1""", (_now_utc(),))


def make_pick(user_id: int, player_id: str, slot: str, expected_overall: int | None = None) -> None:
    if slot not in SLOT_ROLE:
        raise ValueError("Unknown roster slot.")
    try:
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            settings = db.execute("SELECT status, turn_started_at FROM draft_settings WHERE id = 1").fetchone()
            if not settings or settings["status"] != "in_progress":
                raise ValueError("The draft is not accepting picks.")
            if _seconds_remaining(settings["turn_started_at"]) <= 0:
                raise ValueError("Your 45-second pick window expired. The automatic pick will be made now.")
            order = [dict(row) for row in db.execute("""
                SELECT u.id AS user_id FROM draft_order d
                JOIN users u ON u.id = d.user_id ORDER BY d.position
            """)]
            total = db.execute("SELECT COUNT(*) FROM draft_picks").fetchone()[0]
            if expected_overall is not None and int(total) + 1 != int(expected_overall):
                raise ValueError("The turn changed. Refresh the draft board and make the current pick.")
            round_number = int(total) // len(order) + 1
            pick_in_round = int(total) % len(order) + 1
            round_order = order if round_number % 2 else list(reversed(order))
            expected_user_id = round_order[pick_in_round - 1]["user_id"]
            if user_id != expected_user_id:
                raise ValueError("It is not your turn to pick.")
            if db.execute("SELECT 1 FROM draft_picks WHERE user_id = ? AND roster_slot = ?",
                          (user_id, slot)).fetchone():
                raise ValueError(f"You already drafted a pick for {slot}.")
            role = SLOT_ROLE[slot]
            player = db.execute("""
                SELECT player_id FROM player_pool
                WHERE player_id = ? AND (role = ? OR role = 'flex')
            """, (player_id, role)).fetchone()
            if not player:
                raise ValueError("That player is not available for this roster slot.")
            overall = int(total) + 1
            db.execute("""
                INSERT INTO draft_picks(overall_pick, round, pick_in_round, user_id, player_id, roster_slot)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (overall, round_number, pick_in_round, user_id, player_id, slot))
            total += 1
            if total == len(order) * len(SLOTS):
                db.execute("UPDATE draft_settings SET status = 'complete', completed_at = CURRENT_TIMESTAMP, turn_started_at = NULL WHERE id = 1")
                create_random_schedule(db, [int(row[0]) for row in db.execute(
                    "SELECT user_id FROM draft_order ORDER BY position"
                )])
            else:
                db.execute("UPDATE draft_settings SET turn_started_at = ? WHERE id = 1", (_now_utc(),))
    except sqlite3.IntegrityError as exc:
        raise ValueError("That player was just picked by another user. Refresh and choose another player.") from exc
