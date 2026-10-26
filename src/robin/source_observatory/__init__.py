"""Dossier fidèle: immutable source metadata and unit-stake paper evaluation."""

from .models import (
    AccountAssignment,
    Cohort,
    Contribution,
    Evaluation,
    EvidenceExcerpt,
    IdentityRevision,
    MatchMarket,
    MatchScore,
    Publication,
    PublicationVersion,
    RepriseLink,
    Result,
    SettlementLeg,
    SettlementRule,
    Source,
    Visit,
    Withdrawal,
    text_fingerprint,
)
from .ranking import (
    CalibrationBin,
    OriginGroup,
    Ranking,
    calibration,
    classification_state,
    origin_groups,
    pre_match_contributions,
    rankings,
    reprise_groups,
    visit_coverage,
)
from .service import evaluate, resolve_match_market, settle, settle_combined
from .store import AppendOnlyStore, AppendOnlyViolation, IntegrityError, StoredRecord

__all__ = [
    'AppendOnlyStore', 'AppendOnlyViolation', 'Contribution', 'Evaluation',
    'EvidenceExcerpt', 'IntegrityError', 'MatchMarket', 'Publication',
    'PublicationVersion', 'Result', 'Source', 'StoredRecord', 'evaluate',
    'resolve_match_market', 'text_fingerprint',
    'AccountAssignment', 'Cohort', 'IdentityRevision', 'MatchScore', 'RepriseLink',
    'SettlementLeg', 'SettlementRule', 'Visit', 'Withdrawal', 'CalibrationBin', 'Ranking',
    'calibration', 'classification_state', 'pre_match_contributions', 'rankings',
    'reprise_groups', 'visit_coverage', 'settle', 'settle_combined',
    'OriginGroup', 'origin_groups',
]
