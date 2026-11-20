from copy import deepcopy
from hashlib import sha256
import json
import pytest
from robin.source_observatory import opaque_choices


def source():
    return {'calendarSha256':'a'*64,'fixtures':[{'id':'game','label':'Equipe A – Equipe B','homeAliases':['Equipe A'],'awayAliases':['Equipe B'],'kickoff':'2026-11-20T19:45:00Z'}],
        'profiles':[{'request':{'url':'https://www.olbg.com/tipsters/tips/158','responseSha256':'b'*64,'observedAt':'2026-11-20T19:01:57Z'},
        'facts':{'authorId':158,'authorLabel':'Bobby','mode':'current','records':[{'tipid':123,'eventid':456,'eventname':'Equipe A v Equipe B','event_datetime':'2026-11-20 19:45:00','vc_sport_id':1,'result':'Open','selection':'Under 2.50','market':'Total Goals','winew':'Win','hcap':'2.50','hcap_market':True,'odds':1.95}]}}]}


def build(value=None):
    return opaque_choices.build_opaque_choices(value or source(),[123],parser_sha='c'*64)


def test_opaque_preserves_source_types_and_never_interprets_market():
    rows=build()
    assert len(rows)==1
    row=rows[0]
    assert row['sourceFields']==source()['profiles'][0]['facts']['records'][0]
    assert row['sourceFields']['hcap']=='2.50'
    assert row['market']=='source_native_opaque'
    assert row['sourceBetType']=='Win'
    assert row['publishedAt'] is None and row['sourceEventTimezone'] is None
    assert row['performanceEvaluationAllowed'] is False
    assert row['settlementAllowed'] is False
    assert row['marketInterpretationAllowed'] is False
    assert row['kickoff']=='2026-11-20T19:45:00Z'


@pytest.mark.parametrize('change',[ 'wrong-author','late','duplicate' ])
def test_unproven_identity_or_timing_is_rejected(change):
    value=source()
    if change=='wrong-author':value['profiles'][0]['facts']['authorId']=999
    elif change=='late':value['profiles'][0]['request']['observedAt']='2026-11-20T19:45:00Z'
    else:value['profiles'][0]['facts']['records']*=2
    with pytest.raises(ValueError):build(value)


def test_reader_rejects_source_change_and_interpretation_flags(tmp_path):
    value=source(); sp=tmp_path/'source.json';sp.write_bytes(json.dumps(value).encode())
    sh=sha256(sp.read_bytes()).hexdigest()
    bundle={'schemaVersion':'robin-opaque-tipster-facts-v1','sourceResultSha256':sh,'lexicalParserSha256':'c'*64,'acceptedSourceTipIds':[123],'fixtures':value['fixtures'],'picks':build()}
    bp=tmp_path/'bundle.json'
    for mutate in [None,'performanceEvaluationAllowed','settlementAllowed','marketInterpretationAllowed']:
        current=deepcopy(bundle)
        if mutate:current['picks'][0][mutate]=True
        bp.write_bytes(json.dumps(current).encode());bh=sha256(bp.read_bytes()).hexdigest()
        if mutate:
            with pytest.raises(ValueError):opaque_choices.read_opaque_bundle(bp,bh,sp,sh)
        else:
            assert opaque_choices.read_opaque_bundle(bp,bh,sp,sh)['distinctPicks']==1
    sp.write_bytes(b'{}')
    with pytest.raises(ValueError):opaque_choices.read_opaque_bundle(bp,bh,sp,sh)


def test_same_source_identity_is_not_counted_twice_across_representations():
    row=build()[0]
    prior={**row,'market':'source_native'}
    result=opaque_choices.merge_distinct_choices([prior],[row])
    assert len(result)==1
    assert result[0]['market']=='source_native'


@pytest.mark.parametrize('change',['boolean-as-zero','native-boolean-as-one','tipid-as-float'])
def test_json_scalar_types_cannot_be_changed_by_a_valid_outer_hash(tmp_path,change):
    value=source();sp=tmp_path/'source.json';sp.write_bytes(json.dumps(value).encode());sh=sha256(sp.read_bytes()).hexdigest()
    bundle={'schemaVersion':'robin-opaque-tipster-facts-v1','sourceResultSha256':sh,'lexicalParserSha256':'c'*64,'acceptedSourceTipIds':[123],'fixtures':value['fixtures'],'picks':build()}
    if change=='boolean-as-zero':bundle['picks'][0]['settlementAllowed']=0
    elif change=='native-boolean-as-one':bundle['picks'][0]['sourceFields']['hcap_market']=1
    else:bundle['picks'][0]['sourceTipId']=123.0
    bp=tmp_path/'bundle.json';bp.write_bytes(json.dumps(bundle).encode());bh=sha256(bp.read_bytes()).hexdigest()
    with pytest.raises(ValueError):opaque_choices.read_opaque_bundle(bp,bh,sp,sh)
