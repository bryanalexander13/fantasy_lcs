import fantasy_lcs
import streamlit as st
from pathlib import Path
import os
# fantasy_lcs.FOLDER_PATH = str(Path.cwd())

def radio_callback():
    if st.session_state.radio == "Team":
        st.session_state.weekly_dropdown = True
    else:
        st.session_state.weekly_dropdown = False

def week_callback():
    if st.session_state.radio == 'Matchup':
        createMatchUpDisplay(st.session_state.week)

def wraptexthtml(text, justify='left'):
    if justify == 'right':
        return '<div style="text-align: right">' + str(text) + '</div>'
    elif justify == 'left':
        return '<div>' + str(text) + '</div>'

@st.cache_data
def createScorekeeper():
    return fantasy_lcs.ScoreKeeper(scoring_path=r'scoring.json',
                                     teams_path=r'teams_test.json')
scorekeeper = createScorekeeper()

scorekeeper.matches
# @st.cache_data
# def createHeader():
    # st.title('Fantasy LCS')
    # if "weekly_dropdown" not in st.session_state:
    #     st.session_state.weekly_dropdown = False
    #     st.session_state.radio = "Matchup"
    #     st.session_state.week = 'Week 1'
    #
    # current_radio = 'Matchup'
    # current_week = 'Week 1'
    #
    # matchup_team_league = st.radio('',
    #                                options=['Matchup', "Team", "League"],
    #                                horizontal=True, key='radio',
    #                                on_change=radio_callback)
    # matchup_week = st.selectbox('Week',
    # scorekeeper.match_schedule.keys(),
    #  disabled=st.session_state.weekly_dropdown,
    #  key='week',
    #  on_change=week_callback
    #  )
# createHeader()
#scorekeeper = fantasy_lcs.ScoreKeeper()

st.title('Fantasy LCS')
if "weekly_dropdown" not in st.session_state:
    st.session_state.weekly_dropdown = False
    st.session_state.radio = "Matchup"
    st.session_state.week = 'Week 1'

current_radio = 'Matchup'
current_week = 'Week 1'

matchup_team_league = st.radio('',
                               options=['Matchup', "Team", "League"],
                               horizontal=True, key='radio',
                               on_change=radio_callback)
matchup_week = st.selectbox('Week',
scorekeeper.match_schedule.keys(),
 disabled=st.session_state.weekly_dropdown,
 key='week',
 on_change=week_callback
 )


# scorekeeper.week_match_dict
#
# scorekeeper.get_player_stats('109517090067785414',)
# test_match.
# test_match.team1.top
# scorekeeper.week_match_dict['Week 1'][0]
# Match Up
# scorekeeper.week_match_dict['Week 1']

#scorekeeper.week_match_dict['Week 1']

#test_match.team1.top.player_games
#test_match.team1.top.player_stats
#scorekeeper.matches
scorekeeper.matches['Week 1'][0].get_player_score_dict(1, 'top')
def createMatchUpDisplay(week):
    disp_match = scorekeeper.matches[week][0] # TODO make this dynamic
    col1, col2 = st.columns(2)
    with col1:
        # Team Score Owner
        st.write(wraptexthtml(disp_match.team1.team_name), unsafe_allow_html=True)
        st.write(wraptexthtml(disp_match.team1.owner), unsafe_allow_html=True)
        st.caption(wraptexthtml(disp_match.team1_score), unsafe_allow_html=True)

        for player_role in ('top', 'jg', 'mid', 'adc', 'sup'):
            st.divider()
            st.write(wraptexthtml(disp_match.get_player(1, player_role)), unsafe_allow_html=True)
            temp_game_dict = disp_match.get_player_score_dict(1, player_role)
            for i, game_id in enumerate(temp_game_dict.keys()):
                # player_stats = getattr(disp_match.team1, player_role).get_player_stats(week, game_id)
                # scoreline = f"{player_stats.get('kills')}/{player_stats.get('deaths')}/{player_stats.get('assists')}"
                scoreline = disp_match.get_player_stats(1, player_role, week, game_id)
                game_metadata = list(filter(lambda x: scorekeeper.api_session.get_game_id_from_match_id(x['match']['id']) == game_id, scorekeeper.week_match_dict[week]))[0]
                game_teams = {team['code']: team['result']['outcome'] for team in game_metadata['match']['teams']}
                player_team = scorekeeper.get_org_by_id(getattr(disp_match.team1, player_role).player_team)
                opp_team = [team for team in game_teams.keys() if team != player_team][0]
                result = game_teams[player_team].upper()
                st.caption(wraptexthtml(str(temp_game_dict[game_id]) + ' '+ result + ' vs ' + opp_team), unsafe_allow_html=True)
                st.caption(wraptexthtml(scoreline + ' as ' + player_stats['championId']), unsafe_allow_html=True)
                if i < len(temp_game_dict.keys()) - 1:
                    st.caption('')
    with col2:
        st.write(wraptexthtml(disp_match.team2.team_name, 'right'), unsafe_allow_html=True)
        st.write(wraptexthtml(disp_match.team2.owner, 'right'), unsafe_allow_html=True)
        st.caption(wraptexthtml(disp_match.team2_score, 'right'), unsafe_allow_html=True)


        for player_role in ('top', 'jg', 'mid', 'adc', 'sup'):
            st.divider()
            st.write(wraptexthtml(disp_match.get_player(2, player_role), 'right'), unsafe_allow_html=True)
            temp_game_dict = disp_match.get_player_score_dict(2, player_role)
            for i, game_id in enumerate(temp_game_dict.keys()):
                #player_stats = getattr(disp_match.team2, player_role).get_player_stats(week, game_id)
                #scoreline = f"{player_stats.get('kills')}/{player_stats.get('deaths')}/{player_stats.get('assists')}"
                scoreline = disp_match.get_player_stats(2, player_role, week, game_id)
                game_metadata = list(filter(lambda x: scorekeeper.api_session.get_game_id_from_match_id(x['match']['id']) == game_id, scorekeeper.week_match_dict[week]))[0]
                game_teams = {team['code']: team['result']['outcome'] for team in game_metadata['match']['teams']}
                player_team = scorekeeper.get_org_by_id(getattr(disp_match.team2, player_role).player_team)
                opp_team = [team for team in game_teams.keys() if team != player_team][0]
                result = game_teams[player_team].upper()
                st.caption(wraptexthtml(str(temp_game_dict[game_id]) + ' '+ result + ' vs ' + opp_team, 'right'), unsafe_allow_html=True)
                st.caption(wraptexthtml(scoreline + ' as ' + player_stats['championId'], 'right'), unsafe_allow_html=True)
                if i < len(temp_game_dict.keys()) - 1:
                    st.caption('')


def createLeagueDisplay(week):
    st.title('Matchups')
    week_matches = scorekeeper.matches[week]
    for match in week_matches:
        continue
    return

##scorekeeper.matches
 # ["visible", "hidden", "collapsed"]

 #test_match
