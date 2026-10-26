"""Read-only identity bridge and deterministic paper evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, localcontext

from robin.domain.enums import EntityType
from robin.domain.identity import ProviderIdentity
from robin.identity.service import IdentityConflictError, IdentityService

from .models import (
    Contribution,
    Entity,
    Evaluation,
    MatchMarket,
    OddsBasis,
    PublicationVersion,
    Result,
)
from .settlement import (
    combined_return,
    return_factor,
    settle,
    settle_combined,
    supported,
    supported_line,
)


def resolve_match_market(
    identity: IdentityService,
    contribution: Contribution,
    version: PublicationVersion,
    *,
    fixture: ProviderIdentity,
    market: ProviderIdentity,
    selection: ProviderIdentity,
    match_usable_at: datetime | None,
) -> MatchMarket:
    """Resolve explicit provider IDs as of usability. Never create or name-match."""
    if contribution.version_id != version.version_id or contribution.text_sha256 != version.text_sha256:
        raise ValueError('contribution/version lineage mismatch')
    for reference, expected_type in ((fixture, EntityType.FIXTURE), (market, EntityType.MARKET),
                                     (selection, EntityType.SELECTION)):
        if reference.entity_type != expected_type:
            raise ValueError('wrong provider identity type')
        if reference.valid_from != version.usable_at:
            raise ValueError('identity reference must explicitly use version usable_at')
    match_id = market_id = selection_id = None
    reason = None
    try:
        ids = (identity.resolve(fixture), identity.resolve(market), identity.resolve(selection))
        if any(value is None for value in ids):
            reason = 'identite_absente'
        else:
            match_id, market_id, selection_id = ids
            if match_id != contribution.match_id:
                match_id = market_id = selection_id = None
                reason = 'identite_contribution_incoherente'
    except IdentityConflictError:
        reason = 'identite_ambigue'
    return MatchMarket(
        match_market_id=f'match-market:{contribution.contribution_id}',
        contribution_id=contribution.contribution_id, version_id=version.version_id,
        contribution_usable_at=max(version.usable_at, contribution.observed_at),
        match_usable_at=match_usable_at,
        match_id=match_id, market_id=market_id, selection_id=selection_id,
        statut='resolu' if reason is None else 'non_resolu', raison_non_resolu=reason,
    )


def evaluate(
    contribution: Contribution,
    match: MatchMarket,
    result: Result,
    *,
    odds_basis: OddsBasis,
    leg_evidence: Iterable[Entity] = (),
) -> Evaluation:
    """A unit-stake paper result, always using the explicitly chosen odds field."""
    if (contribution.contribution_id != match.contribution_id
            or contribution.version_id != match.version_id
            or result.match_market_id != match.match_market_id
            or (contribution.match_id is not None and match.match_id is not None
                and contribution.match_id != match.match_id)):
        raise ValueError('evaluation lineage mismatch')
    if odds_basis not in ('cote_declaree', 'cote_observee'):
        raise ValueError('explicit supported odds_basis required')
    odds = contribution.cote_declaree if odds_basis == 'cote_declaree' else contribution.cote_observee
    profit = brier = log_loss = factual_accuracy = anteriority = binary_outcome = None
    reason = None
    if match.statut != 'resolu':
        reason = 'non_resolu'
    elif match.match_usable_at is None:
        reason = 'coup_envoi_inconnu'
    elif not match.pre_match_valid or contribution.observed_at >= match.match_usable_at:
        reason = 'invalide_pre_match'
    elif result.observed_at < match.match_usable_at:
        raise ValueError('result observation precedes kickoff')
    elif (not supported(contribution.reglement, contribution.marche, contribution.periode)
          or not supported_line(contribution)
          or result.reglement != contribution.reglement or result.outcome == 'en_attente'):
        reason = 'en_attente'
    elif result.outcome in ('demi_gagne', 'demi_perdu') and contribution.marche not in (
            'total', 'handicap'):
        reason = 'en_attente'
    elif contribution.certitude_rapprochement != 'certaine':
        reason = 'rapprochement_incertain'
    elif contribution.categorie == 'probabilite_explicite':
        if result.outcome not in ('gagne', 'perdu'):
            reason = 'en_attente'
        else:
            if contribution.probabilite is None:
                raise ValueError('probabilite_explicite sans probabilite')
            p = contribution.probabilite
            with localcontext() as context:
                context.prec = max(28, len(p.as_tuple().digits) * 2 + 8)
                y = Decimal(1) if result.outcome == 'gagne' else Decimal(0)
                binary_outcome = y
                brier = (p - y) ** 2
                likelihood = p if y else 1 - p
                log_loss = -likelihood.ln() if likelihood else Decimal('Infinity')
    elif contribution.categorie == 'information_factuelle':
        if result.outcome in ('gagne', 'perdu'):
            factual_accuracy = Decimal(1) if result.outcome == 'gagne' else Decimal(0)
            delta = match.match_usable_at - match.contribution_usable_at
            anteriority = Decimal(delta.days * 86400 + delta.seconds) + (
                Decimal(delta.microseconds) / 1000000)
        else:
            reason = 'en_attente'
    elif odds is None or contribution.categorie == 'selection_sans_cote':
        reason = 'cote_absente'
    elif contribution.cote_observee_at is not None and odds_basis == 'cote_observee' and (
            contribution.cote_observee_at >= match.match_usable_at):
        reason = 'cote_tardive'
    elif contribution.cote_declaree_at is not None and odds_basis == 'cote_declaree' and (
            contribution.cote_declaree_at >= match.match_usable_at):
        reason = 'cote_tardive'
    else:
        with localcontext() as context:
            context.prec = max(28, len(odds.as_tuple().digits) + abs(odds.adjusted()) + 8,
                               sum(len(leg.odds.as_tuple().digits) + 8
                                   for leg in result.legs if leg.odds is not None))
            if contribution.marche == 'combine':
                factor = combined_return(result.legs)
                quoted = Decimal(1)
                for leg in result.legs:
                    if leg.odds is not None:
                        quoted *= leg.odds
                outcome = ('gagne' if factor is not None and factor > 1 else
                           'perdu' if factor is not None and factor < 1 else 'rembourse')
                if (factor is None or quoted != odds or outcome != result.outcome
                        or not combined_legs_proven(result, leg_evidence, odds_basis)):
                    reason = 'en_attente'
                else:
                    profit = factor - 1
            elif result.legs:
                reason = 'en_attente'
            else:
                factor = return_factor(result.outcome, odds)
                if factor is not None:
                    profit = factor - 1
    return Evaluation(
        evaluation_id=f'evaluation:{contribution.contribution_id}:{result.result_id}:{odds_basis}',
        contribution_id=contribution.contribution_id, match_market_id=match.match_market_id,
        result_id=result.result_id, odds_basis=odds_basis, odds_used=odds,
        unit_profit=profit, reason=reason,
        category=contribution.categorie, brier=brier, log_loss=log_loss,
        factual_accuracy=factual_accuracy, anteriority_seconds=anteriority,
        binary_outcome=binary_outcome,
    )


def combined_legs_proven(result: Result, evidence: Iterable[Entity], basis: OddsBasis) -> bool:
    """Each leg needs its own pre-match contribution and latest observed settlement."""
    items = tuple(evidence)
    cs = {e.contribution_id: e for e in items if isinstance(e, Contribution)}
    ms = {e.contribution_id: e for e in items if isinstance(e, MatchMarket)}
    rs = {e.match_market_id: e for e in items if isinstance(e, Result)}
    if len(result.legs) < 2:
        return False
    for leg in result.legs:
        c, m = cs.get(leg.contribution_id), ms.get(leg.contribution_id)
        if c is None or m is None or c.marche == 'combine' or m.match_usable_at is None:
            return False
        r = rs.get(m.match_market_id)
        if (r is None or r.observed_at > result.observed_at or leg.reglement != c.reglement
                or r.reglement != leg.reglement or r.outcome != leg.outcome
                or getattr(c, basis) != leg.odds
                or c not in pre_match_contributions(items, m.match_usable_at)):
            return False
        if not evaluate(c, m, r, odds_basis=basis).evaluable:
            return False
    return True


# Public domain services are also available from this original entry point.
from .ranking import (  # noqa: E402
    pre_match_contributions,
    rankings,
    reprise_groups,
    visit_coverage,
)

__all__ = ['evaluate', 'resolve_match_market', 'settle', 'settle_combined',
           'pre_match_contributions', 'rankings', 'reprise_groups', 'visit_coverage']
