"""Adversarial regressions for the independent PR 127 review."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from robin.source_observatory import models, service
from robin.source_observatory.store import AppendOnlyStore

from .test_conception import H, T, contribution, match, rule, seed, settled, version


def evaluated(c, *, won=True, **match_changes):
    m = match(c, **(dict(selection_id=c.selection) | match_changes))
    r = replace(settled(c), match_market_id=m.match_market_id,
                observed_at=m.match_usable_at + timedelta(hours=2),
                outcome='gagne' if won else 'perdu')
    return m, r, service.evaluate(c, m, r, odds_basis='cote_declaree')


@pytest.mark.parametrize('withdrawal', [False, True])
def test_omitted_loser_still_costs_one_unit_and_suspends_comparability(withdrawal):
    loser = contribution()
    winner = contribution('winner', selection_key='second', selection='away')
    corrected = version('v2', previous_version_id='v1',
        modification_observed_at=T + timedelta(hours=1), usable_at=T + timedelta(hours=1))
    replacement = replace(winner, contribution_id='replacement', version_id='v2')
    entities = [version(), loser, winner, corrected, replacement,
                *evaluated(loser, won=False), *evaluated(winner), *evaluated(replacement)]
    if withdrawal:
        entities.append(models.Withdrawal('withdrawal', 'c1', T + timedelta(hours=1), H, 'retire'))
    report = service.rankings(entities)['account-a']
    assert (report.net, report.stakes, report.roi) == (Decimal('0.4'), 2, Decimal('0.2'))
    assert report.status == 'Comparable suspendu'


def test_withdrawn_author_remains_visible_without_evaluation():
    entities = [version(), contribution(), models.Withdrawal('w', 'c1', T, H, 'retire')]
    report = service.rankings(entities)['account-a']
    assert report.status == 'Comparable suspendu'
    assert report.roi is None


def test_latest_result_without_evaluation_cannot_silently_remove_loss():
    c = contribution()
    m, r, e = evaluated(c, won=False)
    corrected = replace(r, result_id='corrected', previous_result_id=r.result_id,
                        audit_evidence_sha256=H)
    with pytest.raises(ValueError, match='evaluation'):
        service.rankings([version(), c, m, r, e, corrected])


def test_second_match_market_cannot_bypass_result_audit(tmp_path):
    store = AppendOnlyStore(tmp_path / 'duplicate.jsonl')
    seed(store)
    store.append(match())
    store.append(replace(settled(), outcome='perdu'))
    with pytest.raises(ValueError):
        store.append(replace(match(), match_market_id='mm2'))


def test_contribution_cannot_be_backdated_after_result(tmp_path):
    store = AppendOnlyStore(tmp_path / 'late.jsonl')
    seed(store)
    store.append(match())
    store.append(settled())
    with pytest.raises(ValueError):
        store.append(contribution('late', selection_key='second'))


def test_version_cannot_be_backdated_after_result(tmp_path):
    store = AppendOnlyStore(tmp_path / 'late-version.jsonl')
    seed(store)
    store.append(match())
    store.append(settled())
    with pytest.raises(ValueError):
        store.append(version('v2', previous_version_id='v1',
            modification_observed_at=T + timedelta(hours=1), usable_at=T + timedelta(hours=1)))


def test_correction_requires_observed_modification():
    with pytest.raises(ValueError):
        version('v2', previous_version_id='v1')


def test_correction_must_advance_usable_time(tmp_path):
    store = AppendOnlyStore(tmp_path / 'equal-time.jsonl')
    seed(store)
    with pytest.raises(ValueError):
        store.append(version('v2', previous_version_id='v1', modification_observed_at=T))


def test_identity_merge_requires_explicit_certainty():
    with pytest.raises(ValueError):
        models.IdentityRevision('revision', None, (
            models.AccountAssignment('account-a', 'same'),
            models.AccountAssignment('account-b', 'same')), T, H, 'pseudo similaire')


def test_cohort_cannot_be_chosen_after_results_even_before_evaluation(tmp_path):
    store = AppendOnlyStore(tmp_path / 'late-cohort.jsonl')
    seed(store)
    store.append(match())
    store.append(settled())
    cohort = models.Cohort('cohort', ('account-a',), T - timedelta(days=2),
        T - timedelta(days=1), T + timedelta(days=1), T + timedelta(days=2),
        T + timedelta(days=3), 2, Decimal('0.8'), H)
    with pytest.raises(ValueError):
        store.append(cohort)


@pytest.mark.parametrize('market,line', [('1N2', '-1.5'), ('1X2', '1'),
    ('qualification', '1'), ('total', '-2.5')])
def test_ignored_or_impossible_line_stays_pending(market, line):
    c = contribution(marche=market, reglement=rule(market), ligne=Decimal(line),
                     selection='over' if market == 'total' else 'home')
    r = settled(c, qualified='home')
    assert r.outcome == 'en_attente'
    forged = replace(r, outcome='gagne')
    assert service.evaluate(c, match(c), forged, odds_basis='cote_declaree').reason == 'en_attente'


def test_single_leg_combo_stays_pending():
    c = contribution(marche='combine', reglement=rule('combine'))
    legs = (models.SettlementLeg('leg', Decimal('2.4'), 'gagne', rule()),)
    r = service.settle_combined(c, match(c), result_id='combo', observed_at=T + timedelta(hours=4),
                               evidence_sha256=H, legs=legs)
    assert r.outcome == 'en_attente'


def test_combined_cannot_profit_from_unproven_or_contradictory_legs(tmp_path):
    c = contribution(marche='combine', reglement=rule('combine'), cote_declaree=Decimal('4'))
    legs = tuple(models.SettlementLeg(key, Decimal('2'), 'gagne', rule()) for key in ('a', 'b'))
    r = models.Result('combo', match(c).match_market_id, 'perdu', T + timedelta(hours=4),
                      H, rule('combine'), legs)
    assert service.evaluate(c, match(c), r, odds_basis='cote_declaree').reason == 'en_attente'
    store = AppendOnlyStore(tmp_path / 'legs.jsonl')
    seed(store, c=c)
    store.append(match(c))
    with pytest.raises(ValueError):
        store.append(replace(r, outcome='gagne'))


@pytest.mark.parametrize('lengths', [(300, 201), (500,) * 40])
def test_sliced_payload_cannot_evade_total_excerpt_limit(lengths):
    excerpts = []
    start = 0
    for length in lengths:
        excerpts.append(models.EvidenceExcerpt(H, start, start + length, 'x' * length))
        start += length
    with pytest.raises(ValueError):
        contribution(extraits_preuve=tuple(excerpts))


def test_schema_blocks_sliced_payload_and_blank_excerpt():
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    schema = Path(__file__).parents[2] / 'src/robin/source_observatory/schemas/contribution.schema.json'
    validator = Draft202012Validator(json.loads(schema.read_text(encoding='utf-8')))
    data = contribution().extraction_metadata()
    validator.validate(data)
    for excerpts in ([dict(text_sha256=H, start=0, end=500, text='x' * 500)] * 40,
                     [dict(text_sha256=H, start=0, end=3, text='   ')]):
        assert not validator.is_valid(data | {'extraits_preuve': excerpts})


def test_roi_deduplicates_attested_reprises_across_intermediate_author():
    loser = contribution('loser', publication_id='loss', version_id='loss-v')
    origin = contribution('origin')
    bridge = contribution('bridge', publication_id='bridge', version_id='bridge-v',
        author_id='other', liens_reprise=(models.RepriseLink('p1', 'attestee', H),))
    copies = [contribution(f'copy-{i}', publication_id=f'copy-{i}', version_id=f'copy-v-{i}',
        liens_reprise=(models.RepriseLink('bridge', 'attestee', H),)) for i in range(10)]
    cs = [loser, origin, bridge, *copies]
    entities = [version(c.version_id, publication_id=c.publication_id) for c in cs] + cs
    for c in (loser, origin, *copies):
        entities.extend(evaluated(c, won=c != loser))
    report = service.rankings(entities)['account-a']
    assert (report.net, report.stakes, report.roi) == (Decimal('0.4'), 2, Decimal('0.2'))
    assert report.independent_groups == 2


def test_cycle_with_external_root_is_still_unresolved():
    from robin.source_observatory.ranking import origin_groups

    a = contribution(liens_reprise=(models.RepriseLink('p2', 'attestee', H),))
    b = contribution('b', publication_id='p2', liens_reprise=(
        models.RepriseLink('p1', 'attestee', H), models.RepriseLink('p0', 'attestee', H)))
    group, = origin_groups((a, b))
    assert group.statut == 'non_resolu' and group.origin_publication_id is None


@pytest.mark.parametrize('category,extra', [
    ('probabilite_explicite', dict(probabilite=Decimal('0.8'))), ('information_factuelle', {})])
def test_nonpriced_metrics_do_not_depend_on_odds_basis(category, extra):
    c = contribution(categorie=category, cote_declaree=None, cote_declaree_provenance=None,
                     cote_declaree_at=None, **extra)
    entities = [version(), c, *evaluated(c)]
    report = service.rankings(entities, odds_basis='cote_observee')['account-a']
    if category == 'probabilite_explicite':
        assert report.brier == Decimal('0.04')
    else:
        assert report.factual_accuracy == Decimal(1)


def test_resolved_mapping_requires_same_explicit_contribution_match(tmp_path):
    c = contribution(match_id=None, certitude_rapprochement='non_resolue')
    store = AppendOnlyStore(tmp_path / 'match-identity.jsonl')
    seed(store, c=c)
    with pytest.raises(ValueError):
        store.append(match(c))


def test_rankings_derive_cohort_state_from_journal_windows_and_visits():
    cohort = models.Cohort('cohort', ('account-a',), T - timedelta(days=2),
        T - timedelta(days=1), T + timedelta(days=1), T + timedelta(days=2),
        T + timedelta(days=3), 1, Decimal('0.8'), H)
    c = contribution()
    entities = [cohort, version(), c, *evaluated(c),
                models.Visit('visit', 's1', T, T + timedelta(minutes=1), True)]
    at = T + timedelta(days=4)
    report = service.rankings(entities, at=at)['account-a']
    assert report.status == 'Comparable'
    future = T + timedelta(days=2, hours=1)
    prospective = contribution('future', publication_id='future', version_id='future-v',
                              match_id='m2', observed_at=future, cote_declaree_at=future)
    entities.extend([version('future-v', publication_id='future',
        first_observed_by_robin_at=future, usable_at=future), prospective,
        *evaluated(prospective, match_id='m2', contribution_usable_at=future,
                   match_usable_at=future + timedelta(hours=2)),
        models.Visit('future-visit', 's1', future, future + timedelta(minutes=1), True)])
    assert service.rankings(entities, at=at)['account-a'].status == 'Signal prospectif'
    failed_visit = models.Visit('failed', 's1', future, future + timedelta(minutes=1), False)
    assert service.rankings([*entities, failed_visit], at=at)['account-a'].status == 'Comparable'
    unrelated = replace(failed_visit, visit_id='other-source', source_id='unrelated')
    assert service.rankings([*entities, unrelated], at=at)['account-a'].status == 'Comparable'


def test_historical_report_ignores_future_contributions_and_corrections():
    c = contribution()
    future = contribution('future', publication_id='future', version_id='future-v',
                          observed_at=T + timedelta(days=2))
    entities = [version(), c, *evaluated(c),
        version('future-v', publication_id='future', first_observed_by_robin_at=future.observed_at,
                usable_at=future.observed_at), future,
        *evaluated(future, contribution_usable_at=future.observed_at,
                   match_usable_at=future.observed_at + timedelta(hours=2))]
    report = service.rankings(entities, at=T + timedelta(days=1))['account-a']
    assert report.net == Decimal('1.4') and report.stakes == 1


def test_distinct_categories_on_same_selection_keep_both_metrics():
    c = contribution()
    p = contribution('probability', selection_key='probability', categorie='probabilite_explicite',
                     probabilite=Decimal('0.8'))
    entities = [version(), c, p, *evaluated(c), *evaluated(p)]
    report = service.rankings(entities)['account-a']
    assert report.brier == Decimal('0.04') and report.net == Decimal('1.4')


@pytest.mark.parametrize('offset', [2, 4])
def test_new_contribution_at_or_after_kickoff_is_retrospective(tmp_path, offset):
    store = AppendOnlyStore(tmp_path / 'retrospective.jsonl')
    seed(store)
    store.append(match())
    if offset == 4:
        store.append(settled())
    c = contribution('late', selection_key='second', observed_at=T + timedelta(hours=offset))
    store.append(c)
    m = match(c, contribution_usable_at=c.observed_at)
    store.append(m)
    r = replace(settled(c), observed_at=T + timedelta(hours=5))
    store.append(r)
    e = service.evaluate(c, m, r, odds_basis='cote_declaree')
    store.append(e)
    assert e.reason == 'invalide_pre_match' and e.unit_profit is None
    assert c not in service.pre_match_contributions(store.entities(), T + timedelta(hours=2))


def test_similarity_revision_cannot_alias_an_existing_account():
    a = contribution()
    b = contribution('b', author_id='account-b', publication_id='p2', version_id='v2')
    with pytest.raises(ValueError):
        models.IdentityRevision('similar', None,
            (models.AccountAssignment('account-b', 'account-a'),), T, H, 'pseudo similaire',
            certainty='similarite')
    entities = [version(), version('v2', publication_id='p2'), a, b,
                *evaluated(a), *evaluated(b, won=False)]
    report = service.rankings(entities)
    assert set(report) == {'account-a', 'account-b'}
    assert report['account-b'].net == Decimal('-1')


def test_reprise_keeps_its_own_source_after_persistence(tmp_path):
    from robin.source_observatory.ranking import origin_groups

    store = AppendOnlyStore(tmp_path / 'sources.jsonl')
    seed(store)
    store.append(models.Source('robin', 'Robin', 'https://example.invalid/robin'))
    store.append(models.Publication('copy', 'robin', 'https://example.invalid/copy'))
    store.append(version('copy-v', publication_id='copy'))
    copy = contribution('copy', publication_id='copy', version_id='copy-v', source_id='robin',
        publication_url='https://example.invalid/copy',
        liens_reprise=(models.RepriseLink('p1', 'attestee', H),))
    store.append(copy)
    restored = AppendOnlyStore(store.path).entities()
    copies = [e for e in restored if isinstance(e, models.Contribution) and e.contribution_id == 'copy']
    assert copies[0].source_id == 'robin'
    group, = origin_groups(e for e in restored if isinstance(e, models.Contribution))
    assert group.origin_publication_id == 'p1'


def test_cohort_status_is_calculated_from_reopened_journal(tmp_path):
    store = AppendOnlyStore(tmp_path / 'cohort-evidence.jsonl')
    cohort = models.Cohort('cohort', ('account-a',), T - timedelta(days=2),
        T - timedelta(days=1), T + timedelta(days=1), T + timedelta(days=2),
        T + timedelta(days=3), 1, Decimal('0.8'), H)
    store.append(cohort)
    seed(store)
    store.append(models.Visit('visit', 's1', T, T + timedelta(minutes=1), True))
    for entity in evaluated(contribution()):
        store.append(entity)
    entities = AppendOnlyStore(store.path).entities()
    report = service.rankings(entities, at=T + timedelta(days=4))['account-a']
    assert report.status == 'Comparable'


def test_predeclared_cohort_author_is_visible_during_discovery_without_results():
    cohort = models.Cohort('cohort', ('account-a',), T - timedelta(days=2),
        T - timedelta(days=1), T + timedelta(days=1), T + timedelta(days=2),
        T + timedelta(days=3), 1, Decimal('0.8'), H)
    report = service.rankings([cohort], at=T - timedelta(days=1, hours=12))
    assert report['account-a'].status == 'Decouverte'
    assert report['account-a'].stakes == 0 and report['account-a'].roi is None


def test_cohort_cannot_use_other_odds_basis_to_reach_sample_threshold():
    cohort = models.Cohort('cohort', ('account-a',), T - timedelta(days=2),
        T - timedelta(days=1), T + timedelta(days=1), T + timedelta(days=2),
        T + timedelta(days=3), 1, Decimal('0.8'), H)
    c = contribution(cote_declaree=None, cote_declaree_at=None, cote_declaree_provenance=None,
        cote_observee=Decimal('2.4'), cote_observee_at=T, cote_observee_provenance='Robin')
    m, r, e = evaluated(c)
    entities = [cohort, version(), c, m, r, e,
        service.evaluate(c, m, r, odds_basis='cote_observee'),
        models.Visit('visit', 's1', T, T + timedelta(minutes=1), True)]
    assert service.rankings(entities, at=T + timedelta(days=4))['account-a'].status == 'En observation'
