"""Immutable evidence contracts; only necessary, permitted excerpts are retained."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal, TypeAlias
from urllib.parse import urlsplit

ResolutionStatus: TypeAlias = Literal['resolu', 'non_resolu']
Outcome: TypeAlias = Literal['gagne', 'perdu', 'rembourse', 'void',
                             'demi_gagne', 'demi_perdu', 'en_attente']
OddsBasis: TypeAlias = Literal['cote_declaree', 'cote_observee']
Category: TypeAlias = Literal['selection_avec_cote', 'selection_sans_cote',
                              'probabilite_explicite', 'information_factuelle']
CATEGORIES = ('selection_avec_cote', 'selection_sans_cote',
              'probabilite_explicite', 'information_factuelle')
OUTCOMES = ('gagne', 'perdu', 'rembourse', 'void', 'demi_gagne', 'demi_perdu', 'en_attente')


def text_fingerprint(text: str) -> str:
    """Hash the exact UTF-8 text, with no normalisation and no persistence."""
    return sha256(text.encode('utf-8')).hexdigest()


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name}: nonempty metadata required')


def _hash(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('SHA-256 must be 64 lowercase hexadecimal characters')


def _url(value: str) -> None:
    _text(value, 'url')
    parsed = urlsplit(value)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname:
        raise ValueError('absolute HTTP(S) URL required')
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('credentials forbidden in publication metadata')


def _instant(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f'{name}: explicit timezone required')


def _odds(value: Decimal | None) -> None:
    if value is not None:
        if not isinstance(value, Decimal):
            raise TypeError('odds must be explicit Decimal or None')
        if not value.is_finite() or value < Decimal('1'):
            raise ValueError('decimal odds must be finite and at least 1')


def _resolution(status: ResolutionStatus, reason: str | None) -> None:
    if status not in ('resolu', 'non_resolu'):
        raise ValueError('unknown resolution status')
    if status == 'resolu' and reason is not None:
        raise ValueError('resolved metadata cannot have an unresolved reason')
    if status == 'non_resolu':
        if reason is None:
            raise ValueError('unresolved metadata requires a reason')
        _text(reason, 'raison_non_resolu')


@dataclass(frozen=True, slots=True)
class Source:
    source_id: str
    name: str
    url: str

    def __post_init__(self) -> None:
        _text(self.source_id, 'source_id')
        _text(self.name, 'name')
        _url(self.url)


@dataclass(frozen=True, slots=True)
class Publication:
    publication_id: str
    source_id: str
    publication_url: str

    def __post_init__(self) -> None:
        _text(self.publication_id, 'publication_id')
        _text(self.source_id, 'source_id')
        _url(self.publication_url)


@dataclass(frozen=True, slots=True)
class PublicationVersion:
    version_id: str
    publication_id: str
    text_sha256: str
    announced_by_platform_at: datetime | None
    first_observed_by_robin_at: datetime
    modification_observed_at: datetime | None
    usable_at: datetime
    previous_version_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.version_id, 'version_id')
        _text(self.publication_id, 'publication_id')
        _hash(self.text_sha256)
        if self.previous_version_id is not None:
            _text(self.previous_version_id, 'previous_version_id')
            if self.modification_observed_at is None:
                raise ValueError('correction requires observed modification time')
        elif self.modification_observed_at is not None:
            raise ValueError('initial version cannot have modification_observed_at')
        for name in ('announced_by_platform_at', 'first_observed_by_robin_at',
                     'modification_observed_at', 'usable_at'):
            instant = getattr(self, name)
            if instant is not None:
                _instant(instant, name)
        _instant(self.first_observed_by_robin_at, 'first_observed_by_robin_at')
        _instant(self.usable_at, 'usable_at')
        if self.usable_at < self.first_observed_by_robin_at:
            raise ValueError('usable_at must be >= first_observed_by_robin_at')
        if self.modification_observed_at is not None:
            if self.modification_observed_at < self.first_observed_by_robin_at:
                raise ValueError('modification cannot precede first observation')
            if self.usable_at < self.modification_observed_at:
                raise ValueError('modified content cannot be used before observation')


@dataclass(frozen=True, slots=True)
class EvidenceExcerpt:
    """Location and optional necessary excerpt, authorized by the contribution."""

    text_sha256: str
    start: int
    end: int
    text: str | None = None

    def __post_init__(self) -> None:
        _hash(self.text_sha256)
        if type(self.start) is not int or type(self.end) is not int:
            raise TypeError('excerpt offsets must be integers')
        if not 0 <= self.start < self.end:
            raise ValueError('excerpt requires 0 <= start < end')
        if self.text is not None:
            _text(self.text, 'excerpt')
            if len(self.text) > 500 or len(self.text) != self.end - self.start:
                raise ValueError('necessary excerpt must match offsets and be <= 500 characters')


@dataclass(frozen=True, slots=True)
class RepriseLink:
    publication_id: str
    certainty: Literal['attestee', 'similarite']
    evidence_sha256: str | None

    def __post_init__(self) -> None:
        _text(self.publication_id, 'publication_id')
        if self.certainty not in ('attestee', 'similarite'):
            raise ValueError('unsupported reprise certainty')
        if self.evidence_sha256 is not None:
            _hash(self.evidence_sha256)
        elif self.certainty == 'attestee':
            raise ValueError('attested reprise requires evidence')


@dataclass(frozen=True, slots=True)
class SettlementRule:
    rule_id: str
    version: str
    document_url: str
    evidence_sha256: str
    market: str
    period: str
    postponed: Literal['en_attente', 'rembourse'] = 'en_attente'

    def __post_init__(self) -> None:
        for name in ('rule_id', 'version', 'market', 'period'):
            _text(getattr(self, name), name)
        _url(self.document_url)
        _hash(self.evidence_sha256)
        if self.postponed not in ('en_attente', 'rembourse'):
            raise ValueError('explicit postponement policy required')


@dataclass(frozen=True, slots=True)
class MatchScore:
    """Regulation score; qualification is separate, including extra time/penalties."""

    home: int | None
    away: int | None
    qualified: Literal['home', 'away'] | None = None
    status: Literal['termine', 'reporte', 'en_attente'] = 'termine'

    def __post_init__(self) -> None:
        for value in (self.home, self.away):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('nonnegative integer score required')
        if self.qualified not in (None, 'home', 'away'):
            raise ValueError('unknown qualification')
        if self.status not in ('termine', 'reporte', 'en_attente'):
            raise ValueError('unknown match status')


@dataclass(frozen=True, slots=True)
class SettlementLeg:
    contribution_id: str
    odds: Decimal | None
    outcome: Outcome
    reglement: SettlementRule | None

    def __post_init__(self) -> None:
        _text(self.contribution_id, 'contribution_id')
        _odds(self.odds)
        if self.outcome not in OUTCOMES:
            raise ValueError('unknown leg outcome')


@dataclass(frozen=True, slots=True)
class Contribution:
    contribution_id: str
    version_id: str
    source_id: str
    publication_url: str
    text_sha256: str
    langue: str
    marche: str
    selection: str
    cote_declaree: Decimal | None
    cote_observee: Decimal | None
    statut: ResolutionStatus
    raison_non_resolu: str | None
    extraits_preuve: tuple[EvidenceExcerpt, ...]
    author_id: str
    publication_id: str
    preuve_permise: str | None
    liens_reprise: tuple[RepriseLink, ...]
    match_id: str | None
    certitude_rapprochement: Literal['certaine', 'probable', 'non_resolue']
    ligne: Decimal | None
    periode: str
    reglement: SettlementRule | None
    cote_declaree_provenance: str | None
    cote_declaree_at: datetime | None
    cote_observee_provenance: str | None
    cote_observee_at: datetime | None
    bookmaker: str | None
    categorie: Category
    probabilite: Decimal | None
    observed_at: datetime
    selection_key: str = 'selection-1'

    def __post_init__(self) -> None:
        _instant(self.observed_at, 'contribution observed_at')
        for name in ('contribution_id', 'version_id', 'source_id', 'author_id', 'publication_id',
                     'langue', 'marche', 'selection', 'periode', 'selection_key'):
            _text(getattr(self, name), name)
        _url(self.publication_url)
        _hash(self.text_sha256)
        _odds(self.cote_declaree)
        _odds(self.cote_observee)
        _resolution(self.statut, self.raison_non_resolu)
        if self.preuve_permise is not None:
            _url(self.preuve_permise)
        if self.certitude_rapprochement not in ('certaine', 'probable', 'non_resolue'):
            raise ValueError('explicit match certainty required')
        if self.match_id is None and self.certitude_rapprochement != 'non_resolue':
            raise ValueError('missing match must remain unresolved')
        if self.match_id is not None:
            _text(self.match_id, 'match_id')
            if self.certitude_rapprochement == 'non_resolue':
                raise ValueError('unresolved match cannot have an internal identity')
        if self.ligne is not None and (not isinstance(self.ligne, Decimal)
                                       or not self.ligne.is_finite()):
            raise ValueError('finite explicit Decimal line required')
        if self.reglement is not None and type(self.reglement) is not SettlementRule:
            raise TypeError('typed settlement rule required')
        if self.bookmaker is not None:
            _text(self.bookmaker, 'bookmaker')
        for basis in ('cote_declaree', 'cote_observee'):
            odds, provenance, at = (getattr(self, basis), getattr(self, basis + '_provenance'),
                                    getattr(self, basis + '_at'))
            if odds is not None:
                _text(provenance, basis + '_provenance')
                _instant(at, basis + '_at')
                if at > self.observed_at:
                    raise ValueError('odds timestamp exceeds contribution observation')
            elif provenance is not None or at is not None:
                raise ValueError('absent odds cannot have invented quote metadata')
        if self.categorie not in CATEGORIES:
            raise ValueError('unknown ranking category')
        if (self.categorie == 'selection_avec_cote' and self.cote_declaree is None
                and self.cote_observee is None):
            raise ValueError('priced selection requires at least one explicit odds quote')
        if self.categorie == 'selection_sans_cote' and (
                self.cote_declaree is not None or self.cote_observee is not None):
            raise ValueError('unpriced selection cannot contain odds')
        if self.categorie == 'probabilite_explicite':
            if (not isinstance(self.probabilite, Decimal) or not self.probabilite.is_finite()
                    or not 0 <= self.probabilite <= 1):
                raise ValueError('explicit finite probability in [0,1] required')
        elif self.probabilite is not None:
            raise ValueError('probability belongs to its explicit category')
        if type(self.liens_reprise) is not tuple or any(
                type(link) is not RepriseLink for link in self.liens_reprise):
            raise TypeError('immutable typed reprise links required')
        if any(link.publication_id == self.publication_id for link in self.liens_reprise):
            raise ValueError('publication cannot reprise itself')
        if type(self.extraits_preuve) is not tuple:
            raise TypeError('evidence excerpts must be an immutable tuple')
        if len(self.extraits_preuve) > 5:
            raise ValueError('at most five evidence locations per contribution')
        for excerpt in self.extraits_preuve:
            if type(excerpt) is not EvidenceExcerpt:
                raise TypeError('only excerpt hashes and offsets are allowed')
            if excerpt.text_sha256 != self.text_sha256:
                raise ValueError('excerpt fingerprint must match contribution')
            if excerpt.text is not None and self.preuve_permise is None:
                raise ValueError('necessary excerpt requires permission evidence')
        texts = [e.text for e in self.extraits_preuve if e.text is not None]
        if len(texts) > 1 or sum(map(len, texts)) > 500:
            raise ValueError('one necessary text excerpt, at most 500 characters in total')
        excerpts = sorted(self.extraits_preuve, key=lambda e: e.start)
        if any(a.end > b.start for a, b in zip(excerpts, excerpts[1:])):
            raise ValueError('overlapping evidence excerpts forbidden')

    def extraction_metadata(self) -> dict[str, object]:
        """Closed extraction contract, including the complete evidence lineage."""
        from .store import _wire

        return {key: _wire(value) for key, value in asdict(self).items()}


@dataclass(frozen=True, slots=True)
class MatchMarket:
    match_market_id: str
    contribution_id: str
    version_id: str
    contribution_usable_at: datetime
    match_usable_at: datetime | None
    match_id: str | None
    market_id: str | None
    selection_id: str | None
    statut: ResolutionStatus
    raison_non_resolu: str | None

    def __post_init__(self) -> None:
        for name in ('match_market_id', 'contribution_id', 'version_id'):
            _text(getattr(self, name), name)
        _instant(self.contribution_usable_at, 'contribution_usable_at')
        if self.match_usable_at is not None:
            _instant(self.match_usable_at, 'match_usable_at')
        _resolution(self.statut, self.raison_non_resolu)
        identities = (self.match_id, self.market_id, self.selection_id)
        if self.statut == 'resolu':
            for identity in identities:
                if identity is None:
                    raise ValueError('resolved match/market/selection requires all identities')
                _text(identity, 'internal_identity')
        elif any(identity is not None for identity in identities):
            raise ValueError('unresolved match cannot expose partially resolved identities')

    @property
    def pre_match_valid(self) -> bool:
        return (self.statut == 'resolu' and self.match_usable_at is not None
                and self.contribution_usable_at < self.match_usable_at)


@dataclass(frozen=True, slots=True)
class Result:
    result_id: str
    match_market_id: str
    outcome: Outcome
    observed_at: datetime
    evidence_sha256: str
    reglement: SettlementRule | None = None
    legs: tuple[SettlementLeg, ...] = ()
    previous_result_id: str | None = None
    audit_evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        _text(self.result_id, 'result_id')
        _text(self.match_market_id, 'match_market_id')
        if self.outcome not in OUTCOMES:
            raise ValueError('unknown result; never infer a settlement')
        if self.outcome != 'en_attente' and self.reglement is None:
            raise ValueError('settled result requires a documented settlement rule')
        _instant(self.observed_at, 'observed_at')
        _hash(self.evidence_sha256)
        if self.previous_result_id is not None:
            _text(self.previous_result_id, 'previous_result_id')
        if self.audit_evidence_sha256 is not None:
            _hash(self.audit_evidence_sha256)
        if self.reglement is not None and type(self.reglement) is not SettlementRule:
            raise TypeError('typed settlement rule required')
        if type(self.legs) is not tuple or any(type(leg) is not SettlementLeg for leg in self.legs):
            raise TypeError('immutable settlement legs required')
        if len({leg.contribution_id for leg in self.legs}) != len(self.legs):
            raise ValueError('duplicate combined leg')


@dataclass(frozen=True, slots=True)
class Evaluation:
    evaluation_id: str
    contribution_id: str
    match_market_id: str
    result_id: str
    odds_basis: OddsBasis
    odds_used: Decimal | None
    unit_profit: Decimal | None
    reason: str | None
    category: Category = 'selection_avec_cote'
    brier: Decimal | None = None
    log_loss: Decimal | None = None
    factual_accuracy: Decimal | None = None
    anteriority_seconds: Decimal | None = None
    binary_outcome: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ('evaluation_id', 'contribution_id', 'match_market_id', 'result_id'):
            _text(getattr(self, name), name)
        if self.odds_basis not in ('cote_declaree', 'cote_observee'):
            raise ValueError('choose declared or observed odds explicitly')
        _odds(self.odds_used)
        if self.unit_profit is not None:
            if not isinstance(self.unit_profit, Decimal) or not self.unit_profit.is_finite():
                raise ValueError('profit must be a finite Decimal')
            if self.odds_used is None or self.reason is not None:
                raise ValueError('evaluable result requires explicit odds and no exclusion')
        else:
            if self.reason is None and self.brier is None and self.factual_accuracy is None:
                raise ValueError('unevaluable result requires a reason')
            if self.reason is not None:
                _text(self.reason, 'reason')
        if self.category not in CATEGORIES:
            raise ValueError('unknown ranking category')

    @property
    def evaluable(self) -> bool:
        return (self.unit_profit is not None or self.brier is not None
                or self.factual_accuracy is not None)

    @property
    def unit_stake(self) -> Decimal:
        return Decimal('1')


@dataclass(frozen=True, slots=True)
class AccountAssignment:
    author_id: str
    identity_id: str

    def __post_init__(self) -> None:
        _text(self.author_id, 'author_id')
        _text(self.identity_id, 'identity_id')


@dataclass(frozen=True, slots=True)
class IdentityRevision:
    revision_id: str
    previous_revision_id: str | None
    assignments: tuple[AccountAssignment, ...]
    observed_at: datetime
    evidence_sha256: str
    reason: str
    certainty: Literal['attestee', 'similarite'] = 'similarite'

    def __post_init__(self) -> None:
        _text(self.revision_id, 'revision_id')
        _text(self.reason, 'reason')
        _instant(self.observed_at, 'observed_at')
        _hash(self.evidence_sha256)
        if type(self.assignments) is not tuple or not self.assignments or any(
                type(item) is not AccountAssignment for item in self.assignments):
            raise ValueError('explicit immutable assignments required')
        if len({item.author_id for item in self.assignments}) != len(self.assignments):
            raise ValueError('duplicate account assignment')
        if self.certainty not in ('attestee', 'similarite'):
            raise ValueError('explicit identity certainty required')
        if self.certainty != 'attestee' and any(a.author_id != a.identity_id
                                               for a in self.assignments):
            raise ValueError('similar accounts cannot be merged without attested identity')


@dataclass(frozen=True, slots=True)
class Withdrawal:
    withdrawal_id: str
    contribution_id: str
    observed_at: datetime
    evidence_sha256: str
    reason: str

    def __post_init__(self) -> None:
        _text(self.withdrawal_id, 'withdrawal_id')
        _text(self.contribution_id, 'contribution_id')
        _text(self.reason, 'reason')
        _instant(self.observed_at, 'observed_at')
        _hash(self.evidence_sha256)


@dataclass(frozen=True, slots=True)
class Visit:
    visit_id: str
    source_id: str
    planned_at: datetime
    completed_at: datetime | None
    succeeded: bool

    def __post_init__(self) -> None:
        _text(self.visit_id, 'visit_id')
        _text(self.source_id, 'source_id')
        _instant(self.planned_at, 'planned_at')
        if type(self.succeeded) is not bool:
            raise TypeError('explicit boolean visit outcome required')
        if self.completed_at is not None:
            _instant(self.completed_at, 'completed_at')
            if self.completed_at < self.planned_at:
                raise ValueError('visit completion precedes plan')
        elif self.succeeded:
            raise ValueError('successful visit requires completion time')


@dataclass(frozen=True, slots=True)
class Cohort:
    """Criteria and reserved future windows, recorded before cohort evaluation."""

    cohort_id: str
    author_ids: tuple[str, ...]
    defined_at: datetime
    evaluation_starts_at: datetime
    evaluation_ends_at: datetime
    prospective_starts_at: datetime
    prospective_ends_at: datetime
    minimum_independent_matches: int
    minimum_visit_coverage: Decimal
    criteria_sha256: str

    def __post_init__(self) -> None:
        _text(self.cohort_id, 'cohort_id')
        _hash(self.criteria_sha256)
        if type(self.author_ids) is not tuple or not self.author_ids:
            raise ValueError('cohort membership must be fixed explicitly')
        for author in self.author_ids:
            _text(author, 'author_id')
        if len(set(self.author_ids)) != len(self.author_ids):
            raise ValueError('duplicate cohort member')
        times = (self.defined_at, self.evaluation_starts_at, self.evaluation_ends_at,
                 self.prospective_starts_at, self.prospective_ends_at)
        for instant in times:
            _instant(instant, 'cohort window')
        if not all(a < b for a, b in zip(times, times[1:])):
            raise ValueError('cohort and prospective windows must be fixed in advance')
        if type(self.minimum_independent_matches) is not int or self.minimum_independent_matches < 1:
            raise ValueError('positive predeclared independent sample threshold required')
        if (not isinstance(self.minimum_visit_coverage, Decimal)
                or not self.minimum_visit_coverage.is_finite()
                or not 0 < self.minimum_visit_coverage <= 1):
            raise ValueError('explicit predeclared visit coverage threshold in (0,1] required')


@dataclass(frozen=True, slots=True)
class VisitReceipt:
    """One immutable outcome per planned Visit, without replacing the plan."""

    receipt_id: str
    visit_id: str
    completed_at: datetime
    status: Literal['ok', 'echec', 'bloque_robots']
    publication_ids: tuple[str, ...]
    reason: str | None

    def __post_init__(self) -> None:
        _text(self.receipt_id, 'receipt_id')
        _text(self.visit_id, 'visit_id')
        _instant(self.completed_at, 'completed_at')
        if self.status not in ('ok', 'echec', 'bloque_robots'):
            raise ValueError('unknown collection status')
        if type(self.publication_ids) is not tuple or len(set(self.publication_ids)) != len(
                self.publication_ids):
            raise ValueError('immutable unique publication ids required')
        for identifier in self.publication_ids:
            _text(identifier, 'publication_id')
        if self.status == 'ok':
            if self.reason is not None:
                raise ValueError('successful visit cannot have a failure reason')
        else:
            if self.reason is None:
                raise ValueError('visit failure requires a reason')
            _text(self.reason, 'visit failure reason')


Entity: TypeAlias = (Source | Publication | PublicationVersion | Contribution | MatchMarket
                     | Result | Evaluation | IdentityRevision | Withdrawal | Visit | Cohort
                     | VisitReceipt)


def decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, 'f')


def instant_text(value: datetime) -> str:
    _instant(value, 'timestamp')
    return value.astimezone(UTC).isoformat()
