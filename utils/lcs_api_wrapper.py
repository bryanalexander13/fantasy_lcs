import requests
import datetime
import dateutil
import math

def dict_lookup(dict_list, key, value):
    return list(filter(lambda x: x[key] == value, dict_list))

class LoLEsportsAPI:
    def __init__(self):
        self.API_KEY = '0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z'
        self.BASE_URL = 'https://esports-api.lolesports.com/persisted/gw'
        self.MATCH_BASE_URL = 'https://feed.lolesports.com/livestats/v1'
        self.headers = {'x-api-key': self.API_KEY}

    def get_leagues(self, hl='en-US'):
        URL = self.BASE_URL + '/getLeagues'
        params = {'hl': hl}
        resp = requests.get(URL, params=params, headers=self.headers)
        return resp.json()['data']['leagues']

    def get_tournaments_for_league(self, league_id, hl='en-US'):
        URL = self.BASE_URL + '/getTournamentsForLeague'
        params = {'hl': hl, 'leagueId': league_id}
        resp = requests.get(URL, params=params, headers=self.headers)
        return resp.json()['data']

    def get_standings(self, tournament_id, hl='en-US'):
        URL = self.BASE_URL + '/getStandings'
        params = {'hl': hl, 'tournamentId': tournament_id}
        resp = requests.get(URL, params=params, headers=self.headers)
        return resp.json()['data']

    def get_live(self, hl='en-US'):
        URL = self.BASE_URL + '/getLive'
        params = {'hl': hl}
        resp = requests.get(URL, params=params, headers=self.headers)
        return resp.json()

    def get_completed_events(self, tournament_id, hl='en-US'):
        URL = self.BASE_URL + '/getCompletedEvents'
        params = {'hl': hl, 'tournamentId': tournament_id}
        resp = requests.get(URL, params=params, headers=self.headers)
        return resp.json()

    def get_event_details(self, match_id, hl='en-US'):
        URL = self.BASE_URL + '/getEventDetails'
        params = {'hl': hl, 'id': match_id}
        resp = requests.get(URL, params=params, headers=self.headers)
        return resp.json()

    def get_games(self, match_id, hl='en-US'):
        URL = self.BASE_URL + '/getGames'
        params = {'hl': hl, 'id': match_id}
        resp = requests.get(URL, params=params, headers=self.headers)
        return resp.json()

    def get_teams(self,  team_slug=None, hl='en-US'):
        URL = self.BASE_URL + '/getTeams'
        params = {'hl': hl, 'id': team_slug}
        resp = requests.get(URL, params=params, headers=self.headers)
        return resp.json()

    def get_schedule(self, league_id, page_token=None, hl='en-US'):
        URL = self.BASE_URL + '/getSchedule'
        params = {'hl': hl, 'leagueId': league_id, 'pageToken': page_token}
        resp = requests.get(URL, params=params, headers=self.headers)
        return resp.json()['data']

    def get_window(self, game_id, start_time=None, hl='en-US'):
        URL = self.MATCH_BASE_URL + '/window' + '/' + str(game_id)
        params = {'hl': hl, 'startingTime': start_time}
        resp = requests.get(URL, params=params, headers=self.headers)
        return resp.json()

    def get_details(self, game_id, start_time=None, hl='en-US'):
        URL = self.MATCH_BASE_URL + '/details' + '/' + str(game_id)
        params = {'hl': hl, 'startingTime': start_time}
        resp = requests.get(URL, params=params, headers=self.headers)
        return resp.json()

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
