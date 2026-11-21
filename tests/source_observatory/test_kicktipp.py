from robin.source_observatory import kicktipp
import pytest


def test_overview_projects_only_bounded_native_scores_with_headers():
    html='<table><tr><th>Joueur</th><th>A - B</th><th>C - D</th><th>Points</th></tr>'
    html+=''.join(f'<tr><td>Joueur{i}</td><td>2:1</td><td>?</td><td>123</td></tr>' for i in range(5))+'</table>'
    result=kicktipp.project_overview(html.encode(),'text/html; charset=utf-8')
    assert len(result['participants'])==3
    assert result['participants'][0]['pseudonym']=='Joueur0'
    assert result['participants'][0]['cells']==[{'fixtureLabel':'A - B','nativeSelection':'2:1'}]
    assert result['admittedChoices']==0 and result['publishedAt'] is None


def test_masked_and_ranking_cells_never_become_score_predictions():
    html='<table><tr><th>Joueur</th><th>A - B</th><th>Points</th></tr><tr><td>Alice</td><td>?</td><td>123</td></tr></table>'
    result=kicktipp.project_overview(html.encode(),'text/html')
    assert result['participants']==[]
    assert result['status']=='NO_VISIBLE_TYPED_SCORE_CELLS'


def test_actual_challenge_stops_overview_reader():
    with pytest.raises(ValueError,match='access challenge'):
        kicktipp.project_overview(b'<main><h1>Verify you are human</h1></main>','text/html')


def test_unsupported_grid_keeps_bounded_structure_without_extra_participant_text():
    html=b'<table id="ranking"><tr><th>Place</th><th>Points</th></tr><tr><td>UnretainedPerson</td><td>123</td></tr></table>'
    result=kicktipp.project_overview(html,'text/html')
    assert result['structure']==[{'id':'ranking','rowCount':2,'cellCount':4,'headers':['Place','Points']}]
    assert 'UnretainedPerson' not in str(result)


def test_body_row_header_does_not_replace_fixture_column_headers():
    html=b'<table><tr><th>Pos.</th><th>Nom</th><th>A - B</th></tr><tr><th>1</th><td>Alice</td><td>2:1</td></tr></table>'
    result=kicktipp.project_overview(html,'text/html')
    assert result['participants']==[{'pseudonym':'Alice','cells':[{'fixtureLabel':'A - B','nativeSelection':'2:1'}]}]


def test_schedule_preserves_native_civil_date_without_inventing_utc():
    html=b'<table id="spielplanSpiele"><tr><th>Date</th><th>A domicile</th><th>A l\'exterieur</th><th>Resultat</th></tr><tr id="fixture-9"><td>21/11/2026 15:00</td><td>Equipe A</td><td>Equipe B</td><td>-</td></tr></table>'
    result=kicktipp.project_overview(html,'text/html')
    assert result['fixtureDeclarations']==[{'nativeFixtureRef':'fixture-9','nativeDate':'21/11/2026 15:00','nativeHome':'Equipe A','nativeAway':'Equipe B','nativeResult':'-','sourceTimezone':None}]
    assert result['canonicalKickoffsEstablished'] is False
