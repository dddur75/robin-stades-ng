"""Reproducible projections over immutable evidence, without identity guessing."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, localcontext

from .models import (
    Cohort,
    Contribution,
    Entity,
    Evaluation,
    ExtractionRecord,
    IdentityRevision,
    MatchMarket,
    OddsBasis,
    PublicationVersion,
    Result,
    Visit,
    VisitReceipt,
    Withdrawal,
)


def observation_time(entity: Entity) -> datetime | None:
    """Actual observation only: a future visit plan is not an observation."""
    if isinstance(entity, PublicationVersion):
        return entity.modification_observed_at or entity.first_observed_by_robin_at
    if isinstance(entity, (Contribution, Result, IdentityRevision, Withdrawal, ExtractionRecord)):
        return entity.observed_at
    if isinstance(entity, (Visit, VisitReceipt)):
        return entity.completed_at
    if isinstance(entity, Cohort):
        return entity.defined_at
    return None


def preserves_evidence(previous: Contribution, current: Contribution) -> bool:
    return (not (previous.statut == 'resolu' and current.statut != 'resolu')
            and not (previous.certitude_rapprochement == 'certaine'
                     and current.certitude_rapprochement != 'certaine')
            and all(getattr(previous, basis) is None or getattr(current, basis) is not None
                    for basis in ('cote_declaree', 'cote_observee'))
            and previous.categorie == current.categorie)


def pre_match_contributions(
    entities: Iterable[Entity], kickoff: datetime,
) -> tuple[Contribution, ...]:
    """Latest proven selection per slot; omissions never erase earlier selections."""
    items = tuple(entities)
    versions = {e.version_id: e for e in items if isinstance(e, PublicationVersion)}
    latest: dict[tuple[str, str | None, str], Contribution] = {}
    for entity in items:
        if isinstance(entity, Contribution):
            v = versions[entity.version_id]
            if max(v.usable_at, entity.observed_at) >= kickoff:
                continue
            slot = (entity.publication_id, entity.match_id, entity.selection_key)
            # Extraction positions move when a preceding selection is removed.
            # Reattach an unchanged market/selection to its earlier slot first.
            for old_slot, old in latest.items():
                if (old.publication_id == entity.publication_id and old.match_id == entity.match_id
                        and versions[old.version_id].usable_at < v.usable_at
                        and (old.marche, old.selection, old.ligne, old.periode)
                        == (entity.marche, entity.selection, entity.ligne, entity.periode)):
                    slot = old_slot
                    break
            previous = latest.get(slot)
            if previous is None or (v.usable_at > versions[previous.version_id].usable_at
                                    and preserves_evidence(previous, entity)):
                latest[slot] = entity
    return tuple(latest.values())


def reprise_groups(contributions: Iterable[Contribution]) -> dict[str, tuple[str, ...]]:
    """One component per attested origin chain; similarity never joins components."""
    items = tuple(contributions)
    parent: dict[str, str] = {}
    roots: set[str] = set()
    outgoing: set[str] = set()
    for c in items:
        parent.setdefault(c.publication_id, c.publication_id)
        for link in c.liens_reprise:
            if link.certainty == 'attestee':
                outgoing.add(c.publication_id)
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
    return {min((set(pubs) & (roots - outgoing)) or set(pubs)): tuple(pubs)
            for pubs in groups.values()}


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
        # Remove sinks repeatedly. Any remaining node belongs to or reaches a cycle.
        remaining = set(pubs)
        while True:
            sinks = {p for p in remaining if not outgoing[p] & remaining}
            if not sinks:
                break
            remaining -= sinks
        targets = {target for pub in pubs for target in outgoing[pub]}
        roots = {target for target in targets if not outgoing[target]}
        origin = next(iter(roots)) if len(roots) == 1 and not remaining else None
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
             odds_basis: OddsBasis = 'cote_declaree',
             at: datetime | None = None) -> dict[str, Ranking]:
    if odds_basis not in ('cote_declaree', 'cote_observee'):
        raise ValueError('choose declared or observed odds explicitly')
    items = tuple(entities)
    if at is None:
        at = max((t for e in items if (t := observation_time(e)) is not None), default=None)
    if at is not None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError('explicit report timezone required')
        items = tuple(e for e in items if isinstance(e, Visit)
                      or (observation_time(e) or at) <= at)
    contributions = {e.contribution_id: e for e in items if isinstance(e, Contribution)}
    matches = {e.match_market_id: e for e in items if isinstance(e, MatchMarket)
               and e.contribution_id in contributions}
    latest_results = {e.match_market_id: e.result_id for e in items if isinstance(e, Result)}
    identities: dict[str, str] = {}
    for entity in items:
        if isinstance(entity, IdentityRevision) and entity.certainty == 'attestee':
            identities = {a.author_id: a.identity_id for a in entity.assignments}
    withdrawn = {e.contribution_id for e in items if isinstance(e, Withdrawal)}
    affected_authors = {identities.get(contributions[key].author_id, contributions[key].author_id)
                        for key in withdrawn}
    versions = {e.version_id: e for e in items if isinstance(e, PublicationVersion)}
    for c in contributions.values():
        later = [v for v in versions.values() if v.publication_id == c.publication_id
                 and v.usable_at > versions[c.version_id].usable_at]
        if any(not any(other.version_id == v.version_id and other.selection_key == c.selection_key
                       and other.match_id == c.match_id and preserves_evidence(c, other)
                       for other in contributions.values()) for v in later):
            affected_authors.add(identities.get(c.author_id, c.author_id))
    by_author: dict[str, list[Evaluation]] = defaultdict(list)
    for author in affected_authors:
        by_author[author] = []
    for cohort in (e for e in items if isinstance(e, Cohort)):
        for member in cohort.author_ids:
            by_author[identities.get(member, member)] = []
    for m in matches.values():
        c = contributions[m.contribution_id]
        if (identities.get(c.author_id, c.author_id) in affected_authors
                and m.match_usable_at is not None and at is not None
                and at >= m.match_usable_at
                and c in pre_match_contributions(items, m.match_usable_at)
                and m.match_market_id not in latest_results):
            raise ValueError('retained contribution requires result and evaluation')
        if (m.match_market_id in latest_results and m.match_usable_at is not None
                and c in pre_match_contributions(items, m.match_usable_at)
                and not any(isinstance(e, Evaluation)
                    and e.result_id == latest_results[m.match_market_id]
                    and (e.odds_basis == odds_basis or c.categorie in (
                        'probabilite_explicite', 'information_factuelle')) for e in items)):
            raise ValueError('latest result requires a corresponding evaluation')
    # One declared/observed basis must be chosen for a report; never mix both.
    seen: set[str] = set()
    for entity in items:
        if not isinstance(entity, Evaluation):
            continue
        candidate = contributions.get(entity.contribution_id)
        if candidate is None or (entity.odds_basis != odds_basis and candidate.categorie not in (
                'probabilite_explicite', 'information_factuelle')):
            continue
        c = candidate
        if entity.result_id != latest_results.get(entity.match_market_id):
            continue
        match = matches[entity.match_market_id]
        if match.match_usable_at is None:
            continue
        eligible = pre_match_contributions(items, match.match_usable_at)
        if c not in eligible:
            continue
        if c.marche == 'combine' and entity.evaluable:
            from .service import combined_legs_proven

            result = next(e for e in items if isinstance(e, Result)
                          and e.result_id == entity.result_id)
            if not combined_legs_proven(c, match, result, items, odds_basis):
                raise ValueError('combined result requires audited update after leg correction')
        if c.contribution_id in seen:
            if c.categorie in ('probabilite_explicite', 'information_factuelle'):
                continue
            raise ValueError('choose a single odds basis/evaluation per contribution')
        seen.add(c.contribution_id)
        by_author[identities.get(c.author_id, c.author_id)].append(entity)
    output = {}
    groups = reprise_groups(contributions.values())
    group_for = {pub: group for group, pubs in groups.items() for pub in pubs}
    for author, evaluations in by_author.items():
        unique: dict[tuple[object, ...], Evaluation] = {}
        for e in sorted(evaluations, key=lambda e: (not e.evaluable,
                        contributions[e.contribution_id].observed_at, e.contribution_id)):
            c, m = contributions[e.contribution_id], matches[e.match_market_id]
            key = (group_for[c.publication_id], m.match_id, m.market_id, m.selection_id,
                   c.ligne, c.periode, e.category)
            unique.setdefault(key, e)
        evaluations = list(unique.values())
        cs = [contributions[e.contribution_id] for e in evaluations]
        changed = author in affected_authors
        # Several selections may be priced, but independence is counted by origin + match.
        category_counts: dict[str, int] = defaultdict(int)
        for e in evaluations:
            if e.category != 'selection_avec_cote' or e.evaluable:
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
        status = 'Comparable suspendu' if changed else 'En observation'
        cohorts = [e for e in items if isinstance(e, Cohort)
                   and any(identities.get(member, member) == author for member in e.author_ids)]
        if len(cohorts) > 1:
            raise ValueError('choose one predeclared cohort per author')
        if cohorts and at is not None:
            status = cohort_state(items, cohorts[0], author_id=author, at=at,
                                  identities=identities, coverage_changed=changed,
                                  odds_basis=odds_basis)
        output[author] = Ranking(
            net, len(profits), roi, len(independent), len({c.match_id for c in cs
                if c.match_id is not None and c.contribution_id in evaluated_ids}),
            status, changed,
            tuple(sorted(category_counts.items())),
            mean([e.brier for e in evaluations if e.brier is not None]),
            mean([e.log_loss for e in evaluations if e.log_loss is not None]),
            mean([e.factual_accuracy for e in evaluations if e.factual_accuracy is not None]),
        )
    return output


def effective_visits(entities: Iterable[Entity], at: datetime | None = None) -> tuple[Visit, ...]:
    items = tuple(entities)
    receipts: dict[str, VisitReceipt] = {}
    for e in items:
        if isinstance(e, VisitReceipt):
            if e.visit_id in receipts:
                raise ValueError('duplicate visit receipt')
            if at is None or e.completed_at <= at:
                receipts[e.visit_id] = e
    return tuple(replace(e, completed_at=receipts[e.visit_id].completed_at,
                         succeeded=receipts[e.visit_id].status == 'ok')
                 if e.visit_id in receipts else e for e in items if isinstance(e, Visit))


def visit_coverage(visits: Iterable[Entity]) -> Decimal | None:
    items = effective_visits(visits)
    if len({v.visit_id for v in items}) != len(items):
        raise ValueError('duplicate planned visit')
    return Decimal(sum(v.succeeded for v in items)) / len(items) if items else None


def cohort_state(
    entities: Iterable[Entity], cohort: Cohort, *, author_id: str, at: datetime,
    identities: dict[str, str], odds_basis: OddsBasis, coverage_changed: bool = False,
) -> str:
    """Derive cohort inputs from observed journal evidence, never caller counters."""
    items = tuple(entities)
    cs = {e.contribution_id: e for e in items if isinstance(e, Contribution)
          and identities.get(e.author_id, e.author_id) == author_id}
    ms = {e.match_market_id: e for e in items if isinstance(e, MatchMarket)}
    rs = {e.match_market_id: e for e in items if isinstance(e, Result) and e.observed_at <= at}

    def window(start: datetime, end: datetime) -> tuple[int, Decimal | None]:
        matches = set()
        for e in items:
            if not isinstance(e, Evaluation) or not e.evaluable or e.contribution_id not in cs:
                continue
            if e.category == 'selection_avec_cote' and e.odds_basis != odds_basis:
                continue
            c, m, r = cs[e.contribution_id], ms[e.match_market_id], rs.get(e.match_market_id)
            if (r is not None and e.result_id == r.result_id and m.match_usable_at is not None
                    and start <= c.observed_at < end
                    and start <= m.match_usable_at < end
                    and c in pre_match_contributions(items, m.match_usable_at)):
                matches.add(m.match_id)
        visits = [v for v in effective_visits(items, at)
                  if start <= v.planned_at < end and v.planned_at <= at]
        if len({v.visit_id for v in visits}) != len(visits):
            raise ValueError('duplicate planned visit')
        successes = sum(v.succeeded and v.completed_at is not None and v.completed_at <= at
                        for v in visits)
        coverage = Decimal(successes) / len(visits) if visits else None
        return len(matches), coverage

    count, coverage = window(cohort.evaluation_starts_at, cohort.evaluation_ends_at)
    future_count, future_coverage = window(cohort.prospective_starts_at, cohort.prospective_ends_at)
    return classification_state(cohort, at=at, independent_matches=count, coverage=coverage,
        prospective_matches=future_count, prospective_coverage=future_coverage,
        coverage_changed=coverage_changed)


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
