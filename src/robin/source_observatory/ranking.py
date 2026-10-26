"""Reproducible projections over immutable evidence, without identity guessing."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext

from .models import (
    Cohort,
    Contribution,
    Entity,
    Evaluation,
    IdentityRevision,
    MatchMarket,
    OddsBasis,
    PublicationVersion,
    Result,
    Visit,
    Withdrawal,
)


def pre_match_contributions(
    entities: Iterable[Entity], kickoff: datetime,
) -> tuple[Contribution, ...]:
    """Select the last usable publication version strictly before kickoff.

    Selecting a whole version also removes selections omitted by a correction;
    a correction after kickoff can never replace the proven pre-match version.
    """
    latest: dict[str, PublicationVersion] = {}
    items = tuple(entities)
    for entity in items:
        if isinstance(entity, PublicationVersion) and entity.usable_at < kickoff:
            previous = latest.get(entity.publication_id)
            if previous is None or entity.usable_at >= previous.usable_at:
                latest[entity.publication_id] = entity
    versions = {version.version_id for version in latest.values()}
    return tuple(entity for entity in items if isinstance(entity, Contribution)
                 and entity.version_id in versions)


def reprise_groups(contributions: Iterable[Contribution]) -> dict[str, tuple[str, ...]]:
    """One component per attested origin chain; similarity never joins components."""
    items = tuple(contributions)
    parent: dict[str, str] = {}
    roots: set[str] = set()
    for c in items:
        parent.setdefault(c.publication_id, c.publication_id)
        for link in c.liens_reprise:
            if link.certainty == 'attestee':
                parent.setdefault(link.publication_id, link.publication_id)
                roots.add(link.publication_id)

    def find(key: str) -> str:
        while parent[key] != key:
            key = parent[key]
        return key

    for c in items:
        for link in c.liens_reprise:
            if link.certainty == 'attestee':
                a, b = find(c.publication_id), find(link.publication_id)
                if a != b:
                    parent[a] = b
    groups: dict[str, list[str]] = defaultdict(list)
    for pub in sorted(parent):
        groups[find(pub)].append(pub)
    # Prefer an attested root as label, deterministically, including cyclic evidence.
    return {min(set(pubs) & roots or set(pubs)): tuple(pubs) for pubs in groups.values()}


@dataclass(frozen=True, slots=True)
class OriginGroup:
    group_id: str
    publication_ids: tuple[str, ...]
    origin_publication_id: str | None
    statut: str


def origin_groups(contributions: Iterable[Contribution]) -> tuple[OriginGroup, ...]:
    items = tuple(contributions)
    outgoing: dict[str, set[str]] = defaultdict(set)
    for c in items:
        for link in c.liens_reprise:
            if link.certainty == 'attestee':
                outgoing[c.publication_id].add(link.publication_id)
    output = []
    for group, pubs in sorted(reprise_groups(items).items()):
        targets = {target for pub in pubs for target in outgoing[pub]}
        roots = {target for target in targets if not outgoing[target]}
        origin = next(iter(roots)) if len(roots) == 1 else None
        output.append(OriginGroup(group, pubs, origin,
                                  'resolu' if origin is not None else 'non_resolu'))
    return tuple(output)


@dataclass(frozen=True, slots=True)
class Ranking:
    net: Decimal
    stakes: int
    roi: Decimal | None
    independent_groups: int
    independent_matches: int
    status: str
    coverage_changed: bool
    categories: tuple[tuple[str, int], ...]
    brier: Decimal | None
    log_loss: Decimal | None
    factual_accuracy: Decimal | None


def rankings(entities: Iterable[Entity], *,
             odds_basis: OddsBasis = 'cote_declaree') -> dict[str, Ranking]:
    if odds_basis not in ('cote_declaree', 'cote_observee'):
        raise ValueError('choose declared or observed odds explicitly')
    items = tuple(entities)
    contributions = {e.contribution_id: e for e in items if isinstance(e, Contribution)}
    matches = {e.match_market_id: e for e in items if isinstance(e, MatchMarket)}
    latest_results = {e.match_market_id: e.result_id for e in items if isinstance(e, Result)}
    identities: dict[str, str] = {}
    for entity in items:
        if isinstance(entity, IdentityRevision):
            identities.update({a.author_id: a.identity_id for a in entity.assignments})
    withdrawn = {e.contribution_id for e in items if isinstance(e, Withdrawal)}
    affected_authors = {identities.get(contributions[key].author_id, contributions[key].author_id)
                        for key in withdrawn}
    by_author: dict[str, list[Evaluation]] = defaultdict(list)
    # One declared/observed basis must be chosen for a report; never mix both.
    seen: set[str] = set()
    for entity in items:
        if not isinstance(entity, Evaluation) or entity.odds_basis != odds_basis:
            continue
        if entity.result_id != latest_results.get(entity.match_market_id):
            continue
        c = contributions[entity.contribution_id]
        match = matches[entity.match_market_id]
        if match.match_usable_at is None:
            continue
        eligible = pre_match_contributions(items, match.match_usable_at)
        if c not in eligible:
            continue
        if c.contribution_id in seen:
            raise ValueError('choose a single odds basis/evaluation per contribution')
        seen.add(c.contribution_id)
        by_author[identities.get(c.author_id, c.author_id)].append(entity)
    output = {}
    for author, evaluations in by_author.items():
        cs = [contributions[e.contribution_id] for e in evaluations]
        groups = reprise_groups(cs)
        changed = author in affected_authors
        # Several selections may be priced, but independence is counted by origin + match.
        category_counts: dict[str, int] = defaultdict(int)
        for e in evaluations:
            category_counts[e.category] += 1
        profits = [e.unit_profit for e in evaluations if e.unit_profit is not None]
        with localcontext() as context:
            context.prec = max(28, sum(len(p.as_tuple().digits) + 8 for p in profits))
            net = sum(profits, Decimal(0))
            roi = net / len(profits) if profits else None
        def mean(values: list[Decimal]) -> Decimal | None:
            return sum(values, Decimal(0)) / len(values) if values else None
        evaluated_ids = {e.contribution_id for e in evaluations if e.evaluable}
        independent = {(group, c.match_id) for group, pubs in groups.items()
                       for c in cs if c.publication_id in pubs and c.contribution_id in evaluated_ids}
        output[author] = Ranking(
            net, len(profits), roi, len(independent), len({c.match_id for c in cs
                if c.match_id is not None and c.contribution_id in evaluated_ids}),
            'Comparable suspendu' if changed else 'En observation', changed,
            tuple(sorted(category_counts.items())),
            mean([e.brier for e in evaluations if e.brier is not None]),
            mean([e.log_loss for e in evaluations if e.log_loss is not None]),
            mean([e.factual_accuracy for e in evaluations if e.factual_accuracy is not None]),
        )
    return output


def visit_coverage(visits: Iterable[Visit]) -> Decimal | None:
    items = tuple(visits)
    if len({v.visit_id for v in items}) != len(items):
        raise ValueError('duplicate planned visit')
    return Decimal(sum(v.succeeded for v in items)) / len(items) if items else None


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: Decimal
    upper: Decimal
    count: int
    mean_probability: Decimal
    observed_frequency: Decimal


def calibration(contributions: Iterable[Contribution], evaluations: Iterable[Evaluation],
                *, bins: int = 10) -> tuple[CalibrationBin, ...]:
    if type(bins) is not int or bins < 1:
        raise ValueError('positive bin count required')
    cs = {c.contribution_id: c for c in contributions}
    buckets: dict[int, list[tuple[Decimal, Decimal]]] = defaultdict(list)
    seen = set()
    for e in evaluations:
        if e.category != 'probabilite_explicite' or e.brier is None:
            continue
        if e.contribution_id in seen:
            raise ValueError('duplicate probability evaluation')
        seen.add(e.contribution_id)
        p = cs[e.contribution_id].probabilite
        if p is None or e.binary_outcome is None:
            raise ValueError('explicit probability and observed binary outcome required')
        buckets[min(bins - 1, int(p * bins))].append((p, e.binary_outcome))
    return tuple(CalibrationBin(Decimal(i) / bins, Decimal(i + 1) / bins, len(values),
                 sum((p for p, _ in values), Decimal(0)) / len(values),
                 sum((y for _, y in values), Decimal(0)) / len(values))
                 for i, values in sorted(buckets.items()))


def classification_state(
    cohort: Cohort, *, at: datetime, independent_matches: int, coverage: Decimal | None,
    prospective_matches: int, prospective_coverage: Decimal | None,
    coverage_changed: bool = False,
) -> str:
    if coverage_changed:
        return 'Comparable suspendu'
    if at < cohort.evaluation_starts_at:
        return 'Decouverte'
    if (at < cohort.evaluation_ends_at or independent_matches < cohort.minimum_independent_matches
            or coverage is None or coverage < cohort.minimum_visit_coverage):
        return 'En observation'
    if (at >= cohort.prospective_ends_at
            and prospective_matches >= cohort.minimum_independent_matches
            and prospective_coverage is not None
            and prospective_coverage >= cohort.minimum_visit_coverage):
        return 'Signal prospectif'
    return 'Comparable'
