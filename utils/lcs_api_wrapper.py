import requests
import datetime
import dateutil
import math
import json
import os
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from utils.fandom_images import find_player_images


class LoLEsportsAPIError(RuntimeError):
    """Raised when a LoL Esports API request fails or returns an unusable response."""


def _load_api_key():
    api_key = os.environ.get("LOLESPORTS_API_KEY", "").strip()
    if api_key:
        return api_key
    try:
        import streamlit as st
        api_key = str(st.secrets.get("lolesports_api_key", "")).strip()
        if api_key:
            return api_key
    except Exception:
        pass
    credentials_path = Path(__file__).resolve().parent.parent / "credentials.json"
    if credentials_path.exists():
        try:
            return str(json.loads(credentials_path.read_text(encoding="utf-8")).get("lolesportsapi_key", "")).strip()
        except (OSError, ValueError):
            return ""
    return ""


def _team_slugs(value):
    slugs = set()
    if isinstance(value, dict):
        # Standings responses are inconsistent about including team codes. A
        # team slug plus an ID is enough to distinguish team records from
        # stage/section slugs and is what getTeams expects.
        if value.get("slug") and (value.get("code") or value.get("id")):
            slugs.add(str(value["slug"]))
        for child in value.values():
            slugs.update(_team_slugs(child))
    elif isinstance(value, list):
        for child in value:
            slugs.update(_team_slugs(child))
    return slugs


def _canonical_role(raw_role):
    role = str(raw_role or "").strip().lower()
    aliases = {
        "top": "top",
        "jungle": "jg", "jungler": "jg", "jng": "jg", "jg": "jg",
        "mid": "mid", "middle": "mid",
        "adc": "adc", "bot": "adc", "bottom": "adc", "carry": "adc",
        "sup": "sup", "support": "sup", "utility": "sup",
    }
    return aliases.get(role, "flex")

def dict_lookup(dict_list, key, value):
    return list(filter(lambda x: x[key] == value, dict_list))

class LoLEsportsAPI:
    def __init__(self):
        self.API_KEY = _load_api_key()
        self.BASE_URL = 'https://esports-api.lolesports.com/persisted/gw'
        self.MATCH_BASE_URL = 'https://feed.lolesports.com/livestats/v1'
        self.headers = {'x-api-key': self.API_KEY}

    def _get_json(self, url, params=None):
        if not self.API_KEY:
            raise LoLEsportsAPIError(
                "Configure LOLESPORTS_API_KEY, Streamlit secret lolesports_api_key, or credentials.json."
            )
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f" (HTTP {status})" if status else ""
            raise LoLEsportsAPIError(f"LoL Esports request failed{detail}. Check the API key and try again.") from exc
        except ValueError as exc:
            raise LoLEsportsAPIError("LoL Esports returned an unreadable response.") from exc

    def _get_url_json(self, url, params=None):
        """Request a persisted or live-feed endpoint with shared error handling."""
        if not self.API_KEY:
            raise LoLEsportsAPIError(
                "Configure LOLESPORTS_API_KEY, Streamlit secret lolesports_api_key, or credentials.json."
            )
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=20)
            response.raise_for_status()
            try:
                return response.json()
            except requests.exceptions.JSONDecodeError:
                # Historical game IDs can have no frame at a requested time;
                # the feed uses an empty body for that case rather than JSON.
                if response.ok and not response.text.strip():
                    return {}
                raise
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f" (HTTP {status})" if status else ""
            raise LoLEsportsAPIError(f"LoL Esports request failed{detail}. Check the API key and try again.") from exc
        except ValueError as exc:
            raise LoLEsportsAPIError("LoL Esports returned an unreadable response.") from exc

    def get_leagues(self, hl='en-US'):
        URL = self.BASE_URL + '/getLeagues'
        params = {'hl': hl}
        resp = self._get_json(URL, params=params)
        data = resp.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('leagues'), list):
            raise LoLEsportsAPIError("LoL Esports did not return a league list.")
        return data['leagues']

    def get_regional_leagues(self, hl='en-US'):
        return self.get_leagues(hl=hl)

    def get_tournaments_for_league(self, league_id, hl='en-US'):
        URL = self.BASE_URL + '/getTournamentsForLeague'
        params = {'hl': hl, 'leagueId': league_id}
        resp = self._get_json(URL, params=params)
        return resp['data']

    def get_standings(self, tournament_id, hl='en-US'):
        URL = self.BASE_URL + '/getStandings'
        params = {'hl': hl, 'tournamentId': tournament_id}
        resp = self._get_json(URL, params=params)
        return resp['data']

    def get_live(self, hl='en-US'):
        URL = self.BASE_URL + '/getLive'
        params = {'hl': hl}
        return self._get_json(URL, params=params)

    def get_completed_events(self, tournament_id, hl='en-US'):
        URL = self.BASE_URL + '/getCompletedEvents'
        params = {'hl': hl, 'tournamentId': tournament_id}
        return self._get_json(URL, params=params)

    def get_event_details(self, match_id, hl='en-US'):
        URL = self.BASE_URL + '/getEventDetails'
        params = {'hl': hl, 'id': match_id}
        return self._get_json(URL, params=params)

    def get_games(self, match_id, hl='en-US'):
        URL = self.BASE_URL + '/getGames'
        params = {'hl': hl, 'id': match_id}
        return self._get_json(URL, params=params)

    def get_teams(self,  team_slug=None, hl='en-US'):
        URL = self.BASE_URL + '/getTeams'
        params = {'hl': hl}
        if team_slug:
            params['id'] = team_slug
        return self._get_json(URL, params=params)

    def get_players_for_league(self, league, hl='en-US'):
        """Return current-season orgs and player rosters for one regional league.

        The API exposes team rosters by team slug, so this follows the league's
        latest tournament year through standings, then requests those teams'
        rosters in one getTeams call.
        """
        league_id = str(league.get('id', ''))
        if not league_id:
            raise ValueError("The selected league has no LoL Esports league ID.")
        league_name = str(league.get('name', ''))
        region = str(league.get('region', ''))
        tournament_data = self.get_tournaments_for_league(league_id, hl=hl)
        groups = tournament_data.get('leagues', [])
        tournaments = [item for group in groups for item in group.get('tournaments', [])]
        if not tournaments:
            raise ValueError("No tournaments were returned for this league.")

        dated = [item for item in tournaments if item.get('startDate')]
        if dated:
            latest_year = max(str(item['startDate'])[:4] for item in dated)
            tournaments = [item for item in dated if str(item['startDate'])[:4] == latest_year]

        team_slugs = set()
        for tournament in tournaments:
            tournament_id = str(tournament.get('id', ''))
            if tournament_id:
                team_slugs.update(_team_slugs(self.get_standings(tournament_id, hl=hl)))
        if not team_slugs:
            raise ValueError("No teams were found in this league's latest tournament year.")

        requested_slugs = sorted(team_slugs)
        response = self.get_teams(requested_slugs, hl=hl)
        teams = response.get('data', {}).get('teams', [])

        # Some API responses return only one roster for a repeated `id` query
        # even when multiple slugs were requested. Fetch any omitted teams one
        # at a time so the draft pool still contains the whole league.
        returned_slugs = {str(team.get('slug') or '') for team in teams}
        missing_slugs = [slug for slug in requested_slugs if slug not in returned_slugs]
        if missing_slugs:
            teams_by_key = {
                str(team.get('slug') or team.get('id') or team.get('name') or ''): team
                for team in teams
            }
            for slug in missing_slugs:
                individual = self.get_teams(slug, hl=hl)
                for team in individual.get('data', {}).get('teams', []):
                    key = str(team.get('slug') or team.get('id') or team.get('name') or slug)
                    teams_by_key[key] = team
            teams = list(teams_by_key.values())

        pool = {}
        for team in teams:
            team_name = str(team.get('name', 'Unknown team'))
            team_code = str(team.get('code', '')).strip()
            team_id = str(team.get('id') or team.get('slug') or team_name)
            org_id = f"team:{team_id}"
            pool[org_id] = {
                'player_id': org_id,
                'player_name': team_name,
                'role': 'team',
                'team_name': team_name,
                'team_code': team_code,
                'league_name': league_name,
                'region': region,
                'image_url': str(team.get('image') or team.get('alternativeImage') or '').strip(),
            }
            for player in team.get('players', []):
                player_id = str(player.get('id', '')).strip()
                player_name = str(player.get('summonerName') or player.get('name') or '').strip()
                if not player_id or not player_name:
                    continue
                pool[player_id] = {
                    'player_id': player_id,
                    'player_name': player_name,
                    'role': _canonical_role(player.get('role')),
                    'team_name': team_name,
                    'team_code': team_code,
                    'league_name': league_name,
                    'region': region,
                    'image_url': str(player.get('image') or player.get('photoUrl') or '').strip(),
                }
        players_without_images = [
            player for player in pool.values()
            if player['role'] != 'team' and not player['image_url']
        ]
        images = find_player_images(
            [player['player_name'] for player in players_without_images],
            {
                player['player_name']: [player['team_name'], player.get('team_code', '')]
                for player in players_without_images
            },
        )
        for player in players_without_images:
            player['image_url'] = images.get(player['player_name'], '')
        if not pool:
            raise ValueError("No team or player roster records were returned for this league.")
        return list(pool.values())

    def get_schedule(self, league_id, page_token=None, hl='en-US'):
        URL = self.BASE_URL + '/getSchedule'
        params = {'hl': hl, 'leagueId': league_id, 'pageToken': page_token}
        resp = self._get_json(URL, params=params)
        return resp['data']

    def get_window(self, game_id, start_time=None, hl='en-US'):
        URL = self.MATCH_BASE_URL + '/window' + '/' + str(game_id)
        params = {'hl': hl, 'startingTime': start_time}
        return self._get_url_json(URL, params=params)

    def get_details(self, game_id, start_time=None, hl='en-US'):
        URL = self.MATCH_BASE_URL + '/details' + '/' + str(game_id)
        params = {'hl': hl, 'startingTime': start_time}
        return self._get_url_json(URL, params=params)

    def get_game_id_from_match_id(self, match_id):
        """
        Returns game_id for a given match_id
        """
        return self.get_event_details(match_id)['data']['event']['match']['games'][0]['id']

    def get_latest_frame_data(self, game_id):
        """
        Returns dict of game metadata, dict of game stats for latest time available
        """
        now = datetime.datetime.now()
        latest_time = now.replace(second=math.floor(now.second / 10) * 10, microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')
        window = self.get_window(game_id, start_time=latest_time)
        frame_times = [dateutil.parser.parse(x['rfc460Timestamp']) for x in window['frames']]
        latest_frame_index = frame_times.index(max(frame_times))
        game_metadata = window['gameMetadata']
        # add match and game id to the metadata dict
        game_metadata['esportsGameId'] = window['esportsGameId']
        game_metadata['esportsMatchId'] = window['esportsMatchId']
        return window['gameMetadata'], dict_lookup(window['frames'], 'rfc460Timestamp', window['frames'][latest_frame_index]['rfc460Timestamp'])[0]

    #
    # def get_game_metadata(self, game_id):
    #     """
    #     Returns dict of game metadata
    #     """
    #     now = datetime.datetime.now()
    #     latest_time = now.replace(second=math.floor(now.second / 10) * 10, microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')
    #     window = self.get_window(game_id, start_time=latest_time)
    #     return window['gameMetadata']

    def get_player_stats(self, game_id, player_id, player_role):
        """
        Returns player stats dict for latest frame for a specified game
        """
        game_metadata, frame_data = self.get_latest_frame_data(game_id)

        if player_role == 'team':
            if game_metadata['blueTeamMetadata']['esportsTeamId'] == player_id:
                part_team = 'blueTeam'
            elif game_metadata['redTeamMetadata']['esportsTeamId'] == player_id:
                part_team = 'redTeam'
            player_stats = frame_data[part_team]
            player_stats = {key: val for key, val in player_stats.items() if key != 'participants'}
        else:
            player_dict = dict_lookup(game_metadata['blueTeamMetadata']['participantMetadata'] + game_metadata['redTeamMetadata']['participantMetadata'],
                                      key='esportsPlayerId', value=player_id)[0]
            if player_dict['participantId'] >= 6:
                part_team = 'redTeam'
            else:
                part_team = 'blueTeam'

            player_stats = dict_lookup(frame_data[part_team]['participants'], key='participantId',
                                       value=player_dict['participantId'])[0]
            player_stats['championId'] = player_dict['championId']
        game_status = frame_data['gameState']
        return game_metadata, player_stats, game_status

    def get_team_stats(self, game_id, team_id):
        """
        Returns team stats dict for latest frame for a specified game
        """
        game_metadata, frame_data = self.get_latest_frame_data(game_id)
        if game_metadata['blueTeamMetadata']['esportsTeamId'] == team_id:
            team_side = 'blueTeam'
        elif game_metadata['redTeamMetadata']['esportsTeamId'] == team_id:
            team_side = 'redTeam'
        team_stats = frame_data[team_side]
        return team_stats

    def get_lcs_summer_2026_stats(self, progress_callback=None, hl='en-US', event_limit=None):
        """Pull and aggregate regular-season LCS Summer 2026 game stats."""
        return self.get_lcs_split_2026_stats(
            'lcs_split_3_2026', 'LCS Summer 2026',
            progress_callback=progress_callback, hl=hl, event_limit=event_limit,
        )

    def get_lcs_spring_2026_stats(self, progress_callback=None, hl='en-US', event_limit=None):
        """Pull and aggregate regular-season LCS Spring 2026 game stats."""
        return self.get_lcs_split_2026_stats(
            'lcs_split_2_2026', 'LCS Spring 2026',
            progress_callback=progress_callback, hl=hl, event_limit=event_limit,
        )

    def get_lcs_split_2026_stats(self, tournament_slug, season_label,
                                 progress_callback=None, hl='en-US', event_limit=None):
        """Pull and aggregate regular-season LCS game stats for one 2026 split.

        Tournament events come from the persisted gateway. For each completed
        game, its game number guides timestamp queries to the live-stats archive.
        The final frame from the API response is aggregated by match block.
        """
        leagues = self.get_regional_leagues(hl=hl)
        league = next((item for item in leagues if str(item.get('slug', '')).lower() == 'lcs'), None)
        if not league:
            raise LoLEsportsAPIError("The configured API did not return the LCS league.")

        tournament_data = self.get_tournaments_for_league(league['id'], hl=hl)
        tournaments = [
            tournament
            for group in tournament_data.get('leagues', [])
            for tournament in group.get('tournaments', [])
        ]
        tournament = next((item for item in tournaments
                           if str(item.get('slug', '')).lower() == tournament_slug.lower()), None)
        if not tournament:
            raise LoLEsportsAPIError(f"The configured API did not return the {season_label} tournament.")

        completed = self.get_completed_events(tournament['id'], hl=hl)
        events = completed.get('data', {}).get('schedule', {}).get('events', [])
        # Keep this demo snapshot to the regular-season match weeks. Blocks
        # named Playoffs or Finals are deliberately excluded.
        events = [
            event for event in events
            if re.match(r'^Week\s+\d+\b', str(event.get('blockName', '')).strip(), flags=re.IGNORECASE)
            and (event.get('state') == 'completed' or event.get('games'))
        ]
        if event_limit:
            events = events[:int(event_limit)]
        if not events:
            raise LoLEsportsAPIError("No completed LCS Summer 2026 events were returned.")

        player_totals = {}
        team_totals = {}
        week_totals = {}
        games_loaded = 0
        games_skipped = []
        games_skipped_reasons = {}
        games_unplayed = 0
        games_expected = 0
        for event_index, event in enumerate(events, start=1):
            block = str(event.get('blockName') or 'Summer 2026')
            week = week_totals.setdefault(block, {
                'name': block, 'start_time': event.get('startTime'), 'games': 0,
                'players': {}, 'teams': {}, 'game_details': [],
            })
            try:
                match_time = datetime.fromisoformat(str(event.get('startTime', '')).replace('Z', '+00:00'))
            except ValueError:
                match_time = datetime(2026, 7, 25, tzinfo=timezone.utc)
            if match_time.tzinfo is None:
                match_time = match_time.replace(tzinfo=timezone.utc)
            match = event.get('match') or {}
            games = event.get('games') or []
            if match.get('id'):
                detail = self.get_event_details(match['id'], hl=hl)
                detailed_match = detail.get('data', {}).get('event', {}).get('match', {})
                if detailed_match:
                    match = detailed_match
                    games = detailed_match.get('games', games)
            if not games:
                games_skipped.append(str(match.get('id', event_index)))
                continue

            for game in games:
                game_id = str(game.get('id', '')).strip()
                if game.get('state') == 'unneeded':
                    games_unplayed += 1
                    continue
                if game.get('state') != 'completed':
                    continue
                games_expected += 1
                window = {}
                window_frames = []
                archived_at = None
                # Series games start roughly 45 minutes apart. Search around
                # the expected end for this game so we hit the feed's short
                # postgame window instead of querying hours after the match.
                game_number = int(game.get('number') or 1)
                first_offset = 15 + 45 * (game_number - 1)
                points = [match_time + timedelta(minutes=first_offset + 15 * step) for step in range(7)]
                for timestamp in points:
                    point = timestamp.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
                    try:
                        candidate = self.get_window(game_id, start_time=point, hl=hl)
                    except LoLEsportsAPIError as exc:
                        if '(HTTP 400)' in str(exc):
                            continue
                        raise
                    candidate_frames = candidate.get('frames', [])
                    if not candidate_frames:
                        continue
                    candidate_last = candidate_frames[-1]
                    window, window_frames = candidate, candidate_frames
                    if candidate_last.get('gameState') == 'finished':
                        archived_at = point
                        break
                if not archived_at:
                    games_skipped.append(game_id)
                    games_skipped_reasons[game_id] = 'no_final_window'
                    continue
                detail_frames = self.get_details(game_id, start_time=archived_at, hl=hl).get('frames', [])
                window_frames = window.get('frames', [])
                if not detail_frames or not window_frames:
                    games_skipped.append(game_id)
                    games_skipped_reasons[game_id] = 'no_player_detail_frames'
                    continue
                final_details = detail_frames[-1]
                final_window = window_frames[-1]
                game_metadata = window.get('gameMetadata', {})
                names_by_code = {
                    str(item.get('code', '')).casefold(): str(item.get('name', ''))
                    for item in match.get('teams', []) if item.get('code') and item.get('name')
                }
                team_info_by_id = {
                    str(item.get('id') or ''): item
                    for item in match.get('teams', []) if item.get('id')
                }
                participant_lookup = {}
                for side in ('blueTeamMetadata', 'redTeamMetadata'):
                    metadata = game_metadata.get(side, {})
                    team_id = str(metadata.get('esportsTeamId', ''))
                    for entry in metadata.get('participantMetadata', []):
                        summoner_name = str(entry.get('summonerName') or 'Unknown player')
                        code = summoner_name.split(' ', 1)[0].casefold()
                        team_name = names_by_code.get(code, code.upper() if code else 'Unknown team')
                        participant_lookup[int(entry.get('participantId', 0))] = {
                            'player_id': str(entry.get('esportsPlayerId') or ''),
                            'player_name': summoner_name.split(' ', 1)[-1],
                            'role': _canonical_role(entry.get('role')),
                            'team_id': team_id, 'team_name': team_name,
                            'champion': str(entry.get('championId') or entry.get('championName') or ''),
                        }
                if len(participant_lookup) < 10:
                    games_skipped.append(game_id)
                    games_skipped_reasons[game_id] = 'incomplete_participant_metadata'
                    continue

                game_record = {
                    'match_id': str(match.get('id') or ''),
                    'game_id': game_id,
                    'number': int(game.get('number') or 1),
                    'team_ids': [str(team.get('id') or '') for team in match.get('teams', []) if team.get('id')],
                    'players': {},
                    'teams': {},
                }
                for participant in final_details.get('participants', []):
                    participant_id = int(participant.get('participantId', 0))
                    participant_identity = participant_lookup.get(participant_id)
                    if not participant_identity or not participant_identity['player_id']:
                        continue
                    identity = {key: value for key, value in participant_identity.items() if key != 'champion'}
                    player_id = identity['player_id']
                    totals = player_totals.setdefault(player_id, {
                        **identity, 'games': 0, 'kills': 0, 'deaths': 0, 'assists': 0,
                        'creepScore': 0, 'totalGoldEarned': 0, 'wardsPlaced': 0,
                        'wardsDestroyed': 0, 'weeks': {},
                    })
                    block_stats = week['players'].setdefault(player_id, {
                        **identity, 'games': 0, 'kills': 0, 'deaths': 0, 'assists': 0,
                        'creepScore': 0, 'totalGoldEarned': 0, 'wardsPlaced': 0,
                        'wardsDestroyed': 0,
                    })
                    game_player = game_record['players'].setdefault(player_id, {**identity, 'games': 1})
                    game_player['champion'] = participant_identity.get('champion', '')
                    for key in ('kills', 'deaths', 'assists', 'creepScore', 'totalGoldEarned', 'wardsPlaced', 'wardsDestroyed'):
                        value = int(participant.get(key) or 0)
                        totals[key] += value
                        block_stats[key] += value
                        game_player[key] = value
                    totals['games'] += 1
                    block_stats['games'] += 1
                    totals['weeks'][block] = block_stats

                for side, metadata_side in (('blueTeam', 'blueTeamMetadata'), ('redTeam', 'redTeamMetadata')):
                    side_stats = final_window.get(side, {})
                    dragon_types = list(side_stats.get('dragons') or [])
                    team_id = str(game_metadata.get(metadata_side, {}).get('esportsTeamId', ''))
                    if not team_id:
                        continue
                    objectives = {
                        'towers': int(side_stats.get('towers') or 0),
                        'barons': int(side_stats.get('barons') or 0),
                        'dragon_count': len(dragon_types),
                        'dragon_souls': int(len(dragon_types) >= 4),
                        'totalKills': int(side_stats.get('totalKills') or 0),
                    }
                    game_record['teams'][team_id] = {
                        'team_id': team_id, **objectives, 'dragon_types': dragon_types, 'games': 1,
                    }
                    team_info = team_info_by_id.get(team_id, {})
                    image_url = str(team_info.get('image') or team_info.get('alternativeImage') or '').strip()
                    for container in (team_totals, week['teams']):
                        stats = container.setdefault(team_id, {
                            'team_id': team_id,
                            'team_name': next((item['team_name'] for item in participant_lookup.values()
                                               if item['team_id'] == team_id), 'Unknown team'),
                            'image_url': image_url,
                            'games': 0, 'towers': 0, 'barons': 0,
                            'dragon_count': 0, 'dragon_souls': 0, 'totalKills': 0,
                            'dragon_type_counts': {},
                        })
                        if image_url and not stats.get('image_url'):
                            stats['image_url'] = image_url
                        stats['games'] += 1
                        for key, value in objectives.items():
                            stats[key] += value
                        for dragon_type in dragon_types:
                            stats['dragon_type_counts'][dragon_type] = (
                                stats['dragon_type_counts'].get(dragon_type, 0) + 1
                            )
                week['game_details'].append(game_record)
                week['games'] += 1
                games_loaded += 1

            if progress_callback:
                progress_callback(event_index, len(events), event.get('blockName', ''))

        if not player_totals:
            raise LoLEsportsAPIError("The Summer 2026 tournament was found, but no archived player stats were returned.")
        return {
            'season': season_label, 'league': league, 'tournament': tournament,
            'weeks': list(week_totals.values()), 'players': list(player_totals.values()),
            'teams': list(team_totals.values()), 'games_loaded': games_loaded,
            'games_expected': games_expected, 'games_unplayed': games_unplayed,
            'games_skipped': games_skipped, 'games_skipped_reasons': games_skipped_reasons,
            'pulled_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        }
