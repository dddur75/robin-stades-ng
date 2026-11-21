from hashlib import sha256
import json
from robin.source_observatory import compatible_access


def test_latest_compatible_assessment_does_not_activate_or_remove_proven_choices(tmp_path):
    source={'status':'ok','picks':[{'id':'old'}],'candidates':[],
            'qualification':{'status':'ok','personalOverlayState':'ok','personalClaimId':'TEST.PERSONAL','platforms':[{'platform':'Coteur','label':'Old'}]}}
    report={'schemaVersion':'robin-personal-access-v1','scope':'LOCAL_PERSONAL_NONCOMMERCIAL_NO_REDISTRIBUTION',
        'claimId':'TEST.COMPATIBLE','platforms':[{'platform':'Coteur','label':'New','reason':'Confirmed source limitation',
        'requiredAccess':'Personal choices still to establish','ownerAction':'No action required now',
        'observedAt':'2026-11-20T18:37:00Z','status':'partial_technical','evidenceRefs':['TEST.SOURCE']} ]}
    path=tmp_path/'report.json';path.write_bytes(json.dumps(report).encode())
    result=compatible_access.read_compatible_access(source,path,sha256(path.read_bytes()).hexdigest())
    assert result['picks']==[{'id':'old'}]
    assert result['qualification']['platforms'][0]['label']=='New'
    assert result['qualification']['compatibleAccessState']=='ok'
    assert result['qualification']['personalClaimId']=='TEST.PERSONAL'
    assert result['qualification']['compatibleClaimId']=='TEST.COMPATIBLE'
    assert 'collectionEnabled' not in result['qualification']['platforms'][0]
    assert source['qualification']['platforms'][0]['label']=='Old'


def test_missing_compatible_overlay_keeps_previous_personal_proof_and_warns(tmp_path):
    base={'qualification':{'status':'ok','personalOverlayState':'ok'},'picks':[{'id':'old'}]}
    result=compatible_access.read_compatible_access(base,tmp_path/'missing','0'*64)
    assert result['picks']==[{'id':'old'}]
    assert result['qualification']['personalOverlayState']=='ok'
    assert result['qualification']['compatibleAccessState']=='unavailable'
