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
  LIVE_PROSPECTIVE_CAPTURE: {
    short: "Observations pré-match en cours",
    long: "La collecte prospective est active et reste strictement antérieure au match.",
    tone: "information",
    icon: "●",
    severity: 0,
  },
  PROSPECTIVE_GATES_ACCUMULATING: {
    short: "Les données s’accumulent progressivement",
    long: "Les vérifications prospectives restent fermées jusqu’au volume de preuve requis.",
    tone: "research",
    icon: "↗",
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
  CAPTURED: {
    short: "Capture vérifiée",
    long: "La capture a été enregistrée avec sa provenance et son empreinte.",
    tone: "positive",
    icon: "✓",
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
    short: "Replay R2 vérifié",
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

const fallback: StatusPresentation = {
  short: "État technique disponible",
  long: "Le détail de cet état est réservé à la vue expert.",
  tone: "neutral",
  icon: "·",
  severity: 0,
};

export function statusPresentation(value: string): StatusPresentation {
  return catalogue[value] ?? fallback;
}

export const statusCatalogue = catalogue;
