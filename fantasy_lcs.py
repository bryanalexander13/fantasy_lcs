import pandas
import requests
import json
import datetime
import dateutil
import _pickle as cPickle
from pathlib import Path
import random
import uuid
from utils.lcs_api_wrapper import LoLEsportsAPI, dict_lookup

class Team:
    def __init__(self, id, owner, roster, team_name, wins=0, losses=0, draws=0):
        self.id = id
        self.owner = owner
        self.team_name = team_name
        self.roster = roster
        self.player_types = []
        self.wins = wins
        self.losses = losses
        self.draws = draws
        self.init_players()

        self.score_dict = {}
        # self.team_id = roster['team']
        # self.top_id = roster['top']
        # self.jg_id = roster['jg']
        # self.mid_id = roster['mid']
        # self.adc_id = roster['adc']
        # self.sup_id = roster['sup']

    def __repr__(self):
        return f"{self.team_name}"

    @classmethod
    def fromTeamDict(cls, dict):
        return cls(dict['id'], dict['owner'], dict['roster'], dict['name'])

    def init_players(self):
        for player_type in self.roster.keys():
            setattr(self, player_type, Player.load(self.roster[player_type], player_type))
            self.player_types.append(player_type)

    # def get_roster(self, week):
    #     if self.roster.get(week) is None:
    #         self.roster[week] = self.roster['current']
    #     return self.roster.get(week)

    def update_player_scores(self, api_session, week, scoring_dict):
        for player_type in self.player_types:
            getattr(self, player_type).get_player_stats_api(api_session, week, player_type)
            getattr(self, player_type).update_player_score_week(week, scoring_dict)

    def get_total_score(self, week):
        total_score = 0
        for player_type in self.player_types:
            total_score += getattr(self, player_type).player_score_week[week]
        return total_score

    def check_team_game_status(self, week):
        return all([getattr(self, player_type).get_player_game_status(week) for player_type in self.player_types])

    def add_win(self):
        self.wins += 1

    def add_loss(self):
        self.losses += 1

    def add_draw(self):
        self.draws += 1

    def set_score(self, week, score):
        self.score_dict.update({week: score})

    def save(self):
        return

    def load(self):
        return

class Player:
    def __init__(self, id, player_type, player_dict=None):
        self.id = id
        self.player_type = player_type
        self.player_stats = {}
        self.player_score = {}
        self.player_score_week = {}
        self.player_games = {}
        self.game_status = {}

        if player_dict is not None:
            self.player_name = player_dict['summonerName']
            self.player_type = player_dict['role']
            self.player_team = player_dict['esportsTeamId']
        else:
            self.player_name = None
            self.player_team = None

    def __repr__(self):
        return f"""
        {self.id}
        {self.player_type}
        {self.player_name}
        """

    def update_name(self, match_metadata):
        if self.player_name is None:
            player_name = dict_lookup(match_metadata['blueTeamMetadata']['participantMetadata'] + match_metadata['redTeamMetadata']['participantMetadata'], 'esportsPlayerId', self.id)[0]['summonerName']
            self.player_name = player_name

            self.player_team = player_team
        self.save()

    def update_player_stats(self, metadata, stats, week):
        # update name
        self.update_name(metadata)
        # define nested dictionary
        if week not in self.player_stats.keys():
            self.player_stats[week] = {}
        self.player_stats[week][metadata['esportsGameId']] = stats
        # Add correct dragons_count
        if self.player_type == 'team':
            self.player_stats[week][metadata['esportsGameId']]['dragon_count'] = len(self.player_stats[week][metadata['esportsGameId']]['dragons'])
        self.save()

    def get_player_stats_api(self, api_session, week, player_type):
            for game_id in [game for game in self.player_games[week] if self.game_status.get(game) != 'finshed']:
                game_metadata, player_stats, game_status = api_session.get_player_stats(game_id, self.id, self.player_type)
                self.update_player_stats(game_metadata, player_stats, week)
                self.game_status[game_id] = game_status

    def update_player_score_game(self, week, scoring_dict):
        if week not in self.player_score.keys():
            self.player_score[week] = {}
        for game_id in self.player_stats[week].keys():
            score = 0
            if self.player_type == 'team':
                score_type = 'team'
            else:
                score_type = 'player'
            for stat_name in scoring_dict[score_type].keys():
                score += self.player_stats[week][game_id][stat_name] * scoring_dict[score_type][stat_name]
            if score_type == 'player':
                bonus = scoring_dict.get('player_bonus', {})
                threshold = float(bonus.get('kill_or_assist_threshold', 10))
                stats = self.player_stats[week][game_id]
                if (float(stats.get('kills', 0) or 0) >= threshold
                        or float(stats.get('assists', 0) or 0) >= threshold):
                    score += float(bonus.get('points', 0))
            self.player_score[week][game_id] = round(score, 2)
        self.save()

    def update_player_score_week(self, week, scoring_dict):
        self.update_player_score_game(week, scoring_dict)
        score = 0
        for game_id in self.player_score[week].keys():
            score += self.player_score[week][game_id]
        self.player_score_week[week] = score
        self.save()

    def add_game_id(self, week, game_id):
        if self.player_games.get(week) is None:
            self.player_games[week] = [game_id]
        elif game_id in self.player_games[week]:
            pass
        else:
            self.player_games[week].append(game_id)

        self.save()

    def get_player_game_status(self, week):
        return all([self.game_status[game_id] for game_id in self.player_games[week]])

    # def get_game_ids_by_week(self, week):
    #     return self.player_score[week].keys()
    #
    # def get_score_game(self, week, game_id):
    #     return self.player_score[week][game_id]
    def get_player_stats(self, week, game_id):
        return self.player_stats[week][game_id]

    def get_player_statline(self, week, game_id):
        stat_dict = self.get_player_stats(self, week, game_id)
        return f"{stat_dict.get('kills')}/{stat_dict.get('deaths')}/{stat_dict.get('assists')}"

    def save(self):
        """save class as id"""
        path = 'player_data\\' + self.id +'.txt'
        with open(path, 'wb') as file:
            cPickle.dump(self, file)
        file.close()

    @classmethod
    def load(cls, id, player_type=None, player_dict=None):
        """try load self.name.txt"""
        try:
            path = 'player_data\\' + id +'.txt'
            with open(path, 'rb') as file:
                new_cls = cPickle.load(file)
            file.close()
            return new_cls
        except:
            return cls(id, player_type, player_dict)
    # def get_game_ids_by_week(self, api_session):
    #     self.game_week_dict = {}

    # def get_stats(self, game_id, api_session):
    #     if self.position == 'team':
    #         self.stats[game_id] = api_session.get_team_stats(game_id=game_id, team_id=self.id)
    #     else:
    #         self.stats[game_id] = api_session.get_player_stats(game_id=game_id, player_id=self.id)

    # def calc_game_score(self, scoring, game_id):
    #     score = 0
    #     for stat_name in self.stats[game_id]:
    #         if self.position == 'team':
    #             score =+ self.stats[game_id][stat_name] * scoring['team'][stat_name]
    #         else:
    #             score =+ self.stats[game_id][stat_name] * scoring['player'][stat_name]
    #     self.score[game_id] = score
    #
    # def calc_week_score(self, week):
    #     self.week_score[week] = sum([self.score[game_id] for game_id in self.game_week_dict[week]])


# #######################


class ScoreKeeper:
    def __init__(self, LEAGUE_ID='98767991299243165', TOURNAMENT_SLUG='lcs_spring_2023', scoring_path='scoring.json', teams_path='teams_test.json'):
        self.LEAGUE_ID = LEAGUE_ID
        self.TOURNAMENT_SLUG = TOURNAMENT_SLUG
        self.scoring_path = scoring_path
        self.teams_path = teams_path
        self.init_api()
        self.get_full_schedule(self.LEAGUE_ID, self.TOURNAMENT_SLUG)
        self.init_lcs_teams()
        self.get_weekly_match_dicts()
        self.load_scoring()
        self.load_teams()
        self.assign_games_to_players()
        self.load_schedule()
        self.init_matches()
        self.run()

    def get_full_schedule(self, LEAGUE_ID, TOURNAMENT_SLUG):
        """
        Pulls scheduled matches from API and stores list of dict in self.schedule
        Ex.
        {'startTime': '2023-01-26T22:00:00Z',
          'state': 'completed',
          'type': 'match',
          'blockName': 'Week 1',
          'league': {'name': 'LCS', 'slug': 'lcs'},
          'match': {'id': '109517090067719730',
           'flags': ['hasVod'],
           'teams': [{'name': '100 Thieves',
             'code': '100',
             'image': 'http://static.lolesports.com/teams/1631819887423_100t-2021-worlds.png',
             'result': {'outcome': 'loss', 'gameWins': 0},
             'record': {'wins': 12, 'losses': 8}},
            {'name': 'Cloud9',
             'code': 'C9',
             'image': 'http://static.lolesports.com/teams/1631820065346_cloud9-2021-worlds.png',
             'result': {'outcome': 'win', 'gameWins': 1},
             'record': {'wins': 15, 'losses': 4}}],
           'strategy': {'type': 'bestOf', 'count': 1}}}
        """
        all_tournament_dict = self.api_session.get_tournaments_for_league(LEAGUE_ID)['leagues'][0]['tournaments']
        tournament_dict = dict_lookup(all_tournament_dict, key='slug', value=self.TOURNAMENT_SLUG)[0]

        # get start and end dates
        split_start_date = dateutil.parser.parse(tournament_dict['startDate']).replace(tzinfo=dateutil.tz.tzutc())
        split_end_date = dateutil.parser.parse(tournament_dict['endDate']).replace(tzinfo=dateutil.tz.tzutc()) + datetime.timedelta(days=1)

        # Get Schedule
        schedule = []
        temp_schedule = self.api_session.get_schedule(LEAGUE_ID)['schedule']
        newer_schedule = temp_schedule['pages']['newer']
        older_schedule = temp_schedule['pages']['older']
        schedule += temp_schedule['events']
        # get new pages
        while newer_schedule is not None:
            temp_schedule = self.api_session.get_schedule(LEAGUE_ID, page_token=newer_schedule)['schedule']
            newer_schedule = temp_schedule['pages']['newer']
            schedule += temp_schedule['events']
        # get old pages
        old_temp_schedule = self.api_session.get_schedule(LEAGUE_ID, page_token=older_schedule)['schedule']
        while len(list(filter(lambda x: dateutil.parser.parse(x['startTime']) > split_start_date, old_temp_schedule['events']))) > 0:
            old_temp_schedule = self.api_session.get_schedule(LEAGUE_ID, page_token=older_schedule)['schedule']
            older_schedule = old_temp_schedule['pages']['older']
            schedule = old_temp_schedule['events'] + schedule

        # filter schedule for appropriate dates
        split_start_date = dateutil.parser.parse(tournament_dict['startDate']).replace(tzinfo=dateutil.tz.tzutc())
        # filter clean up
        schedule = list(filter(lambda x: dateutil.parser.parse(x['startTime']) > split_start_date, schedule))
        schedule = list(filter(lambda x: dateutil.parser.parse(x['startTime']) <= split_end_date, schedule))

        self.schedule = schedule

    def init_lcs_teams(self):
        """
        Pulls all teams associated with LCS with player data and stores in self.lcs_teams
        Stores dict of LCS team id in self.lcs_team_id
        """
        all_teams = self.api_session.get_teams(None)['data']['teams']

        filtered_all_teams = list(filter(lambda x: 'homeLeague' in x.keys(), all_teams))
        lcs_teams = list(filter(lambda x: x['homeLeague'] != None and x['homeLeague']['name'] == 'LCS', filtered_all_teams))
        self.lcs_teams = lcs_teams
        self.lcs_team_id = {team['id']: team['code'] for team in self.lcs_teams}

    def get_org_by_id(self, id):
        """
        Helper function the returns team org given id
        """
        return self.lcs_team_id.get(id)

    def get_weekly_match_dicts(self):
        # Get Matches by Week
        weeks_list = list(set([match['blockName'] for match in self.schedule]))
        # Filter Playoffs
        weeks_list = list(filter(lambda x: x.startswith('Week'), weeks_list))
        week_match_dict = {}
        for week in weeks_list:
            week_match_dict[week] = dict_lookup(self.schedule, 'blockName', week)
        self.week_match_dict = week_match_dict

        week_match_id_dict = {}
        for key in week_match_dict.keys():
            week_match_id_dict[key] = [match['match']['id'] for match in self.week_match_dict[key]]
        self.week_match_id_dict = week_match_id_dict

    def init_api(self):
        print("Initializing API Session...")
        self.api_session = LoLEsportsAPI()

    def load_teams(self):
        print("Loading Teams...")
        with open(self.teams_path, 'r') as f:
            data = json.loads(f.read())
        self.teams = []
        for key in data.keys():
            self.teams.append(Team(key, data[key]['owner'], data[key]['roster'], data[key]['name'], data[key]['wins'], data[key]['losses']))

    def find_team(self, team_id):
        """Returns team given id"""
        team_index = [team.id for team in self.teams].index(team_id)
        return self.teams[team_index]

    def load_scoring(self):
        """Loads scoring dict from file"""
        print("Loading Scoring...")
        with open(self.scoring_path, 'r') as f:
            data = json.loads(f.read())
        self.scoring = data

    def assign_games_to_players(self):
        """Loops through match ids and adds id to player object"""
        for key, value in self.week_match_id_dict.items():
            for match_id in value:
                game_id = self.api_session.get_game_id_from_match_id(match_id)
                game_metadata = self.api_session.get_window(game_id)['gameMetadata']
                for i in range(len(game_metadata['blueTeamMetadata']['participantMetadata'])):
                    game_metadata['blueTeamMetadata']['participantMetadata'][i]['esportsTeamId'] = game_metadata['blueTeamMetadata']['esportsTeamId']
                for i in range(len(game_metadata['redTeamMetadata']['participantMetadata'])):
                    game_metadata['redTeamMetadata']['participantMetadata'][i]['esportsTeamId'] = game_metadata['redTeamMetadata']['esportsTeamId']
                players_in_game = game_metadata['blueTeamMetadata']['participantMetadata'] + game_metadata['redTeamMetadata']['participantMetadata'] + [{'esportsTeamId': game_metadata['redTeamMetadata']['esportsTeamId'], 'esportsPlayerId': game_metadata['redTeamMetadata']['esportsTeamId'], 'summonerName':game_metadata['redTeamMetadata']['participantMetadata'][0]['summonerName'].split(' ')[0], 'role': 'team'}, {'esportsTeamId': game_metadata['blueTeamMetadata']['esportsTeamId'], 'esportsPlayerId': game_metadata['blueTeamMetadata']['esportsTeamId'], 'summonerName':game_metadata['blueTeamMetadata']['participantMetadata'][0]['summonerName'].split(' ')[0], 'role': 'team'}]
                #players_in_game = [x['esportsPlayerId'] for x in game_metadata['blueTeamMetadata']['participantMetadata']] + game_metadata['redTeamMetadata']['esportsTeamId'] + game_metadata['blueTeamMetadata']['esportsTeamId']
                for player in players_in_game:
                    Player.load(player['esportsPlayerId'], player_dict=player).add_game_id(key, game_id)

    def load_schedule(self):
        """Loads or generates schedule for fantasy teams"""
        try:
            with open('schedule.json', 'r') as f:
                data = json.loads(f.read())
            print("Loading Schedule...")
            self.match_schedule = data
        except:
            print('Generating Schedule...')
            reg_season_len = len(self.week_match_id_dict.keys()) - 2
            schedule_dict = {}
            team_list = [team.id for team in self.teams]
            random.shuffle(team_list)
            for i in range(1, reg_season_len+1):
                mid_length = int(len(team_list) / 2)
                l1 = team_list[:mid_length]
                l2 = team_list[mid_length:]
                l2.reverse()
                schedule_dict[f'Week {i}'] = {str(uuid.uuid4()): tuple([x,y]) for x, y in zip(l1, l2)}
                team_list.insert(1, team_list.pop())

            with open('schedule.json', 'w') as file:
                file.write(json.dumps(schedule_dict))
            file.close()

            self.match_schedule = schedule_dict


    def init_matches(self):
        matches_dict = {week: [] for week in self.match_schedule.keys()}
        for week, matches in self.match_schedule.items():
            for match_id, match_data in matches.items():
                matches_dict[week] = matches_dict[week] + [Match(match_id, self.find_team(match_data[0]), self.find_team(match_data[1]), week)]
        self.matches = matches_dict

    def get_teams_by_match(self, week, match_id):
        temp_match_schedule = self.week_match_dict[week]
        temp_match = list(filter(lambda x: x['match']['id'] == match_id, temp_match_schedule))[0]
        teams = {team['code']: team['result']['outcome'] for team in temp_match['teams']}
        return teams


    def run(self):
        for match in self.matches['Week 1'] + self.matches['Week 2']:
            match.run_match(self.api_session, self.scoring)
        # for team in self.teams:
        #     team.get_total_score(self.api_session, 'Week 1')
        return

class Match:
    def __init__(self, match_id, team1, team2, week, team1_score=0, team2_score=0):
        self.id = match_id
        self.team1 = team1
        self.team2 = team2
        self.team1_score = team1_score
        self.team2_score = team2_score
        self.week = week
        self.complete = False

    def __repr__(self):
        return f"{self.team1}: {self.team1_score} - {self.team2}: {self.team2_score}"

    def update_score(self, team_id, score):
        if team_id == self.team1.id:
            self.team1_score = score
        elif team_id == self.team2.id:
            self.team2_score = score

    def get_scores(self, api_session, scoring_dict):
        self.team1.update_player_scores(api_session, self.week, scoring_dict)
        self.team2.update_player_scores(api_session, self.week, scoring_dict)
        self.team1_score = self.team1.get_total_score(self.week)
        self.team2_score = self.team2.get_total_score(self.week)

    def check_game_status(self):
        if not self.complete and self.team1.check_team_game_status(self.week) and self.team2.check_team_game_status(self.week):
            self.complete = True
            # Maybe put in score keeper instead of match
            if self.team1_score > self.team2_score:
                self.team1.add_win()
                self.team2.add_loss()
            elif self.team2_score > self.team1_score:
                self.team1.add_loss()
                self.team2.add_loss()
            elif self.team2_score == self.team2_score:
                self.team1.add_draw()
                self.team2.add_draw()

    #def get_match_breakdown(self):
    def get_team_name(self, team_num):
        if team_num == 1:
            return self.team1.team_name
        elif team_num == 2:
            return self.team2.team_name

    def get_team_owner(self, team_num):
        if team_num == 1:
            return self.team1.owner
        elif team_num == 2:
            return self.team2.owner

    def get_player(self, team_num, pos):
        if team_num == 1:
            return getattr(self.team1, pos).player_name
        if team_num == 2:
            return getattr(self.team2, pos).player_name

    def get_player_score_dict(self, team_num, pos):
        if team_num == 1:
            return getattr(self.team1, pos).player_score[self.week]
        if team_num == 2:
            return getattr(self.team2, pos).player_score[self.week]

    def get_player_scoreline(self, team_num, pos, week, game_id):
        player_stats = getattr(getattr(self, f'team{team_num}'), player_role).get_player_stats(week, game_id)
        scoreline = f"{player_stats.get('kills')}/{player_stats.get('deaths')}/{player_stats.get('assists')}"
        return scoreline

    def return_scores(self):
        return {"team1": {"team": self.team1, "score": self.team1_score}, "team2": {"team": self.team2, "score": self.team2_score}}

    def run_match(self, api_session, scoring_dict):
        self.get_scores(api_session, scoring_dict)
        self.check_game_status()


# api_session = LoLEsportsAPI()
#api_session.get_player_stats('109517090067719731','102206337829139149', 'top')[0]
#
# api_session.get_teams(None)
# all_teams = api_session.get_teams(None)['data']['teams']
#
# filtered_all_teams = list(filter(lambda x: 'homeLeague' in x.keys(), all_teams))
# lcs_teams = list(filter(lambda x: x['homeLeague'] != None and x['homeLeague']['name'] == 'LCS', filtered_all_teams))
# lcs_teams
# all_teams[0]['homeLeague']['name']
# list(filter(lambda x: x.get('homeLeague').get('name') == 'LCS', all_teams))
#
# list(filter(lambda x: x['homeLeague']['name'] == 'LCS', all_teams))
#
# for team in all_teams:
#     try:
#         if type(team) == type({'a':'b'}):
#             print(team['homeLeague'])
#     except:
#         print(team)
# all_teams[5]
# type(all_teams[0])
# def dict_lookup(dict_list, key, value):
#     return list(filter(lambda x: x[key] == value, dict_list))
#
# game_metadata = api_session.get_window('109517090067719731')['gameMetadata']
# players_in_game = game_metadata['blueTeamMetadata']['participantMetadata'] + game_metadata['redTeamMetadata']['participantMetadata'] + [{'esportsPlayerId': game_metadata['redTeamMetadata']['esportsTeamId'], 'summonerName':game_metadata['redTeamMetadata']['participantMetadata'][0]['summonerName'].split(' ')[0], 'role': 'team'}, {'esportsPlayerId': game_metadata['blueTeamMetadata']['esportsTeamId'], 'summonerName':game_metadata['blueTeamMetadata']['participantMetadata'][0]['summonerName'].split(' ')[0], 'role': 'team'}]
# game_metadata['blueTeamMetadata']
# players_in_game[0]

#
# test_scorekeeper = ScoreKeeper()
# test_scorekeeper.run()
# test_scorekeeper.matches['Week 1'][0]
#
#
#
# test_scorekeeper.schedule
# test_scorekeeper.match_schedule
#
# test_uuid = uuid.uuid4()
# str(test_uuid)
# test_scorekeeper()
# test_scorekeeper.load_schedule()
#
# test_scorekeeper.schedule['Week 1']
#
# test_scorekeeper
# test_player2 = Player.load("101383793885656347")
# test_player2.__dict__
# test_player2.player_games
# test_scorekeeper.week_match_dict
#
# test_scorekeeper.api_session.get_details('109517090067719730')
# test_scorekeeper.api_session.get_event_details('109517090067719730')
# dict(filter(lambda x: x[0].startswith('Week'), test_scorekeeper.week_match_id_dict.items()))
# test_player = Player('102206337829139149', 'top')
# api_session = LoLEsportsAPI()
#
# test_player.player_stats
# test_scoring_dict = {
#   "player":
#     {
#       "kills": 2,
#       "deaths": -1,
#       "assists": 1.5,
#       "creepScore": 0.01
#     },
#   "team":
#     {
#       "towers": 1,
#       "barons": 2,
#       "dragon_count": 1
#     }
# }
#
# random.randrange(10)
# test_list = [1,2,3]
# random.shuffle(test_list)
# test_list
# test_team_list = [team.id for team in test_scorekeeper.teams]
# len(test_team_list) / 2
#
# test_player.update_player_stats(*api_session.get_player_stats('109517090067719731',test_player.id), 'Week 1')
# test_player.update_player_score_game('Week 1', test_scoring_dict)
# test_player.update_player_score_week('Week 1')
# test_player.player_name
# test_player.player_score
# test_player.player_score_week
#
# test_player.save()
# new_test_player = test_player.load('102206337829139149')
# new_test_player.player_name
# new_test_player.player_score
# new_test_player.player_score_week
#

#
# with open(str(Path.cwd())+"\\scoring.json", 'r') as f:
#     data = json.loads(f.read())
#
# data
#
# a = Path.cwd()
# str(a)
# Path(__file__)
# self.scoring = data
#
#
# dict_lookup(test_list, 'name', 'a')
#
#
# test_list = [{'name':'a'}, {'name': 'b'}]
# list(filter(lambda x: x['name']=='a', test_list))[0]
# # get NA/EU
# NA = api_session.get_leagues()['leagues']
#
#
#
# api_session.get_leagues()
# api_session.get_teams('TSM')
#
# # Start Script
# api_session = LoLEsportsAPI()
# LCS_LEAGUE_ID = '98767991299243165'
# TOURNAMENT_SLUG = 'lcs_spring_2023'
#
# all_tournament_dict = api_session.get_tournaments_for_league(LCS_LEAGUE_ID)['leagues'][0]['tournaments']
# tournament_dict = dict_lookup(all_tournament_dict, key='slug', value=TOURNAMENT_SLUG)[0]
#
# print(tournament_dict)
#
# # get start and end dates
# split_start_date = dateutil.parser.parse(tournament_dict['startDate']).replace(tzinfo=dateutil.tz.tzutc())
# split_end_date = dateutil.parser.parse(tournament_dict['endDate']).replace(tzinfo=dateutil.tz.tzutc()) + datetime.timedelta(days=1)
#
# # Get Schedule
# schedule = []
# temp_schedule = api_session.get_schedule(LCS_LEAGUE_ID)['schedule']
# older_schedule = temp_schedule['pages']['older']
# newer_schedule = temp_schedule['pages']['newer']
# schedule += temp_schedule['events']
# # get new pages
# while newer_schedule is not None:
#     temp_schedule = api_session.get_schedule(LCS_LEAGUE_ID, page_token=newer_schedule)['schedule']
#     newer_schedule = temp_schedule['pages']['newer']
#     schedule += temp_schedule['events']
# # get old pages
# old_temp_schedule = api_session.get_schedule(LCS_LEAGUE_ID, page_token=older_schedule)['schedule']
# while len(list(filter(lambda x: dateutil.parser.parse(x['startTime']) > split_start_date, old_temp_schedule['events']))) > 0:
#     old_temp_schedule = api_session.get_schedule(LCS_LEAGUE_ID, page_token=older_schedule)['schedule']
#     older_schedule = old_temp_schedule['pages']['older']
#     schedule = old_temp_schedule['events'] + schedule
# # filter clean up
# schedule = list(filter(lambda x: dateutil.parser.parse(x['startTime']) > split_start_date, schedule))
# schedule = list(filter(lambda x: dateutil.parser.parse(x['startTime']) <= split_end_date, schedule))
#
#
# schedule
# # Get Matches by Week
# weeks_list = list(set([match['blockName'] for match in schedule]))
# week_match_dict = {}
# for week in weeks_list:
#     week_match_dict[week] = dict_lookup(schedule, 'blockName', week)
# week_match_dict
#
# #week_match_id_dict = {}
# #for key in week_match_dict.keys():
# #   week_match_id_dict[key] = [match['match']['id'] for match in ]
#
#
# week_match_id_dict = {}
# for key in week_match_dict.keys():
#     week_match_id_dict[key] = [match['match']['id'] for match in week_match_dict[key]]
# #week_match_id_dict
# #week_match_dict
#
# week_match_id_dict['Week 1']
#
#
#
# api_session.get_event_details(109517090067719730)['data']['event']['match']['games'][0]['id']
# api_session.get_event_details(109517090067719730)
# api_session.get_details('109517090067719731')
# now = datetime.datetime.now()
# test_start_time = now.replace(second=math.floor(now.second / 10) * 10, microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')
# datetime.datetime.now()
# test_start_time
#
# window_test = api_session.get_window('109517090067719731', start_time=test_start_time)
# latest_frame = max([dateutil.parser.parse(x['rfc460Timestamp']) for x in window_test['frames']]).strftime('%Y-%m-%dT%H:%M:%S.%-fZ')
#
# a= pd.DataFrame(get_game_metadata('109517090067719731')['blueTeamMetadata'])
# a['participantMetadata'].apply(pd.Series)
#
# window_test['gameMetadata']
#
# window_test
#
# frame_times = [dateutil.parser.parse(x['rfc460Timestamp']) for x in window_test['frames']]
# latest_frame_index = frame_times.index(max(frame_times))
# #latest_frame = window_test['frames']
# import pandas as pd
# pd.DataFrame(dict_lookup(window_test['frames'], 'rfc460Timestamp', window_test['frames'][latest_frame_index]['rfc460Timestamp'])[0])
# latest_frame
#
# window_test['frames'][latest_frame_index]
#
# window_test
#
#
#
# test_date = dateutil.parser.parse(tournament_dict['startDate'])
# test_date.replace(tzinfo=datetime.timezone.utc)
# dateutil.parser.parse(schedule[0]['startTime'])
# test_unit[0]['startTime']
# test_list = []
# temp_schedule['events']
# test_list += temp_schedule['events']
# test_list
# api_session.get_schedule(LCS_LEAGUE_ID, 'bmV3ZXI6OjEwOTUxNzA5MDA2NzcxOTc4Mg==')['schedule']
# api_session.get_standings(109517090066605615)
# api_session.get_completed_events('108206581962155974')
# api_get
#
#
# api_session.get_event_details('108206581962155974')
# print('hello')
# #?startingTime=2021-01-17T16:24:50Z
# requests.get('https://feed.lolesports.com/livestats/v1/window/108206581965105250?startingTime=2022-08-13T23:53:40Z', headers={'x-api-key': API_KEY}).json()
# api_session.get_team_stats(108206581965105250,team_id='98926509892121852',start_time='2022-08-13T23:56:40Z')
# api_session.get_player_stats(108206581965105250, player_id='106547199482728931', start_time='2022-08-13T23:56:40Z')
#
# api_session.get_window(108206581965105250,start_time='2022-08-13T23:56:40Z')
#
# api_session.get_details(108206581965105250, start_time='2022-08-13T23:56:40Z')
# requests.get('https://feed.lolesports.com/livestats/v1/details/108206581965105250', headers={'x-api-key': API_KEY}).json()
# api_session.get_event_details(108206581965105249)
# api_session.get_schedule(98767991299243165)['schedule']
# api_session.get_games(108206581965039662)
# api_session.get_window(108176672286598206)
#
# api_session.get_event_details(109517090067719782)
#
# api_session.get_d(108176672286598206)
# BASE_URL = 'https://esports-api.lolesports.com/persisted/gw'
# API_KEY = '0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z'#'RGAPI-46209a5c-f824-4825-9447-e739e268167a'
# headers = {'x-api-key': API_KEY}
# game_id = 2782
# URL = BASE_URL + f'/getLeagues'
# params = {'hl':'en-US'}
# resp = requests.get(URL, headers=headers, params={'hl': 'en-US'})
# resp.json()
# resp.json()
#
#
# # https://esports-api.lolesports.com/persisted/gw/getSchedule?hl=en-US&leagueId=98767991299243165%2C98767991302996019%2C98767991325878492
#
# requests.get('https://esports-api.lolesports.com/persisted/gw/getLeagues', params=params,headers=headers)
# resp = requests.get('https://esports-api.lolesports.com/persisted/gw/getGames', params={'hl':'en-US','id':1},headers=headers)
# resp.json()
# all(k in conf and check_structure(struct[k], conf[k]) for k in struct)
# import schema
# schema.Schema(api_session.get_event_details(108206581965105249))
