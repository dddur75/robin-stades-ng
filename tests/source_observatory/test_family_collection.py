from robin.source_observatory import family_collection


def pick(tid,author,at='2026-11-20T19:01:00Z'):
    return {'id':f'olbg-tip:{tid}','sourceId':'SRC_014','sourceTipId':tid,'authorId':f'olbg:{author}',
            'authorUrl':f'https://www.olbg.com/tipsters/tips/{author}','observedAt':at,'selection':'Draw','versions':[]}


def test_new_family_views_preserve_old_facts_and_deduplicate_source_identity():
    old=pick(1,99,'2026-11-20T17:00:00Z');win=pick(2,669088);opaque=pick(3,158)
    base={'picks':[old],'fixtures':[],'claimId':'OLD','generatedAt':'2026-11-20T17:00:00Z'}
    result=family_collection.merge_family_public(base,{'picks':[win],'fixtures':[],'claimId':'WIN','qualifiedAt':'2026-11-20T19:06:00Z'},
        {'picks':[opaque,win],'fixtures':[],'claimId':'OPAQUE'},qualified_at='2026-11-20T19:15:00Z')
    assert result['distinctPicks']==3 and result['authorCount']==3
    assert result['picks'][0]['id']==old['id']
    assert result['sourceObservedThrough']=='2026-11-20T19:01:00Z'
    assert result['generatedAt']=='2026-11-20T19:15:00Z'
    assert base['picks']==[old]


def test_family_candidate_join_requires_exact_origin_and_never_activates():
    author=669088;url=f'https://www.olbg.com/tipsters/tips/{author}'
    row={'id':'candidate','sourceUrl':url,'origin':{'sheet':'Catalogue','row':70},'collectionEnabled':False,'qualification':{'picks':[],'personallyProven':False}}
    wrong={**row,'origin':{'sheet':'Profils FR','row':70}}
    base={'candidates':[row,wrong],'qualification':{'status':'ok'}}
    report={'claimId':'FAMILY','profiles':[{'candidateId':'candidate','sourceUrl':url,'sheet':'Catalogue','row':70,'observedAt':'2026-11-20T19:01:00Z'}]}
    result=family_collection.merge_family_candidates(base,report,[pick(2,author)],None)
    assert result['candidates'][0]['qualification']['personallyProven'] is True
    assert result['candidates'][0]['collectionEnabled'] is False
    assert result['candidates'][1]['qualification']['personallyProven'] is False
    assert result['qualification']['qualifiedCount']==1


def test_missing_new_family_metadata_does_not_erase_prior_facts(tmp_path):
    base={'picks':[pick(1,99)],'distinctPicks':1,'authorCount':1}
    result=family_collection.add_family_public(base,tmp_path)
    assert result['picks']==base['picks'] and result['distinctPicks']==1
    assert result['familyCollection']['state']=='unavailable'


def test_missing_opaque_bundle_does_not_discard_valid_native_win():
    result=family_collection.merge_family_public({'picks':[],'fixtures':[],'claimId':'OLD','generatedAt':'2026-11-20T17:00:00Z'},
        {'picks':[pick(2,669088)],'fixtures':[],'claimId':'WIN','qualifiedAt':'2026-11-20T19:06:00Z'},None,qualified_at='2026-11-20T19:15:00Z')
    assert result['distinctPicks']==1
    assert result['familyCollection']['opaqueState']=='unavailable'


def test_no_available_bundle_preserves_base_and_reports_unavailable(monkeypatch):
    base={'picks':[pick(1,99)],'fixtures':[],'claimId':'OLD','generatedAt':'2026-11-20T17:00:00Z'}
    result=family_collection.merge_family_public(base,None,None,qualified_at='2026-11-20T19:15:00Z')
    assert result['picks']==base['picks']
    assert result['generatedAt']==base['generatedAt']
    assert result['familyCollection']['state']=='unavailable'
    candidates={'candidates':[],'qualification':{'status':'ok','qualifiedCount':7}}
    monkeypatch.setattr(family_collection,'_load',lambda root: ({},None,None,None))
    result=family_collection.add_family_candidates(candidates,None)
    assert result['qualification']['familyCollectionState']=='unavailable'
    assert result['qualification']['qualifiedCount']==7


def test_new_family_cannot_rewind_a_newer_base_view():
    base={'picks':[],'fixtures':[],'claimId':'OLD','generatedAt':'2026-11-20T20:00:00Z'}
    win={'picks':[pick(2,669088)],'fixtures':[],'claimId':'WIN','generatedAt':'2026-11-20T18:00:00Z'}
    result=family_collection.merge_family_public(base,win,None,qualified_at='2026-11-20T19:15:00Z')
    assert result['generatedAt']==base['generatedAt']
