import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("FANTASY_DB_PATH", ROOT / "data" / "fantasy_lcs.sqlite3"))
SLOTS = ("team", "top", "jg", "mid", "adc", "sup")


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_database() -> None:
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                role TEXT NOT NULL DEFAULT 'owner',
                is_approved INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS auth_remember_tokens (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS draft_page_presence (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS fantasy_teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                team_name TEXT NOT NULL DEFAULT 'My Fantasy Team',
                team_image BLOB,
                team_image_mime TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS roster_slots (
                team_id INTEGER NOT NULL REFERENCES fantasy_teams(id) ON DELETE CASCADE,
                slot TEXT NOT NULL,
                player_id TEXT NOT NULL DEFAULT '',
                player_name TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(team_id, slot)
            );
            CREATE TABLE IF NOT EXISTS league_teams (
                legacy_id TEXT PRIMARY KEY,
                team_name TEXT NOT NULL,
                owner_name TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS matchups (
                week TEXT NOT NULL,
                matchup_id TEXT NOT NULL,
                team_1_id TEXT NOT NULL,
                team_2_id TEXT NOT NULL,
                PRIMARY KEY(week, matchup_id)
            );
            CREATE TABLE IF NOT EXISTS fantasy_matchup_schedule (
                week_number INTEGER NOT NULL CHECK(week_number > 0),
                matchup_number INTEGER NOT NULL CHECK(matchup_number > 0),
                team_1_user_id INTEGER NOT NULL REFERENCES users(id),
                team_2_user_id INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(week_number, matchup_number),
                CHECK(team_2_user_id IS NULL OR team_1_user_id <> team_2_user_id)
            );
            CREATE TABLE IF NOT EXISTS fantasy_matchup_results (
                week_number INTEGER NOT NULL,
                matchup_number INTEGER NOT NULL,
                split_name TEXT NOT NULL,
                team_1_score REAL NOT NULL,
                team_2_score REAL,
                team_1_breakdown_json TEXT NOT NULL,
                team_2_breakdown_json TEXT NOT NULL,
                winner_user_id INTEGER REFERENCES users(id),
                updated_at TEXT NOT NULL,
                PRIMARY KEY(week_number, matchup_number),
                FOREIGN KEY(week_number, matchup_number)
                    REFERENCES fantasy_matchup_schedule(week_number, matchup_number) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS weekly_dragon_bonus (
                week_number INTEGER PRIMARY KEY CHECK(week_number > 0),
                dragon_type TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS matchup_champion_choices (
                week TEXT NOT NULL,
                fantasy_team_id TEXT NOT NULL,
                choice_type TEXT NOT NULL CHECK(choice_type IN ('pick', 'ban')),
                choice_number INTEGER NOT NULL CHECK(choice_number IN (1, 2)),
                role TEXT NOT NULL CHECK(role IN ('top', 'jg', 'mid', 'adc', 'sup')),
                champion_name TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(week, fantasy_team_id, choice_type, choice_number)
            );
            CREATE TABLE IF NOT EXISTS draft_settings (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                status TEXT NOT NULL DEFAULT 'setup',
                league_name TEXT NOT NULL DEFAULT 'LCS',
                league_id TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT 'North America',
                scheduled_at TEXT,
                turn_started_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                draft_order_locked INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS player_pool (
                player_id TEXT PRIMARY KEY,
                player_name TEXT NOT NULL,
                role TEXT NOT NULL,
                team_name TEXT NOT NULL DEFAULT '',
                team_code TEXT NOT NULL DEFAULT '',
                league_name TEXT NOT NULL,
                region TEXT NOT NULL,
                image_url TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS draft_order (
                user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                position INTEGER NOT NULL UNIQUE CHECK(position > 0),
                PRIMARY KEY(user_id)
            );
            CREATE TABLE IF NOT EXISTS draft_picks (
                overall_pick INTEGER PRIMARY KEY,
                round INTEGER NOT NULL,
                pick_in_round INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id),
                player_id TEXT NOT NULL UNIQUE REFERENCES player_pool(player_id),
                roster_slot TEXT NOT NULL,
                picked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_auto_pick INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS roster_exchanges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                roster_slot TEXT NOT NULL,
                outgoing_player_id TEXT NOT NULL REFERENCES player_pool(player_id),
                incoming_player_id TEXT NOT NULL REFERENCES player_pool(player_id),
                split_name TEXT NOT NULL,
                exchanged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS live_match_cache (
                match_id TEXT PRIMARY KEY,
                league_id TEXT NOT NULL DEFAULT '',
                match_state TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS trade_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposer_user_id INTEGER NOT NULL REFERENCES users(id),
                recipient_user_id INTEGER NOT NULL REFERENCES users(id),
                offered_player_id TEXT NOT NULL REFERENCES player_pool(player_id),
                requested_player_id TEXT NOT NULL REFERENCES player_pool(player_id),
                status TEXT NOT NULL DEFAULT 'proposed'
                    CHECK(status IN ('proposed', 'accepted', 'approved', 'rejected', 'cancelled')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT,
                resolved_by INTEGER REFERENCES users(id),
                CHECK(proposer_user_id <> recipient_user_id),
                CHECK(offered_player_id <> requested_player_id)
            );
        """)
        user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        if "is_admin" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        if "role" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'owner'")
        settings_columns = {row[1] for row in db.execute("PRAGMA table_info(draft_settings)")}
        if "scheduled_at" not in settings_columns:
            db.execute("ALTER TABLE draft_settings ADD COLUMN scheduled_at TEXT")
        if "turn_started_at" not in settings_columns:
            db.execute("ALTER TABLE draft_settings ADD COLUMN turn_started_at TEXT")
        user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        if "is_approved" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN is_approved INTEGER NOT NULL DEFAULT 1")
        if "is_active" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        if "draft_order_locked" not in settings_columns:
            db.execute("ALTER TABLE draft_settings ADD COLUMN draft_order_locked INTEGER NOT NULL DEFAULT 0")
        pick_columns = {row[1] for row in db.execute("PRAGMA table_info(draft_picks)")}
        if "is_auto_pick" not in pick_columns:
            db.execute("ALTER TABLE draft_picks ADD COLUMN is_auto_pick INTEGER NOT NULL DEFAULT 0")
        pool_columns = {row[1] for row in db.execute("PRAGMA table_info(player_pool)")}
        if "image_url" not in pool_columns:
            db.execute("ALTER TABLE player_pool ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")
        if "team_code" not in pool_columns:
            db.execute("ALTER TABLE player_pool ADD COLUMN team_code TEXT NOT NULL DEFAULT ''")
        fantasy_team_columns = {row[1] for row in db.execute("PRAGMA table_info(fantasy_teams)")}
        if "team_image" not in fantasy_team_columns:
            db.execute("ALTER TABLE fantasy_teams ADD COLUMN team_image BLOB")
        if "team_image_mime" not in fantasy_team_columns:
            db.execute("ALTER TABLE fantasy_teams ADD COLUMN team_image_mime TEXT NOT NULL DEFAULT ''")
        db.execute("INSERT OR IGNORE INTO draft_settings(id) VALUES (1)")
        if not db.execute("SELECT 1 FROM users WHERE is_admin = 1 LIMIT 1").fetchone():
            db.execute("UPDATE users SET is_admin = 1 WHERE id = (SELECT MIN(id) FROM users)")
        db.execute("UPDATE users SET role = 'commissioner' WHERE is_admin = 1")
        db.execute("UPDATE draft_settings SET turn_started_at = CURRENT_TIMESTAMP WHERE status = 'in_progress' AND turn_started_at IS NULL")
        db.execute("INSERT OR IGNORE INTO fantasy_teams(user_id, team_name) SELECT id, display_name || ' Team' FROM users")
        _seed_legacy_schedule(db)


def _seed_legacy_schedule(db) -> None:
    if db.execute("SELECT 1 FROM matchups LIMIT 1").fetchone():
        return
    schedule_path, teams_path = ROOT / "schedule.json", ROOT / "teams_test.json"
    if not schedule_path.exists() or not teams_path.exists():
        return
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    teams = json.loads(teams_path.read_text(encoding="utf-8"))
    for legacy_id, team in teams.items():
        db.execute("INSERT OR IGNORE INTO league_teams VALUES (?, ?, ?)",
                   (str(legacy_id), team.get("name", f"Team {legacy_id}"), team.get("owner", "")))
    for week, week_matches in schedule.items():
        for matchup_id, team_ids in week_matches.items():
            if len(team_ids) == 2:
                db.execute("INSERT OR IGNORE INTO matchups VALUES (?, ?, ?, ?)",
                           (week, str(matchup_id), str(team_ids[0]), str(team_ids[1])))


def find_user(username: str):
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def create_remember_token(user_id: int, lifetime_days: int = 30) -> tuple[str, datetime]:
    """Create a random long-lived sign-in token, storing only its SHA-256 digest."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=max(1, int(lifetime_days)))
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        account = db.execute(
            "SELECT is_active, is_approved FROM users WHERE id = ?", (int(user_id),)
        ).fetchone()
        if not account or not account["is_active"] or not account["is_approved"]:
            raise ValueError("This account cannot create a persistent sign-in.")
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.execute("DELETE FROM auth_remember_tokens WHERE expires_at <= ?", (now_iso,))
        db.execute(
            "INSERT INTO auth_remember_tokens(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, int(user_id), expires_at.isoformat(timespec="seconds")),
        )
    return token, expires_at


def get_user_by_remember_token(token: str) -> dict | None:
    """Validate a persistent sign-in token and return its active account."""
    if not token or len(token) > 256:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connect() as db:
        row = db.execute("""
            SELECT account.id, account.display_name, account.is_active, account.is_approved,
                   session.expires_at
            FROM auth_remember_tokens AS session
            JOIN users AS account ON account.id = session.user_id
            WHERE session.token_hash = ?
        """, (token_hash,)).fetchone()
        if not row:
            return None
        expires_at = datetime.fromisoformat(row["expires_at"])
        if (not row["is_active"] or not row["is_approved"]
                or expires_at <= datetime.now(timezone.utc)):
            db.execute("DELETE FROM auth_remember_tokens WHERE token_hash = ?", (token_hash,))
            return None
        return {"id": int(row["id"]), "display_name": row["display_name"]}


def revoke_remember_token(token: str | None) -> None:
    """Revoke one browser's persistent sign-in token."""
    if not token or len(token) > 256:
        return
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connect() as db:
        db.execute("DELETE FROM auth_remember_tokens WHERE token_hash = ?", (token_hash,))


def create_user(username: str, display_name: str, salt: str, digest: str) -> int:
    try:
        with connect() as db:
            draft = db.execute("SELECT status, draft_order_locked FROM draft_settings WHERE id = 1").fetchone()
            if draft and draft["status"] != "setup":
                raise ValueError("Registration is closed after the draft begins.")
            if draft and draft["draft_order_locked"]:
                raise ValueError("Registration closes when the commissioner randomizes the draft order.")
            make_commissioner = not db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            cur = db.execute("""INSERT INTO users(
                username, display_name, password_salt, password_hash, is_admin, role,
                is_approved, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                             (username, display_name, salt, digest, int(make_commissioner),
                              "commissioner" if make_commissioner else "owner", int(make_commissioner)))
            db.execute("INSERT INTO fantasy_teams(user_id, team_name) VALUES (?, ?)",
                       (int(cur.lastrowid), f"{display_name} Team"))
            return int(cur.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise ValueError("username already exists") from exc


def get_users() -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT id, username, display_name, is_admin, role FROM users "
            "WHERE is_active = 1 AND is_approved = 1 ORDER BY id")]


def get_user_accounts() -> list[dict]:
    """Return accounts for commissioner approval and access management."""
    with connect() as db:
        return [dict(row) for row in db.execute("""
            SELECT id, username, display_name, role, is_admin, is_approved,
                   is_active, created_at
            FROM users ORDER BY created_at, id
        """)]


def get_user_access(user_id: int) -> dict | None:
    with connect() as db:
        row = db.execute(
            "SELECT id, display_name, is_approved, is_active FROM users WHERE id = ?",
            (int(user_id),),
        ).fetchone()
        return dict(row) if row else None


def approve_user_account(commissioner_id: int, target_user_id: int) -> None:
    if not is_commissioner(commissioner_id):
        raise ValueError("Only the commissioner can approve accounts.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT is_approved, is_active FROM users WHERE id = ?",
            (int(target_user_id),),
        ).fetchone()
        if not row or not row["is_active"]:
            raise ValueError("That account is unavailable.")
        if row["is_approved"]:
            raise ValueError("That account is already approved.")
        db.execute("UPDATE users SET is_approved = 1 WHERE id = ?", (int(target_user_id),))


def remove_user_account(commissioner_id: int, target_user_id: int) -> str:
    """Remove an account; preserve completed-draft team history when applicable."""
    if not is_commissioner(commissioner_id):
        raise ValueError("Only the commissioner can remove accounts.")
    if int(commissioner_id) == int(target_user_id):
        raise ValueError("The commissioner cannot remove their own account.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        account = db.execute(
            "SELECT role, is_admin, is_active FROM users WHERE id = ?",
            (int(target_user_id),),
        ).fetchone()
        if not account or not account["is_active"]:
            raise ValueError("That account is already removed or does not exist.")
        if account["role"] == "commissioner" or account["is_admin"]:
            raise ValueError("A commissioner account cannot be removed here.")
        draft = db.execute("SELECT status, draft_order_locked FROM draft_settings WHERE id = 1").fetchone()
        status = draft["status"] if draft else "setup"
        if status == "in_progress":
            raise ValueError("Accounts cannot be removed during an active draft.")
        db.execute("DELETE FROM auth_remember_tokens WHERE user_id = ?", (int(target_user_id),))
        if status == "setup":
            was_in_order = db.execute(
                "SELECT 1 FROM draft_order WHERE user_id = ?", (int(target_user_id),)
            ).fetchone()
            db.execute("DELETE FROM draft_picks WHERE user_id = ?", (int(target_user_id),))
            db.execute("DELETE FROM trade_proposals WHERE proposer_user_id = ? OR recipient_user_id = ?",
                       (int(target_user_id), int(target_user_id)))
            db.execute("DELETE FROM roster_exchanges WHERE user_id = ?", (int(target_user_id),))
            db.execute("DELETE FROM fantasy_matchup_schedule WHERE team_1_user_id = ? OR team_2_user_id = ?",
                       (int(target_user_id), int(target_user_id)))
            db.execute("DELETE FROM matchup_champion_choices WHERE fantasy_team_id = ?",
                       (str(int(target_user_id)),))
            db.execute("DELETE FROM users WHERE id = ?", (int(target_user_id),))
            if was_in_order or (draft and draft["draft_order_locked"]):
                db.execute("DELETE FROM draft_order")
                db.execute("UPDATE draft_settings SET draft_order_locked = 0 WHERE id = 1")
            return "deleted"
        db.execute("UPDATE users SET is_active = 0 WHERE id = ?", (int(target_user_id),))
        order_row = db.execute(
            "SELECT position FROM draft_order WHERE user_id = ?", (int(target_user_id),)
        ).fetchone()
        if order_row:
            db.execute("DELETE FROM draft_order WHERE user_id = ?", (int(target_user_id),))
            remaining_order = [int(row[0]) for row in db.execute(
                "SELECT user_id FROM draft_order ORDER BY position"
            )]
            if remaining_order:
                max_position = int(db.execute(
                    "SELECT COALESCE(MAX(position), 0) FROM draft_order"
                ).fetchone()[0])
                offset = max_position + 1
                for remaining_user_id in remaining_order:
                    db.execute(
                        "UPDATE draft_order SET position = position + ? WHERE user_id = ?",
                        (offset, remaining_user_id),
                    )
                for position, remaining_user_id in enumerate(remaining_order, start=1):
                    db.execute(
                        "UPDATE draft_order SET position = ? WHERE user_id = ?",
                        (position, remaining_user_id),
                    )
        return "disabled"


def get_fantasy_team_profile(user_id: int) -> dict | None:
    """Return one owner's team name and optional uploaded image."""
    with connect() as db:
        row = db.execute(
            "SELECT team_name, team_image, team_image_mime FROM fantasy_teams WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        return dict(row) if row else None


def rename_fantasy_team(user_id: int, team_name: str) -> None:
    """Rename only the fantasy team owned by the given user."""
    normalized_name = str(team_name or "").strip()
    if not normalized_name:
        raise ValueError("Enter a team name.")
    if len(normalized_name) > 50:
        raise ValueError("Team names must be 50 characters or fewer.")
    with connect() as db:
        updated = db.execute(
            "UPDATE fantasy_teams SET team_name = ? WHERE user_id = ?",
            (normalized_name, int(user_id)),
        ).rowcount
        if not updated:
            raise ValueError("Your fantasy team profile could not be found.")


def save_fantasy_team_image(user_id: int, image_data: bytes, mime_type: str = "image/png") -> None:
    """Save an image only to the fantasy team owned by the authenticated user."""
    if not image_data or len(image_data) > 5 * 1024 * 1024:
        raise ValueError("Team images must be between 1 byte and 5 MB.")
    if mime_type != "image/png":
        raise ValueError("Team images must be normalized to PNG before saving.")
    with connect() as db:
        updated = db.execute(
            "UPDATE fantasy_teams SET team_image = ?, team_image_mime = ? WHERE user_id = ?",
            (sqlite3.Binary(image_data), mime_type, int(user_id)),
        ).rowcount
        if not updated:
            raise ValueError("Your fantasy team profile could not be found.")


def clear_fantasy_team_image(user_id: int) -> None:
    with connect() as db:
        db.execute(
            "UPDATE fantasy_teams SET team_image = NULL, team_image_mime = '' WHERE user_id = ?",
            (int(user_id),),
        )


def is_admin(user_id: int) -> bool:
    with connect() as db:
        row = db.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row and row["is_admin"])


def is_commissioner(user_id: int) -> bool:
    with connect() as db:
        row = db.execute(
            "SELECT role, is_admin, is_approved, is_active FROM users WHERE id = ?",
            (int(user_id),),
        ).fetchone()
        return bool(row and row["is_active"] and row["is_approved"]
                    and (row["role"] == "commissioner" or row["is_admin"]))


def clear_draft_results(commissioner_id: int) -> None:
    """Clear draft results and order while keeping the imported pool and league accounts."""
    if not is_commissioner(commissioner_id):
        raise ValueError("Only the commissioner can clear draft results.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        settings = db.execute("SELECT status FROM draft_settings WHERE id = 1").fetchone()
        if not settings:
            raise ValueError("Draft settings are unavailable.")
        if settings["status"] == "in_progress":
            raise ValueError("The draft must be completed or in setup before its results can be cleared.")
        db.execute("DELETE FROM trade_proposals")
        db.execute("DELETE FROM roster_exchanges")
        db.execute("DELETE FROM draft_picks")
        db.execute("DELETE FROM draft_order")
        db.execute("DELETE FROM fantasy_matchup_schedule")
        db.execute("DELETE FROM fantasy_matchup_results")
        db.execute("DELETE FROM weekly_dragon_bonus")
        db.execute("DELETE FROM matchup_champion_choices")
        db.execute("""UPDATE draft_settings SET status = 'setup', draft_order_locked = 0,
            turn_started_at = NULL, started_at = NULL, completed_at = NULL WHERE id = 1""")


def reset_league_information(commissioner_id: int) -> None:
    """Reset league setup and results while preserving user logins and API match history."""
    if not is_commissioner(commissioner_id):
        raise ValueError("Only the commissioner can reset league information.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        settings = db.execute("SELECT status FROM draft_settings WHERE id = 1").fetchone()
        if not settings:
            raise ValueError("Draft settings are unavailable.")
        if settings["status"] == "in_progress":
            raise ValueError("The league cannot be reset while a draft is in progress.")
        db.execute("DELETE FROM trade_proposals")
        db.execute("DELETE FROM roster_exchanges")
        db.execute("DELETE FROM draft_picks")
        db.execute("DELETE FROM draft_order")
        db.execute("DELETE FROM fantasy_matchup_schedule")
        db.execute("DELETE FROM fantasy_matchup_results")
        db.execute("DELETE FROM weekly_dragon_bonus")
        db.execute("DELETE FROM matchup_champion_choices")
        db.execute("DELETE FROM roster_slots")
        db.execute("DELETE FROM matchups")
        db.execute("DELETE FROM league_teams")
        db.execute("DELETE FROM player_pool")
        db.execute("""UPDATE fantasy_teams
            SET team_name = COALESCE((SELECT NULLIF(users.display_name, '') FROM users
                                      WHERE users.id = fantasy_teams.user_id), 'My Fantasy Team') || ' Team',
                team_image = NULL, team_image_mime = ''""")
        db.execute("""UPDATE draft_settings SET status = 'setup', league_name = 'LCS',
            league_id = '', region = 'North America', scheduled_at = NULL,
            turn_started_at = NULL, started_at = NULL, completed_at = NULL,
            draft_order_locked = 0 WHERE id = 1""")


def touch_draft_page_presence(user_id: int) -> None:
    """Record that an authenticated user is currently viewing the Draft page."""
    with connect() as db:
        db.execute("""
            INSERT INTO draft_page_presence(user_id, last_seen)
            VALUES (?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET last_seen = CURRENT_TIMESTAMP
        """, (int(user_id),))


def get_active_draft_page_user_ids(active_for_seconds: int = 30) -> set[int]:
    """Return approved members who checked in on the Draft page recently."""
    timeout = max(1, int(active_for_seconds))
    with connect() as db:
        rows = db.execute("""
            SELECT presence.user_id
            FROM draft_page_presence AS presence
            JOIN users AS account ON account.id = presence.user_id
            WHERE account.is_active = 1 AND account.is_approved = 1
              AND presence.last_seen >= datetime('now', ?)
        """, (f"-{timeout} seconds",)).fetchall()
        return {int(row[0]) for row in rows}


def get_matchup_weeks() -> list[str]:
    with connect() as db:
        return [r[0] for r in db.execute(
            "SELECT DISTINCT week FROM matchups ORDER BY CAST(substr(week, 6) AS INTEGER)")]


def get_matchups(week: str) -> list[dict]:
    with connect() as db:
        rows = db.execute("""SELECT m.matchup_id, m.week,
            a.team_name AS team_1, a.owner_name AS owner_1,
            b.team_name AS team_2, b.owner_name AS owner_2
            FROM matchups m
            LEFT JOIN league_teams a ON a.legacy_id = m.team_1_id
            LEFT JOIN league_teams b ON b.legacy_id = m.team_2_id
            WHERE m.week = ? ORDER BY m.matchup_id""", (week,)).fetchall()
        return [dict(row) for row in rows]


def get_fantasy_matchup_schedule(week_number: int | None = None) -> list[dict]:
    """Return generated user-team matchups, optionally for one schedule week."""
    where = "WHERE s.week_number = ?" if week_number is not None else ""
    params = (int(week_number),) if week_number is not None else ()
    with connect() as db:
        _ensure_schedule_dragon_bonuses(db)
        rows = db.execute(f"""
            SELECT s.week_number, s.matchup_number,
                   s.team_1_user_id, one.display_name AS team_1_owner,
                   COALESCE(one_team.team_name, one.display_name || ' Team') AS team_1_name,
                   one_team.team_image AS team_1_image,
                   s.team_2_user_id, two.display_name AS team_2_owner,
                   CASE WHEN two.id IS NULL THEN ''
                        ELSE COALESCE(two_team.team_name, two.display_name || ' Team') END AS team_2_name,
                   two_team.team_image AS team_2_image,
                   result.split_name, result.team_1_score, result.team_2_score,
                   result.team_1_breakdown_json, result.team_2_breakdown_json,
                   result.winner_user_id, result.updated_at AS score_updated_at
            FROM fantasy_matchup_schedule s
            JOIN users one ON one.id = s.team_1_user_id
            LEFT JOIN fantasy_teams one_team ON one_team.user_id = one.id
            LEFT JOIN users two ON two.id = s.team_2_user_id
            LEFT JOIN fantasy_teams two_team ON two_team.user_id = two.id
            LEFT JOIN fantasy_matchup_results result
                ON result.week_number = s.week_number AND result.matchup_number = s.matchup_number
            {where}
            ORDER BY s.week_number, s.matchup_number
        """, params).fetchall()
        return [dict(row) for row in rows]


def get_user_fantasy_matchup_schedule(user_id: int) -> list[dict]:
    """Return all generated matchups involving one authenticated team."""
    with connect() as db:
        _ensure_schedule_dragon_bonuses(db)
        rows = db.execute("""
            SELECT s.week_number, s.matchup_number,
                   s.team_1_user_id, one.display_name AS team_1_owner,
                   COALESCE(one_team.team_name, one.display_name || ' Team') AS team_1_name,
                   s.team_2_user_id, two.display_name AS team_2_owner,
                   CASE WHEN two.id IS NULL THEN ''
                        ELSE COALESCE(two_team.team_name, two.display_name || ' Team') END AS team_2_name,
                   result.split_name, result.team_1_score, result.team_2_score,
                   result.team_1_breakdown_json, result.team_2_breakdown_json,
                   result.winner_user_id, result.updated_at AS score_updated_at
            FROM fantasy_matchup_schedule s
            JOIN users one ON one.id = s.team_1_user_id
            LEFT JOIN fantasy_teams one_team ON one_team.user_id = one.id
            LEFT JOIN users two ON two.id = s.team_2_user_id
            LEFT JOIN fantasy_teams two_team ON two_team.user_id = two.id
            LEFT JOIN fantasy_matchup_results result
                ON result.week_number = s.week_number AND result.matchup_number = s.matchup_number
            WHERE s.team_1_user_id = ? OR s.team_2_user_id = ?
            ORDER BY s.week_number, s.matchup_number
        """, (int(user_id), int(user_id))).fetchall()
        return [dict(row) for row in rows]


def get_fantasy_roster_assignments() -> list[dict]:
    """Return drafted roster slots with the API player IDs used for scoring."""
    with connect() as db:
        rows = db.execute("""
            SELECT k.user_id, k.roster_slot, p.player_id, p.player_name,
                   p.role, p.team_name, p.team_code
            FROM draft_picks k
            JOIN player_pool p ON p.player_id = k.player_id
            ORDER BY k.user_id, k.roster_slot
        """).fetchall()
        return [dict(row) for row in rows]


def get_matchup_champion_choice_rows() -> list[dict]:
    """Return saved pick/ban choices for use when recomputing fantasy points."""
    with connect() as db:
        _ensure_matchup_champion_choices(db)
        rows = db.execute("""
            SELECT week, fantasy_team_id, choice_type, role, champion_name
            FROM matchup_champion_choices
            ORDER BY week, fantasy_team_id, choice_type, choice_number
        """).fetchall()
        return [dict(row) for row in rows]


def replace_fantasy_matchup_results(commissioner_id: int, split_name: str,
                                    results: list[dict]) -> None:
    """Replace saved scores for a split after recomputing with current rules."""
    if not is_commissioner(commissioner_id):
        raise ValueError("Only the commissioner can refresh matchup points.")
    if not results:
        raise ValueError("No scheduled matchups were available to score.")
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM fantasy_matchup_results")
        db.executemany("""
            INSERT INTO fantasy_matchup_results(
                week_number, matchup_number, split_name, team_1_score, team_2_score,
                team_1_breakdown_json, team_2_breakdown_json, winner_user_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [(
            int(row["week_number"]), int(row["matchup_number"]), str(split_name),
            float(row["team_1_score"]),
            None if row.get("team_2_score") is None else float(row["team_2_score"]),
            json.dumps(row.get("team_1_breakdown", []), ensure_ascii=False),
            json.dumps(row.get("team_2_breakdown", []), ensure_ascii=False),
            row.get("winner_user_id"), updated_at,
        ) for row in results])


def get_fantasy_matchup_records() -> dict[int, dict]:
    """Calculate cumulative W-L-D and points from the currently saved results."""
    with connect() as db:
        rows = db.execute("""
            SELECT s.team_1_user_id, s.team_2_user_id,
                   r.team_1_score, r.team_2_score, r.winner_user_id
            FROM fantasy_matchup_schedule s
            JOIN fantasy_matchup_results r
              ON r.week_number = s.week_number AND r.matchup_number = s.matchup_number
        """).fetchall()
    records: dict[int, dict] = {}
    for row in rows:
        first_id = int(row["team_1_user_id"])
        first = records.setdefault(first_id, {"wins": 0, "losses": 0, "draws": 0, "points": 0.0})
        first["points"] += float(row["team_1_score"] or 0)
        if row["team_2_user_id"] is None:
            continue
        second_id = int(row["team_2_user_id"])
        second = records.setdefault(second_id, {"wins": 0, "losses": 0, "draws": 0, "points": 0.0})
        second["points"] += float(row["team_2_score"] or 0)
        if row["winner_user_id"] is None:
            first["draws"] += 1
            second["draws"] += 1
        elif int(row["winner_user_id"]) == first_id:
            first["wins"] += 1
            second["losses"] += 1
        else:
            second["wins"] += 1
            first["losses"] += 1
    return records


def _ensure_schedule_dragon_bonuses(db) -> None:
    """Backfill weekly dragon draws for schedules created before this feature."""
    weeks = [int(row[0]) for row in db.execute(
        "SELECT DISTINCT week_number FROM fantasy_matchup_schedule ORDER BY week_number"
    )]
    if weeks:
        from matchup_schedule import create_weekly_dragon_bonuses
        create_weekly_dragon_bonuses(db, weeks)


def get_weekly_dragon_bonus(week_number: int) -> str | None:
    """Return the persisted featured dragon assigned to one fantasy week."""
    with connect() as db:
        row = db.execute(
            "SELECT dragon_type FROM weekly_dragon_bonus WHERE week_number = ?",
            (int(week_number),),
        ).fetchone()
        return str(row[0]) if row else None


def _ensure_matchup_champion_choices(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS matchup_champion_choices (
            week TEXT NOT NULL,
            fantasy_team_id TEXT NOT NULL,
            choice_type TEXT NOT NULL CHECK(choice_type IN ('pick', 'ban')),
            choice_number INTEGER NOT NULL CHECK(choice_number IN (1, 2)),
            role TEXT NOT NULL CHECK(role IN ('top', 'jg', 'mid', 'adc', 'sup')),
            champion_name TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(week, fantasy_team_id, choice_type, choice_number)
        )
    """)


def get_matchup_champion_choices(week: str) -> dict[str, dict[str, list[dict]]]:
    """Return shared pick/ban selections for every fantasy team in a week."""
    with connect() as db:
        _ensure_matchup_champion_choices(db)
        rows = db.execute("""
            SELECT fantasy_team_id, choice_type, choice_number, role, champion_name
            FROM matchup_champion_choices
            WHERE week = ?
            ORDER BY fantasy_team_id, choice_type, choice_number
        """, (str(week),)).fetchall()
        result = {}
        for row in rows:
            team_choices = result.setdefault(row["fantasy_team_id"], {"picks": [], "bans": []})
            key = "picks" if row["choice_type"] == "pick" else "bans"
            team_choices[key].append({"role": row["role"], "champion": row["champion_name"]})
        return result


def save_matchup_champion_choices(
    week: str, fantasy_team_id: str, picks: list[dict], bans: list[dict], match_start: str,
) -> None:
    """Save exactly two picks and bans, rejecting submissions after first match start."""
    if not str(week).strip() or not str(fantasy_team_id).strip():
        raise ValueError("The matchup week and fantasy team are required.")
    try:
        lock_time = datetime.fromisoformat(str(match_start).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("The first match time for this week is unavailable.") from exc
    if lock_time.tzinfo is None:
        lock_time = lock_time.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= lock_time:
        raise ValueError("Picks and bans are locked because the first match has started.")

    valid_roles = {"top", "jg", "mid", "adc", "sup"}
    rows = []
    for choice_type, selections in (("pick", picks), ("ban", bans)):
        if len(selections) != 2:
            raise ValueError(f"Choose exactly two champions for your {choice_type}s.")
        champion_keys = set()
        for index, choice in enumerate(selections, start=1):
            role = str(choice.get("role") or "").strip().lower()
            champion = str(choice.get("champion") or "").strip()
            champion_key = "".join(character for character in champion.casefold() if character.isalnum())
            if role not in valid_roles or not champion:
                raise ValueError("Each champion choice needs a valid role and champion.")
            if champion_key in champion_keys:
                raise ValueError(f"Choose two different champions for your {choice_type}s.")
            champion_keys.add(champion_key)
            rows.append((str(week), str(fantasy_team_id), choice_type, index, role, champion))

    with connect() as db:
        _ensure_matchup_champion_choices(db)
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "DELETE FROM matchup_champion_choices WHERE week = ? AND fantasy_team_id = ?",
            (str(week), str(fantasy_team_id)),
        )
        db.executemany("""
            INSERT INTO matchup_champion_choices(
                week, fantasy_team_id, choice_type, choice_number, role, champion_name
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, rows)


def get_live_match_cache(match_id: str) -> dict | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM live_match_cache WHERE match_id = ?", (str(match_id),)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result


def get_cached_live_matches() -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM live_match_cache ORDER BY updated_at DESC"
        ).fetchall()
        matches = []
        for row in rows:
            result = dict(row)
            result["payload"] = json.loads(result.pop("payload_json"))
            matches.append(result)
        return matches


def get_in_progress_match_ids(league_id: str = "") -> list[str]:
    with connect() as db:
        if league_id:
            rows = db.execute(
                "SELECT match_id FROM live_match_cache WHERE match_state = 'in_progress' AND league_id = ?",
                (str(league_id),),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT match_id FROM live_match_cache WHERE match_state = 'in_progress'"
            ).fetchall()
        return [str(row[0]) for row in rows]


def save_live_match(match_id: str, league_id: str, match_state: str,
                    payload: dict, updated_at: str) -> bool:
    """Persist a live match, refusing to modify a match already marked completed."""
    state = "completed" if str(match_state).casefold() == "completed" else "in_progress"
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT match_state FROM live_match_cache WHERE match_id = ?", (str(match_id),)
        ).fetchone()
        if existing and existing["match_state"] == "completed":
            return False
        completed_at = updated_at if state == "completed" else None
        db.execute("""
            INSERT INTO live_match_cache(match_id, league_id, match_state, payload_json, updated_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                league_id = excluded.league_id,
                match_state = excluded.match_state,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at,
                completed_at = CASE WHEN excluded.match_state = 'completed'
                                    THEN excluded.completed_at ELSE NULL END
        """, (str(match_id), str(league_id or ""), state,
              json.dumps(payload, ensure_ascii=False, default=str), updated_at, completed_at))
        return True
