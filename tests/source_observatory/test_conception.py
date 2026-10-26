"""Synthetic acceptance cases from the decisive dossier, never a corpus replay."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from robin.source_observatory import models, service
from robin.source_observatory.store import AppendOnlyStore, AppendOnlyViolation

T = datetime(2026, 10, 25, 18, tzinfo=UTC)
H = 'a' * 64


def rule(market='1N2', **changes):
    return models.SettlementRule(**(dict(
        rule_id='rules:' + market, version='1', document_url='https://example.invalid/rules',
        evidence_sha256=H, market=market, period='reglementaire', postponed='en_attente',
    ) | changes))


def version(identifier='v1', **changes):
    return models.PublicationVersion(**(dict(
        version_id=identifier, publication_id='p1', text_sha256=H,
        announced_by_platform_at=T, first_observed_by_robin_at=T,
        modification_observed_at=None, usable_at=T,
    ) | changes))


def contribution(identifier='c1', **changes):
    return models.Contribution(**(dict(
        contribution_id=identifier, version_id='v1', source_id='s1', author_id='account-a',
        publication_id='p1', publication_url='https://example.invalid/p1', text_sha256=H,
        preuve_permise='https://example.invalid/permission', langue='fr', marche='1N2',
        selection='home', cote_declaree=Decimal('2.4'), cote_observee=None,
        cote_declaree_provenance='auteur', cote_declaree_at=T,
        cote_observee_provenance=None, cote_observee_at=None, bookmaker=None,
        statut='resolu', raison_non_resolu=None, extraits_preuve=(models.EvidenceExcerpt(
            H, 0, 4, 'home'),), liens_reprise=(), match_id='m1',
        certitude_rapprochement='certaine', ligne=None, periode='reglementaire',
        reglement=rule(), categorie='selection_avec_cote', probabilite=None, observed_at=T,
    ) | changes))


def match(c=None, **changes):
    c = c or contribution()
    return models.MatchMarket(**(dict(
        match_market_id='mm:' + c.contribution_id, contribution_id=c.contribution_id,
        version_id=c.version_id, contribution_usable_at=T, match_usable_at=T + timedelta(hours=2),
        match_id='m1', market_id='market', selection_id='selection', statut='resolu',
        raison_non_resolu=None,
    ) | changes))


def settled(c=None, **score):
    c = c or contribution()
    return service.settle(c, match(c), result_id='r:' + c.contribution_id,
                          observed_at=T + timedelta(hours=4), evidence_sha256=H,
                          score=models.MatchScore(**(dict(home=1, away=0) | score)))


def seed(store, c=None, v=None):
    store.append(models.Source('s1', 'synthetic', 'https://example.invalid'))
    store.append(models.Publication('p1', 's1', 'https://example.invalid/p1'))
    store.append(v or version())
    store.append(c or contribution())


def test_scenario_a_observed_18_kickoff_20_corrected_22(tmp_path):
    store = AppendOnlyStore(tmp_path / 'a.jsonl')
    seed(store)
    store.append(version('v2', previous_version_id='v1', text_sha256='b' * 64,
                         modification_observed_at=T + timedelta(hours=4),
                         usable_at=T + timedelta(hours=4)))
    store.append(contribution('c2', version_id='v2', text_sha256='b' * 64,
                              selection='away', extraits_preuve=(),
                              observed_at=T + timedelta(hours=4)))
    assert service.pre_match_contributions(store.entities(), T + timedelta(hours=2)) == (
        contribution(),)
    assert len(AppendOnlyStore(store.path).entities()) == 6


def test_scenario_b_platform_18_discovered_22_is_retrospective(tmp_path):
    store = AppendOnlyStore(tmp_path / 'b.jsonl')
    v = version(first_observed_by_robin_at=T + timedelta(hours=4),
                usable_at=T + timedelta(hours=4))
    c = contribution(observed_at=T + timedelta(hours=4))
    seed(store, v=v, c=c)
    assert service.pre_match_contributions(store.entities(), T + timedelta(hours=2)) == ()
    evaluation = service.evaluate(c, match(c,
        contribution_usable_at=v.usable_at), settled(c), odds_basis='cote_declaree')
    assert not evaluation.evaluable
    assert evaluation.reason == 'invalide_pre_match'


def test_utc_and_original_dst_timezone_survive_restart(tmp_path):
    local = T.astimezone(ZoneInfo('Europe/Paris'))
    v = version(first_observed_by_robin_at=local, usable_at=local,
                announced_by_platform_at=local)
    store = AppendOnlyStore(tmp_path / 'tz.jsonl')
    seed(store, v=v)
    restored = AppendOnlyStore(store.path).entities()[2]
    assert restored.first_observed_by_robin_at.tzinfo.key == 'Europe/Paris'
    assert restored.first_observed_by_robin_at == T
    assert '"utc":"2026-10-25T18:00:00+00:00"' in store.path.read_text()
    assert 'Europe/Paris' in store.path.read_text()


def test_permission_and_match_certainty_are_required():
    with pytest.raises(ValueError):
        contribution(preuve_permise=None)
    with pytest.raises(ValueError):
        contribution(certitude_rapprochement='inventee')
    assert contribution(match_id=None, certitude_rapprochement='non_resolue').match_id is None
    with pytest.raises(ValueError):
        contribution(cote_declaree_provenance=None)


def test_ten_attested_reprises_one_group_unknown_origins_stay_separate():
    origin = contribution()
    copies = tuple(contribution(str(i), publication_id='copy:' + str(i),
        liens_reprise=(models.RepriseLink('p1', 'attestee', H),)) for i in range(10))
    unknown = (contribution('u1', publication_id='u1'), contribution('u2', publication_id='u2',
        liens_reprise=(models.RepriseLink('u1', 'similarite', None),)))
    groups = service.reprise_groups((origin,) + copies + unknown)
    assert len(groups) == 3
    assert len(groups['p1']) == 11
    assert groups['u1'] == ('u1',)
    assert groups['u2'] == ('u2',)


@pytest.mark.parametrize('market,selection,line,score,expected', [
    ('1N2', 'draw', None, dict(home=1, away=1), 'gagne'),
    ('1N2', 'away', None, dict(home=1, away=1, qualified='away'), 'perdu'),
    ('qualification', 'away', None, dict(home=1, away=1, qualified='away'), 'gagne'),
    ('qualification', 'home', None, dict(home=1, away=1), 'en_attente'),
    ('total', 'over', '2', dict(home=1, away=1), 'rembourse'),
    ('total', 'over', '2.25', dict(home=1, away=1), 'demi_perdu'),
    ('total', 'under', '2.25', dict(home=1, away=1), 'demi_gagne'),
    ('handicap', 'home', '-0.25', dict(home=0, away=0), 'demi_perdu'),
    ('handicap', 'away', '0.25', dict(home=0, away=0), 'demi_gagne'),
    ('handicap', 'home', '-0.75', dict(home=1, away=0), 'demi_gagne'),
])
def test_documented_settlements(market, selection, line, score, expected):
    c = contribution(marche=market, selection=selection,
                     ligne=Decimal(line) if line is not None else None, reglement=rule(market))
    assert settled(c, **score).outcome == expected


@pytest.mark.parametrize('changes', [dict(reglement=None),
    dict(reglement=rule(period='prolongations')),
    dict(reglement=rule('autre')), dict(periode='mi_temps')])
def test_missing_or_unsupported_rule_waits(changes):
    c = contribution(**changes)
    result = settled(c)
    assert result.outcome == 'en_attente'
    assert service.evaluate(c, match(c), result, odds_basis='cote_declaree').reason == 'en_attente'


@pytest.mark.parametrize('outcome,profit', [('demi_gagne', '0.70'), ('demi_perdu', '-0.5')])
def test_half_settlement_unit_returns(outcome, profit):
    c = contribution(marche='handicap', ligne=Decimal('-0.25'), reglement=rule('handicap'))
    r = replace(settled(c), outcome=outcome)
    assert service.evaluate(c, match(c), r, odds_basis='cote_declaree').unit_profit == Decimal(profit)


def test_combined_half_settlements_and_missing_leg_rule():
    legs = (models.SettlementLeg('leg-a', Decimal('2'), 'demi_gagne', rule('handicap')),
            models.SettlementLeg('leg-b', Decimal('3'), 'rembourse', rule('total')))
    c = contribution(marche='combine', reglement=rule('combine'), cote_declaree=Decimal('6'))
    r = service.settle_combined(c, match(c), result_id='combo',
        observed_at=T + timedelta(hours=4), evidence_sha256=H, legs=legs)
    evidence = []
    for leg, line in zip(legs, ('0.25', '2'), strict=True):
        leg_c = contribution(leg.contribution_id, publication_id=leg.contribution_id,
            version_id=leg.contribution_id, marche=leg.reglement.market,
            ligne=Decimal(line), reglement=leg.reglement, cote_declaree=leg.odds)
        leg_m = match(leg_c)
        leg_r = replace(settled(leg_c), outcome=leg.outcome)
        evidence.extend((version(leg_c.version_id, publication_id=leg_c.publication_id),
                         leg_c, leg_m, leg_r))
    assert service.evaluate(c, match(c), r, odds_basis='cote_declaree',
                            leg_evidence=evidence).unit_profit == Decimal('0.5')
    pending = service.settle_combined(c, match(c), result_id='pending',
        observed_at=T + timedelta(hours=4), evidence_sha256=H,
        legs=(replace(legs[0], reglement=None), legs[1]))
    assert pending.outcome == 'en_attente'


def test_postponement_requires_explicit_rule():
    c = contribution()
    assert settled(c, status='reporte').outcome == 'en_attente'
    c = replace(c, reglement=rule(postponed='rembourse'))
    assert settled(c, status='reporte').outcome == 'rembourse'


def test_merge_split_recalculates_and_withdrawal_does_not_improve_roi(tmp_path):
    store = AppendOnlyStore(tmp_path / 'identity.jsonl')
    seed(store)
    second = contribution('c2', author_id='account-b', publication_id='p2', version_id='v2',
                          publication_url='https://example.invalid/p2', selection='away')
    store.append(models.Publication('p2', 's1', second.publication_url))
    store.append(version('v2', publication_id='p2'))
    store.append(second)
    for c in (contribution(), second):
        store.append(match(c))
        r = settled(c)
        store.append(r)
        store.append(service.evaluate(c, match(c), r, odds_basis='cote_declaree'))
    separate = service.rankings(store.entities())
    assert separate['account-a'].net == Decimal('1.4')
    assert separate['account-b'].net == Decimal('-1')
    merge = models.IdentityRevision('merge', None, (
        models.AccountAssignment('account-a', 'merged'),
        models.AccountAssignment('account-b', 'merged')), T + timedelta(hours=5), H, 'preuve',
        certainty='attestee')
    store.append(merge)
    assert service.rankings(store.entities())['merged'].roi == Decimal('0.2')
    store.append(models.IdentityRevision('split', 'merge', (
        models.AccountAssignment('account-a', 'account-a'),
        models.AccountAssignment('account-b', 'account-b')), T + timedelta(hours=6), H, 'erreur fusion',
        certainty='attestee'))
    assert service.rankings(AppendOnlyStore(store.path).entities()) == separate
    store.append(models.Withdrawal('withdraw', 'c2', T + timedelta(hours=7), H, 'retire'))
    after = service.rankings(AppendOnlyStore(store.path).entities())
    assert after['account-b'].roi == Decimal('-1')
    assert after['account-b'].status == 'Comparable suspendu'
    assert after['account-b'].coverage_changed is True


def test_coverage_is_successful_planned_visits_not_publication_recall():
    visits = (models.Visit('visit1', 's1', T, T + timedelta(minutes=1), True),
              models.Visit('visit2', 's1', T, T + timedelta(minutes=2), False),
              models.Visit('visit3', 's1', T, None, False))
    assert service.visit_coverage(visits) == Decimal('1') / 3
    assert service.visit_coverage(()) is None


def test_categories_probability_and_factual_metrics_never_invent_odds():
    c = contribution(categorie='selection_sans_cote', cote_declaree=None,
                     cote_declaree_at=None, cote_declaree_provenance=None)
    e = service.evaluate(c, match(c), settled(c), odds_basis='cote_declaree')
    assert e.unit_profit is None and e.category == 'selection_sans_cote'
    p = replace(c, categorie='probabilite_explicite', probabilite=Decimal('0.8'))
    e = service.evaluate(p, match(p), settled(p), odds_basis='cote_declaree')
    assert e.brier == Decimal('0.04') and e.log_loss is not None
    assert e.unit_profit is None
    with pytest.raises(ValueError):
        replace(p, probabilite=None)
    f = replace(c, categorie='information_factuelle')
    e = service.evaluate(f, match(f), settled(f), odds_basis='cote_declaree')
    assert e.factual_accuracy == Decimal('1') and e.anteriority_seconds == Decimal('7200')


def test_correction_requires_previous_version_and_never_mutates(tmp_path):
    store = AppendOnlyStore(tmp_path / 'correction.jsonl')
    seed(store)
    before = store.path.read_bytes()
    with pytest.raises((ValueError, AppendOnlyViolation)):
        store.append(version('v2', text_sha256='b' * 64))
    assert store.path.read_bytes() == before


def test_pre_match_correction_keeps_all_selections_of_new_version(tmp_path):
    store = AppendOnlyStore(tmp_path / 'slots.jsonl')
    seed(store)
    store.append(version('v2', previous_version_id='v1',
                         modification_observed_at=T + timedelta(minutes=30),
                         usable_at=T + timedelta(minutes=30)))
    c2 = contribution('c2', version_id='v2', selection='away', observed_at=T + timedelta(minutes=30))
    c3 = contribution('c3', version_id='v2', selection='draw', selection_key='selection-2',
                      observed_at=T + timedelta(minutes=30))
    store.append(c2)
    store.append(c3)
    assert service.pre_match_contributions(store.entities(), T + timedelta(hours=2)) == (c2, c3)


def test_withdrawn_unevaluated_publication_suspends_the_author(tmp_path):
    store = AppendOnlyStore(tmp_path / 'withdraw.jsonl')
    seed(store)
    c = contribution()
    store.append(match(c))
    r = settled(c)
    store.append(r)
    store.append(service.evaluate(c, match(c), r, odds_basis='cote_declaree'))
    other = contribution('c2', publication_id='p2', version_id='v2',
                         publication_url='https://example.invalid/p2',
                         observed_at=T + timedelta(hours=4))
    store.append(models.Publication('p2', 's1', other.publication_url))
    store.append(version('v2', publication_id='p2',
                         first_observed_by_robin_at=T + timedelta(hours=4),
                         usable_at=T + timedelta(hours=4)))
    store.append(other)
    store.append(models.Withdrawal('w', 'c2', T + timedelta(hours=5), H, 'retire'))
    assert service.rankings(store.entities())['account-a'].status == 'Comparable suspendu'


def test_calibration_uses_only_explicit_probabilities():
    from robin.source_observatory.ranking import calibration

    p = contribution(categorie='probabilite_explicite', probabilite=Decimal('0.8'))
    e = service.evaluate(p, match(p), settled(p), odds_basis='cote_declaree')
    bins = calibration((p,), (e,))
    assert len(bins) == 1
    assert bins[0].mean_probability == Decimal('0.8')
    assert bins[0].observed_frequency == Decimal('1')


def test_same_match_origins_are_not_independent_matches():
    c1, c2 = contribution(), contribution('c2', publication_id='p2', version_id='v2')
    entities = [version(), version('v2', publication_id='p2'), c1, c2]
    for c in (c1, c2):
        m, r = match(c), settled(c)
        entities.extend((m, r, service.evaluate(c, m, r, odds_basis='cote_declaree')))
    report = service.rankings(entities)['account-a']
    assert report.independent_groups == 2
    assert report.independent_matches == 1


def test_result_rule_version_mismatch_and_quote_after_kickoff_are_excluded():
    c = contribution()
    r = replace(settled(c), reglement=rule(version='2'))
    assert service.evaluate(c, match(c), r, odds_basis='cote_declaree').reason == 'en_attente'
    with pytest.raises(ValueError, match='odds timestamp'):
        replace(c, cote_declaree_at=T + timedelta(hours=3))


def test_cohort_is_fixed_before_evaluation_and_signal_requires_future_holdout():
    from robin.source_observatory.ranking import classification_state

    cohort = models.Cohort('cohort', ('account-a',), T - timedelta(days=2),
        T - timedelta(days=1), T + timedelta(days=1), T + timedelta(days=2),
        T + timedelta(days=3), 2, Decimal('0.8'), H)
    assert classification_state(cohort, at=T, independent_matches=2,
        coverage=Decimal('1'), prospective_matches=0, prospective_coverage=None) == 'En observation'
    assert classification_state(cohort, at=T + timedelta(days=1), independent_matches=2,
        coverage=Decimal('1'), prospective_matches=0, prospective_coverage=None) == 'Comparable'
    assert classification_state(cohort, at=T + timedelta(days=4), independent_matches=2,
        coverage=Decimal('1'), prospective_matches=2,
        prospective_coverage=Decimal('1')) == 'Signal prospectif'
    with pytest.raises(ValueError):
        replace(cohort, defined_at=T)


def test_pending_result_can_be_finalized_by_append_only_correction(tmp_path):
    store = AppendOnlyStore(tmp_path / 'pending.jsonl')
    seed(store)
    c, m = contribution(), match()
    store.append(m)
    pending = replace(settled(), result_id='pending', outcome='en_attente')
    store.append(pending)
    store.append(service.evaluate(c, m, pending, odds_basis='cote_declaree'))
    final = replace(settled(), previous_result_id='pending',
                    observed_at=T + timedelta(hours=5))
    store.append(final)
    store.append(service.evaluate(c, m, final, odds_basis='cote_declaree'))
    report = service.rankings(AppendOnlyStore(store.path).entities())['account-a']
    assert report.stakes == 1 and report.net == Decimal('1.4')


def test_rankings_keep_declared_and_observed_odds_separate():
    c = contribution(cote_observee=Decimal('2.1'), cote_observee_provenance='Robin',
                     cote_observee_at=T)
    m, r = match(c), settled(c)
    entities = [version(), c, m, r]
    for basis in ('cote_declaree', 'cote_observee'):
        entities.append(service.evaluate(c, m, r, odds_basis=basis))
    assert service.rankings(entities, odds_basis='cote_declaree')['account-a'].net == Decimal('1.4')
    assert service.rankings(entities, odds_basis='cote_observee')['account-a'].net == Decimal('1.1')


def test_unsupported_half_outcome_and_mismatched_match_cannot_score():
    c = contribution()
    r = replace(settled(), outcome='demi_gagne')
    assert service.evaluate(c, match(c), r, odds_basis='cote_declaree').reason == 'en_attente'
    with pytest.raises(ValueError):
        service.evaluate(c, match(c, match_id='wrong'), settled(), odds_basis='cote_declaree')


def test_corrections_of_settled_result_need_audit_evidence(tmp_path):
    store = AppendOnlyStore(tmp_path / 'audited.jsonl')
    seed(store)
    store.append(match())
    store.append(settled())
    with pytest.raises(AppendOnlyViolation):
        store.append(replace(settled(), result_id='corrected', previous_result_id='r:c1',
                             outcome='perdu', observed_at=T + timedelta(hours=5)))
    store.append(replace(settled(), result_id='corrected', previous_result_id='r:c1',
        outcome='perdu', observed_at=T + timedelta(hours=5), audit_evidence_sha256='b' * 64))
    assert len(AppendOnlyStore(store.path).entities()) == 7


def test_unknown_origins_and_cyclic_links_remain_explicitly_unresolved():
    from robin.source_observatory.ranking import origin_groups

    a, b = contribution(), contribution('c2', publication_id='p2')
    assert all(g.origin_publication_id is None and g.statut == 'non_resolu'
               for g in origin_groups((a, b)))
    a = replace(a, liens_reprise=(models.RepriseLink('p2', 'attestee', H),))
    b = replace(b, liens_reprise=(models.RepriseLink('p1', 'attestee', H),))
    group, = origin_groups((a, b))
    assert group.statut == 'non_resolu'
    b = replace(b, liens_reprise=())
    group, = origin_groups((a, b))
    assert group.origin_publication_id == 'p2' and group.statut == 'resolu'


def test_cohort_and_visit_are_persisted_before_any_evaluation(tmp_path):
    store = AppendOnlyStore(tmp_path / 'cohort.jsonl')
    cohort = models.Cohort('cohort', ('account-a',), T - timedelta(days=2),
        T - timedelta(days=1), T + timedelta(days=1), T + timedelta(days=2),
        T + timedelta(days=3), 2, Decimal('0.8'), H)
    store.append(cohort)
    seed(store)
    visit = models.Visit('visit', 's1', T, T + timedelta(minutes=1), True)
    store.append(visit)
    restored = AppendOnlyStore(store.path).entities()
    assert restored[0] == cohort and restored[-1] == visit
    c, m, r = contribution(), match(), settled()
    store.append(m)
    store.append(r)
    store.append(service.evaluate(c, m, r, odds_basis='cote_declaree'))
    with pytest.raises(ValueError, match='before observations|backdated'):
        store.append(replace(cohort, cohort_id='late'))


def test_schema_accepts_only_permitted_excerpt_and_complete_evidence_metadata():
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker

    path = Path(__file__).parents[2] / 'src/robin/source_observatory/schemas/contribution.schema.json'
    validator = Draft202012Validator(json.loads(path.read_text(encoding='utf-8')),
                                    format_checker=FormatChecker())
    data = contribution().extraction_metadata()
    validator.validate(data)
    for bad in (data | {'author_id': ''}, data | {'publication_id': None},
                data | {'preuve_permise': None}, data | {'certitude_rapprochement': 'inventee'},
                data | {'cote_declaree_at': None}, data | {'extra': 'forbidden'},
                data | {'liens_reprise': [{'publication_id': 'p2', 'certainty': 'attestee',
                                          'evidence_sha256': None}]}):
        assert not validator.is_valid(bad)
