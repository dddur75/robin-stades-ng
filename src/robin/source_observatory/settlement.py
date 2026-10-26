"""Documented paper settlements. Unsupported semantics always remain pending."""

from datetime import datetime
from decimal import Decimal, localcontext

from .models import (
    Contribution,
    MatchMarket,
    MatchScore,
    Outcome,
    Result,
    SettlementLeg,
    SettlementRule,
)


def supported(rule: SettlementRule | None, market: str, period: str) -> bool:
    return (rule is not None and rule.market == market and rule.period == period
            and period == 'reglementaire'
            and market in ('1N2', '1X2', 'qualification', 'total', 'handicap', 'combine'))


def return_factor(outcome: Outcome, odds: Decimal) -> Decimal | None:
    """Return includes the stake. Caller supplies adequate Decimal precision."""
    return {'gagne': odds, 'perdu': Decimal(0), 'rembourse': Decimal(1),
            'void': Decimal(1), 'demi_gagne': (odds + 1) / 2,
            'demi_perdu': Decimal('0.5'), 'en_attente': None}[outcome]


def _line_outcome(margin: Decimal, line: Decimal) -> Outcome:
    if line % Decimal('0.25'):
        return 'en_attente'
    # Quarter lines split the unit stake equally over adjacent half-lines.
    margins = (margin - Decimal('0.25'), margin + Decimal('0.25')) if (
        line % Decimal('0.5')) else (margin, margin)
    signs = tuple(1 if value > 0 else -1 if value < 0 else 0 for value in margins)
    return {2: 'gagne', 1: 'demi_gagne', 0: 'rembourse',
            -1: 'demi_perdu', -2: 'perdu'}[sum(signs)]  # type: ignore[return-value]


def settle(
    contribution: Contribution, match: MatchMarket, *, result_id: str,
    observed_at: datetime, evidence_sha256: str, score: MatchScore,
) -> Result:
    if contribution.contribution_id != match.contribution_id:
        raise ValueError('settlement contribution mismatch')
    rule = contribution.reglement
    market, selection, line = contribution.marche, contribution.selection, contribution.ligne
    outcome: Outcome = 'en_attente'
    if supported(rule, market, contribution.periode):
        assert rule is not None
        if score.status == 'reporte':
            outcome = rule.postponed
        elif score.status == 'termine':
            if market == 'qualification' and score.qualified is not None:
                if selection in ('home', 'away'):
                    outcome = 'gagne' if selection == score.qualified else 'perdu'
            elif score.home is not None and score.away is not None:
                if market in ('1N2', '1X2') and selection in ('home', 'away', 'draw'):
                    winner = ('home' if score.home > score.away else
                              'away' if score.home < score.away else 'draw')
                    outcome = 'gagne' if selection == winner else 'perdu'
                elif line is not None:
                    with localcontext() as context:
                        context.prec = max(28, len(line.as_tuple().digits) + abs(line.adjusted()) + 8)
                        if market == 'total' and selection in ('over', 'under'):
                            margin = Decimal(score.home + score.away) - line
                            if selection == 'under':
                                margin = -margin
                            outcome = _line_outcome(margin, line)
                        elif market == 'handicap' and selection in ('home', 'away'):
                            diff = (score.home - score.away if selection == 'home'
                                    else score.away - score.home)
                            outcome = _line_outcome(Decimal(diff) + line, line)
    return Result(result_id, match.match_market_id, outcome, observed_at, evidence_sha256, rule)


def combined_return(legs: tuple[SettlementLeg, ...]) -> Decimal | None:
    if not legs:
        return None
    value = Decimal(1)
    for leg in legs:
        rule = leg.reglement
        if (rule is None or not supported(rule, rule.market, rule.period)
                or rule.market == 'combine' or leg.odds is None):
            return None
        factor = return_factor(leg.outcome, leg.odds)
        if factor is None:
            return None
        value *= factor
    return value


def settle_combined(
    contribution: Contribution, match: MatchMarket, *, result_id: str,
    observed_at: datetime, evidence_sha256: str, legs: tuple[SettlementLeg, ...],
) -> Result:
    if contribution.contribution_id != match.contribution_id:
        raise ValueError('settlement contribution mismatch')
    outcome: Outcome = 'en_attente'
    if supported(contribution.reglement, 'combine', contribution.periode) and (
            contribution.marche == 'combine'):
        with localcontext() as context:
            context.prec = max(28, sum(len(leg.odds.as_tuple().digits) + 8
                                       for leg in legs if leg.odds is not None))
            factor = combined_return(legs)
        if factor is not None:
            outcome = 'gagne' if factor > 1 else 'perdu' if factor < 1 else 'rembourse'
    return Result(result_id, match.match_market_id, outcome, observed_at,
                  evidence_sha256, contribution.reglement, legs)
