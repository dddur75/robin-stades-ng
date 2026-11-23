"""Six new gate variants, one synthetic graph/row/calendar; no old replay."""
import copy
import json
from datetime import datetime,timezone
import pytest
from robin.source_observatory import notbetting_prospective as m
uid="11111111-1111-1111-1111-111111111111";label="SYNTHETIC_OWNER"
row=dict(id="22222222-2222-2222-2222-222222222222",event="Synthetic Home - Synthetic Away",pick="SYNTHETIC_OPAQUE",competition="Bundesliga",date="2026-11-27T19:30:00+00:00",tipsterId=uid,tipster=dict(user=dict(id=uid,username=label,tipster=dict(id=uid,userId=uid))))
fixture=dict(id="synthetic",home="Synthetic Home",away="Synthetic Away",kickoff=row["date"],competition="Bundesliga",calendarSHA="a"*64,calendarClaim="SYNTHETIC.CALENDAR")
kwargs=dict(ownerSpec=dict(uid=uid,label=label),competition="Bundesliga",responseSHA="a"*64,parserSHA="b"*64,calendarSHA="a"*64,calendarClaim="SYNTHETIC.CALENDAR")
seed={"0":"$a:entry:data","a":{"entry":{"data":row}}}
cases=[("positive",seed,True,None)]
x=copy.deepcopy(seed);x["a"]["entry"]["data"]["access"]="private";cases.append(("private_target",x,False,"gate_state_unproven"))
x=copy.deepcopy(seed);x["a"]["entry"]["data"]["access"]=None;cases.append(("null_target",x,False,"gate_state_unproven"))
x=copy.deepcopy(seed);x["a"]["type"]="recommendation";cases.append(("recommendation_ancestor",x,False,"filtered_metadata_context"))
x=copy.deepcopy(seed);x["a"]["recommendations"]=x["a"].pop("entry");x["0"]="$a:recommendations:data";cases.append(("filtered_path",x,False,"filtered_reference_segment"))
x=copy.deepcopy(seed);x["a"]["entry"]["access"]="members_only";cases.append(("unknown_intermediate",x,False,"gate_state_unproven"))
@pytest.mark.parametrize("name,documents,positive,reason", cases, ids=[case[0] for case in cases])
def test_reference_path_gate(name,documents,positive,reason):
    before=json.dumps(documents,sort_keys=True)
    result=m.qualify_documents(documents,[fixture],datetime(2026,11,23,tzinfo=timezone.utc),**kwargs)
    assert before==json.dumps(documents,sort_keys=True)
    assert bool(result["picks"])==positive,(name,result["reasons"])
    if positive:
        assert result["status"]=="qualified" and result["picks"][0]["eligibleForApplication"]is False
    else:
        assert result["status"]=="partial" and reason in result["reasons"] and not result["traversalComplete"]
