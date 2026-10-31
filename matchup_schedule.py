"""Create a randomized round-robin fantasy matchup schedule."""

import random


DEFAULT_SCHEDULE_WEEKS = 6
FEATURED_DRAGON_TYPES = ("Cloud", "Chemtech", "Hextech", "Infernal", "Mountain", "Ocean")


def create_weekly_dragon_bonuses(db, week_numbers, rng=None):
    """Assign a random non-Elder featured dragon once per scheduled week."""
    chooser = rng or random.SystemRandom()
    requested_weeks = sorted({int(week) for week in week_numbers})
    existing_weeks = {
        int(row[0]) for row in db.execute(
            "SELECT week_number FROM weekly_dragon_bonus WHERE week_number IN ({})".format(
                ",".join("?" for _ in requested_weeks)
            ), requested_weeks,
        )
    } if requested_weeks else set()
    assignments = []
    for week_number in requested_weeks:
        if week_number in existing_weeks:
            continue
        dragon_type = chooser.choice(FEATURED_DRAGON_TYPES)
        assignments.append((week_number, dragon_type))
    if assignments:
        db.executemany("""
            INSERT OR IGNORE INTO weekly_dragon_bonus(week_number, dragon_type)
            VALUES (?, ?)
        """, assignments)
    return len(assignments)


def create_random_schedule(db, team_user_ids, minimum_weeks=DEFAULT_SCHEDULE_WEEKS):
    """Create a season schedule once, delaying every rematch until a full cycle.

    Odd-sized leagues receive one bye each round. The schedule lasts at least
    six weeks and is extended when needed so every team faces every other team
    before any pairing repeats.
    """
    existing_weeks = [int(row[0]) for row in db.execute(
        "SELECT DISTINCT week_number FROM fantasy_matchup_schedule ORDER BY week_number"
    )]
    if existing_weeks:
        create_weekly_dragon_bonuses(db, existing_weeks)
        return {"created": False, "weeks": len(existing_weeks), "matchups": 0}

    teams = [int(user_id) for user_id in team_user_ids]
    if len(teams) < 2:
        return {"created": False, "weeks": 0, "matchups": 0}

    rng = random.SystemRandom()
    rng.shuffle(teams)
    rotation = list(teams)
    if len(rotation) % 2:
        rotation.append(None)

    round_count = len(rotation) - 1
    rounds = []
    for _ in range(round_count):
        pairings = []
        for index in range(len(rotation) // 2):
            first, second = rotation[index], rotation[-1 - index]
            if first is None:
                first, second = second, first
            elif second is not None and rng.choice((True, False)):
                first, second = second, first
            pairings.append((first, second))
        rng.shuffle(pairings)
        rounds.append(pairings)
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]

    schedule_weeks = max(int(minimum_weeks), round_count)
    rows = []
    week_number = 1
    while week_number <= schedule_weeks:
        cycle = [list(pairings) for pairings in rounds]
        rng.shuffle(cycle)
        for pairings in cycle:
            if week_number > schedule_weeks:
                break
            for matchup_number, (team_1, team_2) in enumerate(pairings, start=1):
                rows.append((week_number, matchup_number, team_1, team_2))
            week_number += 1

    db.executemany("""
        INSERT INTO fantasy_matchup_schedule(
            week_number, matchup_number, team_1_user_id, team_2_user_id
        ) VALUES (?, ?, ?, ?)
    """, rows)
    create_weekly_dragon_bonuses(db, range(1, schedule_weeks + 1), rng)
    return {"created": True, "weeks": schedule_weeks, "matchups": len(rows)}
