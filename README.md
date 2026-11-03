# Fantasy LCS: next iteration

This keeps Streamlit and the existing JSON schedule while adding per-user accounts, a snake draft, and locked rosters. Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes in SQLite. The database is created at data/fantasy_lcs.sqlite3; set FANTASY_DB_PATH to use a different persistent location.

## Run locally

1. Use Python 3.10 or newer.
2. Install dependencies: python -m pip install -r requirements.txt.
3. Run streamlit run app.py from this folder.
4. Create league accounts, then use Draft, Roster, Matchups, and Players from the sidebar.

To preview six sample fantasy teams with LCS Summer 2026 stats, run:

```bash
streamlit run app.py -- --demo
```

Demo mode uses `utils/lcs_api_wrapper.py` to pull actual LCS Summer 2026 regular-season completed-game player and team statistics. Playoff and Finals blocks are excluded. For each LCS team/role, the player with the most regular-season games is treated as the first-string primary, and same-role substitute stats are credited to that primary. Matchup box scores list each completed game in a best-of-three series, omit Game 3 for a 2-0, and score player/org fantasy points as averages across games played. It then creates reproducible sample fantasy rosters and matchups. The downloaded snapshot is saved to `sample_data/lcs_summer_2026.json`; use **Refresh data from API** on the Matchups page to update it. Demo mode does not initialize or modify the regular league database. Use **Roster** and **Matchups** in the sidebar for the sample views; **Draft** shows a preview notice.

The **Players** page lists LCS Summer 2026 regular-season totals and cumulative fantasy points. The **Past Stats** page lists the previous LCS Spring 2026 split. Both pages support search, role, and team filters, exclude playoffs, and are available for LCS leagues; other regional leagues need their own split data imports.

## Draft workflow

The first registered account is the commissioner; later accounts are team owners. Before starting the draft, the commissioner can set its local date and time, load a regional league, import its team and player rosters from the LoL Esports API, or upload a complete player pool using player_pool_template.csv. The API import uses the league's newest tournament year and includes orgs plus the rosters returned for its teams. The supported roles are team, top, jg, mid, adc, sup, and flex. The draft order includes every account registered at that point.

The commissioner saves the order and starts the draft. Picks advance automatically in snake order: the order reverses on every other round. Each owner has 45 seconds per pick. A background watcher advances expired turns even when nobody has the Draft page open. If time expires, the app auto-picks the highest-scoring available Spring 2026 player whose role is still open on that roster; the Team org slot uses the highest-scoring available org from Spring 2026. Each team drafts one org and one pick for each player role. A player or org can only be drafted once; the server checks the current turn and slot and the database enforces unique picks. Rosters become read-only as soon as the draft starts. Account registration closes at that point as well.

After the draft is complete, owners can propose one-for-one trades with another owner from the Roster page. Trades exchange players from the same roster slot. The recipient must accept the proposal, then the commissioner must approve it before the roster picks are swapped. The commissioner reviews proposals on the Commissioner page. All trade actions are checked against current roster ownership in the database.

On the Commissioner page, **Refresh current split data** pulls the LCS Summer 2026 regular-season games through the API wrapper. **Refresh points and matchup records** scores the saved fantasy schedule with the current `scoring.json`, drafted rosters, featured dragon bonuses, and champion pick/ban multipliers, then saves matchup scores and cumulative wins, losses, and points. Run the point refresh again after a scoring change or data refresh. The League leaderboard, Matchups page, and My Matchup page use the saved results.

The shared API wrapper reads LOLESPORTS_API_KEY from the environment, lolesports_api_key from Streamlit secrets, or lolesportsapi_key from the ignored local credentials.json file. The CSV option does not require an API key. The commissioner must make sure the imported CSV contains the complete player pool for the chosen league.

Login offers a 30-day “Keep me signed in” option. The app stores only a hash of each random remember-me token in SQLite, and revokes that token on logout or account removal. The browser cookie is marked Secure when the app URL uses HTTPS and uses SameSite=Strict. Because the Streamlit cookie component writes from the browser, the cookie cannot be marked HttpOnly; keep the app on HTTPS and only use trusted app content.

Before the draft starts, account creation is open to people who can reach the app. Use a private network or add an invitation flow before public deployment. Public deployment should use HTTPS and persistent storage for the SQLite database. Do not commit credentials or the database.

The app reads schedule.json and teams_test.json once to seed the static matchup list. It does not load legacy pickle files.

Both the draft importer and live matchup panel use utils/lcs_api_wrapper.py, which loads the API key when a client is created.

## Live match updates

The Matchups page checks the LoL Esports live schedule every 30 seconds while it is open, then refreshes match details and current game feeds for tracked in-progress matches. Current match data is cached in the SQLite database. When the API reports a match as completed (or its series result reaches the best-of win threshold), the match is stored as final; later refreshes skip its match-detail and game-feed API calls. The page resumes refreshes when opened again, so this is not a background worker that runs while the app is closed. Live updates require a configured API key and a persistent database location if the app is deployed.
