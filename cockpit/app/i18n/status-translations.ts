export type StatusTone = "positive" | "information" | "attention" | "critical" | "neutral" | "research";

export type StatusPresentation = {
  short: string;
  long: string;
  tone: StatusTone;
  icon: string;
  severity: 0 | 1 | 2 | 3;
  action?: string;
};

const catalogue: Record<string, StatusPresentation> = {
  FRESHNESS_CURRENT: {
    short: "À jour au moment du snapshot",
    long: "Au moment du snapshot, aucune nouvelle capture n’était attendue depuis sa génération.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  FRESHNESS_UPDATING: {
    short: "Actualisation en cours",
    long: "Un nouveau snapshot est en cours de préparation ; la dernière version valide reste affichée.",
    tone: "information",
    icon: "↻",
    severity: 0,
  },
  FRESHNESS_STALE: {
    short: "Données anciennes",
    long: "Une fenêtre de capture attendue s’est ouverte depuis la génération du snapshot.",
    tone: "attention",
    icon: "◷",
    severity: 2,
    action: "Attendre ou vérifier le prochain workflow de snapshot.",
  },
  FRESHNESS_INVALID: {
    short: "Snapshot invalide",
    long: "Le schéma ou les horodatages ne permettent pas de présenter ces données avec confiance.",
    tone: "critical",
    icon: "!",
    severity: 3,
    action: "Vérifier le générateur et l’intégrité du snapshot.",
  },
  BLOCKED_BY_COVERAGE: {
    short: "Données encore insuffisantes",
    long: "Les observations nécessaires n’existent pas encore en quantité suffisante.",
    tone: "attention",
    icon: "◔",
    severity: 1,
    action: "Attendre les prochaines captures.",
  },
  BLOCKED_BY_TEMPORALITY: {
    short: "Horaire de disponibilité non prouvé",
    long: "L’information existe dans l’historique, mais sa disponibilité avant le coup d’envoi n’est pas démontrée.",
    tone: "critical",
    icon: "◷",
    severity: 2,
    action: "Vérifier la preuve temporelle.",
  },
  WAITING_FOR_OBSERVATIONS: {
    short: "En attente de nouvelles observations",
    long: "La collecte prospective doit encore produire des observations vérifiées.",
    tone: "information",
    icon: "◌",
    severity: 0,
  },
  ACTIVE_FULL: {
    short: "Actif en cadence complète",
    long: "Le calendrier est disponible et toutes les fenêtres prévues par le profil complet sont planifiées.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  ACTIVE_ODDS_REDUCED: {
    short: "Actif avec cotes réduites",
    long: "Le calendrier est disponible ; les données profondes sont suivies avec les trois fenêtres de cotes prioritaires.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  WAITING_FOR_FIXTURES: {
    short: "Calendrier en attente",
    long: "Le fournisseur a répondu normalement, mais aucune rencontre admissible n’est encore publiée.",
    tone: "information",
    icon: "◌",
    severity: 0,
  },
  NO_FIXTURES_IN_CURRENT_HORIZON: {
    short: "Aucune rencontre dans l’horizon",
    long: "Le fournisseur a répondu normalement, mais aucune rencontre ne se trouve dans l’horizon de découverte actuel.",
    tone: "information",
    icon: "◌",
    severity: 0,
  },
  BLOCKED_PROVIDER_ERROR: {
    short: "Erreur fournisseur",
    long: "Une erreur HTTP, d’authentification, de délai ou de schéma empêche la découverte du calendrier.",
    tone: "critical",
    icon: "!",
    severity: 3,
    action: "Examiner le dernier passage du registre.",
  },
  BLOCKED_IDENTITY: {
    short: "Identités incomplètes",
    long: "Le calendrier existe, mais toutes les équipes ne sont pas encore résolues avec une provenance vérifiée.",
    tone: "attention",
    icon: "◔",
    severity: 2,
  },
  BLOCKED_BUDGET: {
    short: "Budget de collecte protégé",
    long: "Le registre reste fermé afin de préserver les plafonds et la réserve fournisseur.",
    tone: "attention",
    icon: "◔",
    severity: 2,
  },
  DISABLED: {
    short: "Désactivé",
    long: "Cette compétition est volontairement exclue de la collecte.",
    tone: "neutral",
    icon: "Ⅱ",
    severity: 0,
  },
  LIVE_PROSPECTIVE_CAPTURE: {
    short: "Observations pré-match en cours",
    long: "La collecte prospective est active et reste strictement antérieure au match.",
    tone: "information",
    icon: "●",
    severity: 0,
  },
  CAPTURES_RECORDED: {
    short: "Captures consignées",
    long: "Le snapshot contient des appels ou crédits fournisseur enregistrés.",
    tone: "information",
    icon: "●",
    severity: 0,
  },
  NO_CAPTURE_RECORDED: {
    short: "Aucune capture consignée",
    long: "Le snapshot ne contient aucun appel ou crédit pour ce fournisseur.",
    tone: "neutral",
    icon: "∅",
    severity: 0,
  },
  NO_CURRENT_OPERATIONAL_EVIDENCE: {
    short: "Aucune preuve opérationnelle courante",
    long: "Le snapshot courant ne permet pas d’attester l’état opérationnel de cette source.",
    tone: "neutral",
    icon: "∅",
    severity: 0,
  },
  HISTORICAL_SOURCE_ONLY: {
    short: "Source historique uniquement",
    long: "Cette source intervient dans les données historiques, pas dans l’état fournisseur courant.",
    tone: "research",
    icon: "◇",
    severity: 0,
  },
  PROSPECTIVE_GATES_ACCUMULATING: {
    short: "Les données s’accumulent progressivement",
    long: "Les vérifications prospectives restent fermées jusqu’au volume de preuve requis.",
    tone: "research",
    icon: "↗",
    severity: 0,
  },
  PROSPECTIVE_FROZEN: {
    short: "Gelée pour observation prospective",
    long: "La règle et son contrat de prix ont été figés avant les nouvelles observations.",
    tone: "research",
    icon: "◇",
    severity: 0,
  },
  NO_DUE_WINDOW_SUCCESS: {
    short: "Aucune capture nécessaire",
    long: "Le planificateur a vérifié le calendrier : aucune fenêtre n’était due.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  CAPTURED_EMPTY: {
    short: "Capture effectuée, aucune information publiée",
    long: "La source a répondu, mais ne proposait aucune donnée à cet instant.",
    tone: "neutral",
    icon: "∅",
    severity: 0,
  },
  MISSED_WINDOW: {
    short: "Fenêtre de capture manquée",
    long: "La capture n’a pas été effectuée dans l’intervalle autorisé.",
    tone: "critical",
    icon: "!",
    severity: 3,
    action: "Examiner l’incident et la politique de rattrapage.",
  },
  TEMPORALITY_FAILED: {
    short: "Donnée reçue trop tard",
    long: "La donnée a été reçue après l’heure limite et ne peut pas servir de preuve pré-match.",
    tone: "critical",
    icon: "!",
    severity: 2,
  },
  PRODUCTION_LOCKED: {
    short: "Paris réels désactivés",
    long: "Aucune décision ne peut déclencher de transaction financière.",
    tone: "positive",
    icon: "⌁",
    severity: 0,
  },
  STORAGE_PAUSED: {
    short: "Collectes historiques secondaires suspendues",
    long: "Les tâches secondaires de stockage sont en pause et séparées du suivi prospectif.",
    tone: "neutral",
    icon: "Ⅱ",
    severity: 0,
  },
  P3_P4_PAUSED: {
    short: "Tâches secondaires suspendues",
    long: "Les priorités P3 et P4 restent volontairement en pause.",
    tone: "neutral",
    icon: "Ⅱ",
    severity: 0,
  },
  NO_CANDIDATE: {
    short: "Aucun candidat actuellement",
    long: "Aucune hypothèse ne satisfait actuellement tous les critères requis.",
    tone: "neutral",
    icon: "∅",
    severity: 0,
  },
  REJECTED: {
    short: "Hypothèse rejetée",
    long: "L’hypothèse n’a pas franchi les contrôles scientifiques prévus.",
    tone: "critical",
    icon: "×",
    severity: 1,
  },
  NOT_DUE: {
    short: "Pas encore nécessaire",
    long: "Cette donnée sera recherchée plus près du match.",
    tone: "neutral",
    icon: "○",
    severity: 0,
  },
  READY: {
    short: "Prêt",
    long: "Tous les critères requis pour cette étape sont satisfaits.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  PARTIAL: {
    short: "Partiel",
    long: "Une partie des données attendues est disponible.",
    tone: "attention",
    icon: "◐",
    severity: 1,
  },
  PENDING: {
    short: "À venir",
    long: "Cette étape est planifiée mais n’est pas encore due.",
    tone: "neutral",
    icon: "○",
    severity: 0,
  },
  REGISTERED: {
    short: "Match enregistré",
    long: "La rencontre est inscrite dans le registre prospectif.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  VERIFIED: {
    short: "Identité vérifiée",
    long: "Le nom est relié à une capture de rencontre et à son reçu cryptographiquement vérifié.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  UNRESOLVED: {
    short: "Identité non résolue",
    long: "Aucune preuve vérifiée ne permet encore de publier le nom de cette équipe.",
    tone: "attention",
    icon: "◌",
    severity: 1,
  },
  CAPTURED: {
    short: "Capture vérifiée",
    long: "La capture a été enregistrée avec sa provenance et son empreinte.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  COMPLETE: {
    short: "Capture acquittée",
    long: "Cette fenêtre dispose déjà d’une preuve complète et ne doit plus être planifiée.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  DUE: {
    short: "Capture actuellement due",
    long: "La fenêtre de capture est ouverte et n’a pas encore été acquittée.",
    tone: "attention",
    icon: "◷",
    severity: 1,
  },
  TOMBSTONED: {
    short: "Rencontre retirée",
    long: "La version de cette rencontre est conservée comme tombstone mais exclue du suivi actif.",
    tone: "neutral",
    icon: "∅",
    severity: 0,
  },
  OBSERVED: {
    short: "Donnée observée",
    long: "La donnée provient d’une observation réelle et horodatée.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  QUALITY_BLOCKED: {
    short: "Analyse suspendue par prudence",
    long: "La qualité ou la quantité de preuve ne permet pas de poursuivre l’analyse.",
    tone: "attention",
    icon: "◔",
    severity: 1,
  },
  INSUFFICIENT_OBSERVATION: {
    short: "Observations encore insuffisantes",
    long: "Le volume actuel ne permet pas de tirer une conclusion.",
    tone: "attention",
    icon: "◔",
    severity: 1,
  },
  NO_LIVE_SHADOW_DATA: {
    short: "Aucun résultat prospectif publié",
    long: "Aucune décision simulée n’a encore été publiée.",
    tone: "neutral",
    icon: "∅",
    severity: 0,
  },
  R2_REPLAY_VERIFIED: {
    short: "Reconstruction R2 vérifiée",
    long: "Les preuves ont été reconstruites depuis R2 sans appeler de fournisseur.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  RECONSTRUCTIBLE_FROM_R2: {
    short: "Reconstruction R2 disponible",
    long: "Le registre peut être reconstitué à partir des objets append-only vérifiés.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  ACTIVE_AND_VERIFIED: {
    short: "Actif et vérifié",
    long: "Le mécanisme est actif et sa cohérence a été contrôlée.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  CONNECTED_AND_PERSISTED: {
    short: "Connecté et persistant",
    long: "La connexion et la persistance ont été vérifiées.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  HASH_CHAIN_VERIFIED: {
    short: "Chaîne de preuves vérifiée",
    long: "Les empreintes forment une chaîne cohérente et contrôlée.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  LEDGER_VERIFIED: {
    short: "Registre vérifié",
    long: "Le registre public de preuves est cohérent.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  PASS: {
    short: "Contrôle réussi",
    long: "Le contrôle a satisfait son seuil prédéfini.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  PASSED: {
    short: "Contrôle réussi",
    long: "Le contrôle a satisfait son seuil prédéfini.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  FAILED: {
    short: "Contrôle en échec",
    long: "Le contrôle n’a pas satisfait le critère attendu.",
    tone: "critical",
    icon: "!",
    severity: 2,
  },
  ERROR: {
    short: "Erreur technique",
    long: "Une erreur a empêché l’étape de se terminer normalement.",
    tone: "critical",
    icon: "!",
    severity: 3,
    action: "Consulter le détail de l’incident.",
  },
  PREQUENTIAL_LEARNING_FACTORY_READY: {
    short: "Usine prête",
    long: "L’évaluation préquentielle est prête à attendre les premières heures limites et les premiers résultats réels.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  NO_REAL_PREQUENTIAL_ACTIVITY: {
    short: "Aucune activité réelle",
    long: "Aucune prédiction, aucun règlement et aucun entraînement réel ne sont encore enregistrés.",
    tone: "neutral",
    icon: "∅",
    severity: 0,
  },
  FROZEN: {
    short: "Prédiction gelée",
    long: "La prédiction et son contexte sont immuables depuis leur publication avant match.",
    tone: "positive",
    icon: "❄",
    severity: 0,
  },
  REJECTED_LATE: {
    short: "Prédiction trop tardive",
    long: "La tentative a été rejetée parce que son heure limite était dépassée.",
    tone: "critical",
    icon: "◷",
    severity: 2,
  },
  REJECTED_MISSING_GATE: {
    short: "Donnée requise absente",
    long: "La prédiction a été rejetée car une vérification obligatoire n’était pas satisfaite.",
    tone: "attention",
    icon: "◔",
    severity: 1,
  },
  NO_ODDS_REFERENCE: {
    short: "Référence de marché absente",
    long: "Aucune cote admissible n’était disponible pour construire la référence gelée.",
    tone: "attention",
    icon: "◔",
    severity: 1,
  },
  SETTLED: {
    short: "Résultat réglé",
    long: "Le résultat final vérifié a été associé aux prédictions gelées.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  VOID: {
    short: "Rencontre neutralisée",
    long: "La rencontre ne peut pas contribuer aux métriques ni à l’entraînement.",
    tone: "neutral",
    icon: "∅",
    severity: 0,
  },
  TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT: {
    short: "Réentraînement différé",
    long: "Le nombre de nouvelles rencontres réglées ou de ligues représentées reste insuffisant.",
    tone: "information",
    icon: "◌",
    severity: 0,
  },
  INSUFFICIENT_TRAINING_SUPPORT: {
    short: "Support d’entraînement insuffisant",
    long: "Cette portée de modèle attend davantage de rencontres réglées admissibles.",
    tone: "attention",
    icon: "◔",
    severity: 1,
  },
  PROMOTION_LOCKED: {
    short: "Promotion verrouillée",
    long: "Aucune version ne peut devenir automatiquement la nouvelle référence.",
    tone: "positive",
    icon: "▣",
    severity: 0,
  },
  REFERENCE_UNCHANGED: {
    short: "Référence inchangée",
    long: "La référence gelée conserve exactement sa version et son artefact.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  NO_COMPARABLE_SETTLEMENT: {
    short: "Comparaison en attente",
    long: "Aucun règlement prospectif réel ne permet encore de comparer les modèles.",
    tone: "neutral",
    icon: "∅",
    severity: 0,
  },
  WAITING_FOR_RESULTS: {
    short: "Résultats en attente",
    long: "Ce championnat n’a pas encore de rencontre réelle réglée dans le registre préquentiel.",
    tone: "information",
    icon: "◌",
    severity: 0,
  },
  PREQUENTIAL_LEDGER_VERIFIED: {
    short: "Ledger préquentiel vérifié",
    long: "La chaîne de preuves préquentielle est cohérente et ne contient aucune promotion.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  ACTIVE_REFERENCE: {
    short: "Référence active",
    long: "Cette version gelée sert de point de comparaison immuable.",
    tone: "positive",
    icon: "✓",
    severity: 0,
  },
  ACTIVE_CHALLENGER: {
    short: "Challenger actif",
    long: "Cette version est évaluée sans remplacer la référence.",
    tone: "research",
    icon: "◇",
    severity: 0,
  },
  NO_PROMOTION: {
    short: "Aucune promotion",
    long: "Aucun résultat ne satisfait les critères de promotion prédéfinis.",
    tone: "neutral",
    icon: "∅",
    severity: 0,
  },
  INCONCLUSIVE: {
    short: "Résultat non concluant",
    long: "Les données ne permettent pas de départager les hypothèses.",
    tone: "neutral",
    icon: "≈",
    severity: 0,
  },
};

const documentedTechnicalStatuses = `
ADAPTER_ONLY
ACTIVE_FULL
ACTIVE_ODDS_REDUCED
API_FOOTBALL_LIVE_PIPELINE_VERIFIED
API_FOOTBALL_AUTHENTICATED
API_MARKET_BASELINE_READY
API_OOS_BACKTEST_READY
API_PLAYER_DATASET_READY
API_TEAM_DATASET_READY
AUDIT_COMPLETE_VERIFIED
AVAILABLE
CAMPAIGN_BLOCKED
CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2
BLOCKED_BUDGET
BLOCKED_IDENTITY
BLOCKED_PROVIDER_ERROR
DISABLED
COMPUTABLE
CONTROLLED_WITH_CR1_CLUSTER_SIGN_FLIP_CLUSTER_BOOTSTRAP_AND_BH
CONTROL_DATASET_READY
DATA_GATE_BLOCKED
DEMONSTRATED
DESCRIPTIVE_RETROSPECTIVE_DIAGNOSTIC
ELIGIBLE
EMPTY_NO_ROBUST_DEEP_MATCHUP
EVALUATED
EXACT_FIXTURE_PAIRING_VERIFIED
EXECUTED_NO_PROMOTION
EXECUTED_ZERO_SUPPORT_NO_PROMOTION
EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING
EXTERNAL_DATASET_READY
EXTERNAL_VALIDATION_FAILED
EXTERNAL_VALIDATION_PROTOCOL_V1_LOCKED
FIVE_LEAGUE_PROSPECTIVE_EXPANSION_FAILED
FIVE_LEAGUE_PROSPECTIVE_EXPANSION_PARTIAL
FIVE_LEAGUE_PROSPECTIVE_EXPANSION_READY
FIVE_LEAGUE_PROSPECTIVE_EXPANSION_READY_WITH_SCHEDULE_WAIT
FROZEN_TRANSFER_EVALUATED
HISTORICAL_BACKFILL_ACTIVE
HISTORICAL_PILOT_VERIFIED
HISTORICAL_RESEARCH
HISTORICAL_RESEARCH_EVIDENCE
INCONCLUSIVE_OOS
INSUFFICIENT_SAMPLE
JALON6_BASELINE_FROZEN
JALON_9
LEAGUE_SPECIFIC_EVALUATED
LEAVE_ONE_LEAGUE_OUT_READY
LEGACY_SOURCE_ONLY
LIVE_HISTORICAL_ISOLATED
LIVE_PIPELINE_VERIFIED
MARKET_RECALIBRATED_TRAIN_ONLY_TOP_LABEL_ECE_DIAGNOSTIC
MATCH_DATE_CLUSTERED_TEAM_SERIAL_DEPENDENCE_REMAINS_LIMITATION
MODEL_ARENA_ACTIVE
NOT_APPLICABLE_LINEUP_GATE_BLOCKED
NOT_APPLICABLE_PLAYER_GATE_BLOCKED
NO_FIXTURES_IN_CURRENT_HORIZON
NO_1X2_MARKET_ATTRITION
NO_CAUSAL_CLAIM
NO_DECISION_NO_CANDIDATE
NO_EXTERNAL_VALIDATED_EDGE
NO_STRATEGY_PROMOTED
OBJECT_STORAGE_REQUIRED
ONE_TESTED_PLUS_EIGHT_BLOCKED_HYPOTHESES_INCLUDED
ONE_TO_ONE_EXACT_JOIN
PAIRED_EVALUATION_READY
PASSED_BLOCKED_BY_ANTI_LEAKAGE
PAUSE
PLAYER_FEATURE_FACTORY_ACTIVE
PLAYER_GENERALIZATION_INCONCLUSIVE
POOLED_MODEL_EVALUATED
POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE
POST_LINEUP_SIMULATED_READY
POSTGRESQL_AND_GIT_DATA_BRIDGE
PRESEASON_PACKAGE_WAITING_FOR_EXTERNAL_GATES
PRESEASON_SHADOW_PACKAGE_V2_FROZEN
PRIMARY_CORRECTIVE_NON_PROMOTABLE_TEAM_GATE_PARTIAL
PRIMARY_FIXED_NO_TEST_SET_MODEL_SELECTION
READY
REFERENCE_RAW_MARKET
REFERENCE_RECALIBRATED_TRAIN_ONLY
REGULAR_SEASON_CANONICAL
REJECTED_BY_FEATURE_ALLOWLIST
REJECTED_BY_PAIRING_GUARD
REJECTED_BY_TEMPORAL_GUARD
REJECTED_OOS
REPLAY_CONFIRMED
REPLAY_VERIFIED
RESOLVED
SAFE
SCORE_MODEL_READY
SHADOW_COLLECTION_HARDENED
SIX_COMPUTATIONAL_OR_GUARD_CONTROLS_EXECUTED_SIX_DATA_GATED
SOURCE_PRICE_CLASS_ONLY
STABLE
TARGET_EXCLUDED_BUT_TEAM_SOURCE_OBSERVED_AT_UNPROVEN_GATE_PARTIAL
TARGET_KICKOFF_EXCLUSIVE_BOUNDARY_NOT_STRICT_OBSERVED_AT
TESTING
UNAVAILABLE
UNKNOWN
UNSTABLE
WAITING_FOR_BACKFILL_GATES
WAITING_FOR_EXTERNAL_GATES
WAITING_FOR_FIXTURES
WARN
WARNING
WORKFLOW_SUCCESS_LIVE_DATA
`.trim().split(/\s+/);

for (const value of documentedTechnicalStatuses) {
  if (catalogue[value]) continue;
  const critical = /FAILED|REJECTED|UNAVAILABLE|UNSTABLE/.test(value);
  const waiting = /WAITING|BLOCKED|PAUSE|INSUFFICIENT|REQUIRED/.test(value);
  catalogue[value] = {
    short: critical
      ? "Contrôle technique non satisfait"
      : waiting
        ? "Vérification encore nécessaire"
        : "État technique documenté",
    long: critical
      ? "Cet état expert signale qu’un contrôle scientifique ou opérationnel n’est pas satisfait."
      : waiting
        ? "Cet état expert est catalogué mais attend encore une preuve ou une étape prévue."
        : "Cet état expert est catalogué ; sa valeur technique originale reste visible en vue expert.",
    tone: critical ? "critical" : waiting ? "attention" : "research",
    icon: critical ? "!" : waiting ? "◔" : "◇",
    severity: critical ? 2 : waiting ? 1 : 0,
  };
}

const fallback: StatusPresentation = {
  short: "État en cours de vérification",
  long: "Le catalogue de traduction ne couvre pas encore cette valeur technique.",
  tone: "attention",
  icon: "◔",
  severity: 1,
  action: "Compléter le catalogue avant une présentation publique spécifique.",
};

const warnedStatuses = new Set<string>();

export function statusPresentation(value: string): StatusPresentation {
  if (!catalogue[value] && !warnedStatuses.has(value)) {
    warnedStatuses.add(value);
    console.warn(`[Robin Experience] statut non catalogué : ${value}`);
  }
  return catalogue[value] ?? fallback;
}

export const statusCatalogue = catalogue;
