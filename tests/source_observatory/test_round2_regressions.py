"""Counterexamples from Gemini round 2, using synthetic evidence only."""

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from robin.source_observatory import models, service
from robin.source_observatory.ranking import reprise_groups
from robin.source_observatory.store import AppendOnlyStore

from .test_conception import H, T, contribution, match, rule, seed, version
from .test_review_regressions import evaluated


def test_r2_1_distinct_lines_keep_loss():
    a = contribution(marche='total', selection='over', ligne=Decimal('1.5'),
                     reglement=rule('total'), cote_declaree=Decimal('1.5'))
    b = replace(a, contribution_id='b', selection_key='b', ligne=Decimal('3.5'))
    report = service.rankings([version(), a, b, *evaluated(a), *evaluated(b, won=False)])['account-a']
    assert (report.net, report.stakes, report.roi) == (Decimal('-.5'), 2, Decimal('-.25'))


def test_r2_1_unpriced_basis_cannot_mask_priced_loss():
    a = contribution(cote_declaree=None, cote_declaree_at=None, cote_declaree_provenance=None,
                     cote_observee=Decimal('2'), cote_observee_at=T,
                     cote_observee_provenance='Robin', selection='away')
    b = contribution('b', publication_id='p2', version_id='v2', selection='away',
                     observed_at=T + timedelta(minutes=1),
                     liens_reprise=(models.RepriseLink('p1', 'attestee', H),))
    entities = [version(), version('v2', publication_id='p2'), a, b,
                *evaluated(a, won=False), *evaluated(b, won=False)]
    report = service.rankings(entities)['account-a']
    assert (report.net, report.stakes) == (Decimal('-1'), 1)


@pytest.mark.parametrize('downgrade', ['odds', 'certainty', 'status', 'match'])
def test_r2_2_neutralizing_or_shifting_slot_never_erases_loss(downgrade):
    loser = contribution(selection='away')
    winner = contribution('winner', selection_key='s2', match_id='m2')
    v2 = version('v2', previous_version_id='v1', modification_observed_at=T + timedelta(minutes=30),
                 usable_at=T + timedelta(minutes=30))
    changes = {
        'odds': dict(cote_declaree=None, cote_declaree_at=None, cote_declaree_provenance=None,
                     categorie='selection_sans_cote'),
        'certainty': dict(certitude_rapprochement='probable'),
        'status': dict(statut='non_resolu', raison_non_resolu='ambigu'),
        'match': dict(match_id='m2', selection='home'),
    }[downgrade]
    neutral = replace(loser, contribution_id='neutral', version_id='v2',
                      observed_at=v2.usable_at, **changes)
    entities = [version(), loser, winner, v2, neutral,
                *evaluated(loser, won=False), *evaluated(winner, match_id='m2'),
                *evaluated(neutral, contribution_usable_at=v2.usable_at,
                           match_id=neutral.match_id)]
    report = service.rankings(entities)['account-a']
    assert (report.net, report.stakes, report.roi) == (Decimal('.4'), 2, Decimal('.2'))
    assert report.coverage_changed


def test_r2_2_withdrawn_without_result_must_block_report():
    loser = contribution(selection='away')
    winner = contribution('winner', selection_key='s2', match_id='m2')
    entities = [version(), loser, winner, match(loser),
                models.Withdrawal('w', 'c1', T + timedelta(minutes=30), H, 'retire'),
                *evaluated(winner, match_id='m2')]
    with pytest.raises(ValueError, match='result|evaluation'):
        service.rankings(entities)


def combo_evidence(*, late=False, other=False):
    legs = [contribution('leg1', selection_key='leg1', cote_declaree=Decimal('2'),
                         author_id='other' if other else 'account-a'),
            contribution('leg2', selection_key='leg2', match_id='m2', cote_declaree=Decimal('2'),
                         author_id='other' if other else 'account-a')]
    evidence = [version(), *legs]
    for i, leg in enumerate(legs):
        evidence.extend(evaluated(leg, match_id=leg.match_id,
                                 match_usable_at=T + timedelta(hours=1 + i * 3)))
    observed = T + timedelta(hours=3) if late else T
    combo = contribution('combo', selection_key='combo', marche='combine',
                         reglement=rule('combine'), cote_declaree=Decimal('4'), observed_at=observed)
    m = match(combo, contribution_usable_at=observed, match_usable_at=T + timedelta(hours=4))
    r = models.Result('combo-result', m.match_market_id, 'gagne', T + timedelta(hours=7), H,
                      combo.reglement, tuple(models.SettlementLeg(c.contribution_id,
                          c.cote_declaree, 'gagne', c.reglement) for c in legs))
    return combo, m, r, evidence


@pytest.mark.parametrize('late,other', [(True, False), (False, True)])
def test_r2_3_combo_requires_each_leg_prematch_and_same_author(late, other):
    c, m, r, evidence = combo_evidence(late=late, other=other)
    assert not service.evaluate(c, m, r, odds_basis='cote_declaree',
                                leg_evidence=evidence).evaluable


def test_r2_3_corrected_losing_leg_invalidates_stale_combo_then_recalculates():
    c, m, r, evidence = combo_evidence()
    e = service.evaluate(c, m, r, odds_basis='cote_declaree', leg_evidence=evidence)
    leg = next(x for x in evidence if isinstance(x, models.Contribution))
    lm = next(x for x in evidence if isinstance(x, models.MatchMarket))
    lr = next(x for x in evidence if isinstance(x, models.Result))
    correction = replace(lr, result_id='corrected-leg', outcome='perdu',
                         observed_at=r.observed_at + timedelta(hours=1),
                         previous_result_id=lr.result_id, audit_evidence_sha256=H)
    evidence.extend([c, m, r, e, correction,
                     service.evaluate(leg, lm, correction, odds_basis='cote_declaree')])
    with pytest.raises(ValueError, match='combin|leg'):
        service.rankings(evidence)
    fixed = replace(r, result_id='corrected-combo', previous_result_id=r.result_id,
                    audit_evidence_sha256=H, observed_at=correction.observed_at,
                    outcome='perdu', legs=(replace(r.legs[0], outcome='perdu'), r.legs[1]))
    fixed_e = service.evaluate(c, m, fixed, odds_basis='cote_declaree', leg_evidence=evidence)
    assert fixed_e.unit_profit == Decimal('-1')
    evidence.extend([fixed, fixed_e])
    assert service.rankings(evidence)['account-a'].net == Decimal('-1')  # -1 +1 -1


def cohort():
    return models.Cohort('cohort', ('account-a',), T - timedelta(days=2),
        T - timedelta(days=1), T + timedelta(days=1), T + timedelta(days=2),
        T + timedelta(days=3), 1, Decimal('.8'), H)


def test_r2_4_all_planned_sources_including_empty_failures_count():
    c = contribution()
    entities = [cohort(), version(), c, *evaluated(c), models.Visit('ok', 's1', T, T, True)]
    entities.extend(models.Visit(f'fail-{i}', 's2', T, T, False) for i in range(10))
    assert service.rankings(entities, at=T + timedelta(days=4))['account-a'].status == 'En observation'


def test_r2_4_default_time_cannot_ignore_cohort():
    assert service.rankings([cohort()])['account-a'].status == 'Decouverte'


@pytest.mark.parametrize('kind', ['visit', 'withdrawal', 'identity', 'cohort'])
def test_r2_5_observations_cannot_backdate_after_any_timestamped_entity(tmp_path, kind):
    store = AppendOnlyStore(tmp_path / 'journal.jsonl')
    seed(store)
    later = T + timedelta(hours=4)
    entities = dict(
        visit=models.Visit('visit', 's1', later, later, False),
        withdrawal=models.Withdrawal('w', 'c1', later, H, 'retire'),
        identity=models.IdentityRevision('id', None, (models.AccountAssignment('account-a',
                   'account-a'),), later, H, 'atteste', 'attestee'),
        cohort=replace(cohort(), defined_at=later, evaluation_starts_at=later + timedelta(days=1),
                       evaluation_ends_at=later + timedelta(days=2),
                       prospective_starts_at=later + timedelta(days=3),
                       prospective_ends_at=later + timedelta(days=4)),
    )
    store.append(entities[kind])
    with pytest.raises(ValueError, match='backdat|observation'):
        store.append(contribution('late', selection_key='late'))


@pytest.mark.parametrize('basis', ['cote_declaree', 'cote_observee'])
def test_r2_5_odds_time_cannot_exceed_contribution_observation(basis):
    with pytest.raises(ValueError):
        contribution(**{basis: Decimal('2'), basis + '_provenance': 'preuve',
                         basis + '_at': T + timedelta(minutes=1)})


def test_r2_5_observed_odds_cannot_precede_first_observation(tmp_path):
    store = AppendOnlyStore(tmp_path / 'odds.jsonl')
    with pytest.raises(ValueError):
        seed(store, c=contribution(cote_observee=Decimal('2'), cote_observee_provenance='Robin',
                                  cote_observee_at=T - timedelta(hours=1)))


def test_r2_6_similarity_single_alias_is_refused():
    with pytest.raises(ValueError):
        models.IdentityRevision('id', None, (models.AccountAssignment('account-b', 'account-a'),),
                                T, H, 'pseudo similaire', 'similarite')


def test_r2_6_partial_revision_is_complete_snapshot_not_overlay():
    a = contribution()
    b = contribution('b', author_id='account-b', publication_id='p2', version_id='v2')
    merge = models.IdentityRevision('merge', None, tuple(models.AccountAssignment(x, 'merged')
        for x in ('account-a', 'account-b')), T, H, 'preuve', 'attestee')
    split = models.IdentityRevision('split', 'merge',
        (models.AccountAssignment('account-a', 'account-a'),), T, H, 'correction', 'attestee')
    report = service.rankings([version(), version('v2', publication_id='p2'), a, b,
                              *evaluated(a), *evaluated(b, won=False), merge, split])
    assert set(report) == {'account-a', 'account-b'}
    assert report['account-b'].net == Decimal('-1')


def test_r2_7_origin_label_is_not_intermediate_relay():
    origin = contribution(publication_id='pub-origin')
    relay = contribution('relay', publication_id='aaa-relay',
        liens_reprise=(models.RepriseLink('pub-origin', 'attestee', H),))
    copy = contribution('copy', publication_id='zzz-copy',
        liens_reprise=(models.RepriseLink('aaa-relay', 'attestee', H),))
    assert set(reprise_groups([origin, relay, copy])) == {'pub-origin'}


def test_r2_8_priced_category_requires_odds_model_and_schema():
    data = contribution().extraction_metadata() | {
        'cote_declaree': None, 'cote_declaree_provenance': None, 'cote_declaree_at': None}
    schema = Path('src/robin/source_observatory/schemas/contribution.schema.json')
    assert not Draft202012Validator(json.loads(schema.read_text(encoding='utf-8'))).is_valid(data)
    with pytest.raises(ValueError):
        contribution(cote_declaree=None, cote_declaree_provenance=None, cote_declaree_at=None)


def test_r2_8_category_count_uses_selected_evaluable_basis():
    c = contribution(cote_declaree=None, cote_declaree_provenance=None, cote_declaree_at=None,
                     cote_observee=Decimal('2'), cote_observee_at=T,
                     cote_observee_provenance='Robin')
    report = service.rankings([version(), c, *evaluated(c)])['account-a']
    assert ('selection_avec_cote', 1) not in report.categories
