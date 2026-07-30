import rawHypothesisGlossary from "../hypothesis-glossary-data.json";

const hypothesisGlossary = rawHypothesisGlossary as Record<string, string>;

export type GlossaryEntry = {
  term: string;
  publicName: string;
  simple: string;
  expert: string;
  example?: string;
};

const coreGlossary: GlossaryEntry[] = [
  { term: "Pattern", publicName: "Régularité observée", simple: "Une répétition repérée dans les données.", expert: "Une structure statistique candidate, qui doit encore résister aux contrôles multiples et prospectifs." },
  { term: "Hypothèse", publicName: "Question de recherche", simple: "Une idée précise que Robin cherche à vérifier.", expert: "Une proposition préréglée avec mécanisme, variables, seuils et critères de rejet." },
  { term: "Backtest", publicName: "Simulation historique", simple: "Un test d’une règle sur des matchs déjà joués.", expert: "Une évaluation hors échantillon ou walk-forward respectant la disponibilité temporelle des variables." },
  { term: "Test prospectif", publicName: "Test sur les prochains matchs", simple: "Un test décidé avant de connaître le résultat.", expert: "Une évaluation gelée ex ante, fondée sur des captures point-in-time et des décisions append-only." },
  { term: "Shadow", publicName: "Simulation sans argent", simple: "Robin enregistre ce qu’il aurait décidé, sans miser.", expert: "Un registre prospectif de décisions et règlements fictifs, sans connexion bookmaker." },
  { term: "NO BET", publicName: "Aucun pari", simple: "Robin décide de ne rien proposer.", expert: "Décision explicite par défaut lorsqu’aucun candidat ne franchit tous les critères." },
  { term: "Cote", publicName: "Cote", simple: "Le prix proposé par un bookmaker pour un résultat.", expert: "Un prix décimal horodaté, associé à un fournisseur, un marché et une fraîcheur." },
  { term: "Marge bookmaker", publicName: "Marge du bookmaker", simple: "La part intégrée par le bookmaker dans ses prix.", expert: "La somme des probabilités implicites au-delà de 100 %, avant dé-vigage." },
  { term: "Probabilité de-viguée", publicName: "Probabilité corrigée de la marge", simple: "Une probabilité estimée après retrait de la marge du bookmaker.", expert: "Une normalisation des probabilités implicites destinée à produire une référence de marché comparable." },
  { term: "Bankroll fictive", publicName: "Capital de simulation", simple: "Un compteur virtuel pour suivre les décisions simulées.", expert: "Un ledger en unités sans valeur monétaire, mis à jour uniquement après règlement vérifié." },
  { term: "Log Loss", publicName: "Erreur des probabilités", simple: "Pénalise fortement une prédiction très sûre mais fausse.", expert: "Perte logarithmique moyenne multiclasses sur un jeu apparié." },
  { term: "Score de Brier", publicName: "Score de Brier", simple: "Mesure l’écart entre les probabilités annoncées et les résultats observés.", expert: "Erreur quadratique moyenne appliquée aux probabilités multiclasses." },
  { term: "Calibration", publicName: "Fiabilité des probabilités", simple: "Vérifie si 60 % annoncé arrive environ 6 fois sur 10.", expert: "Concordance entre confiance prédite et fréquence empirique, évaluée hors échantillon." },
  { term: "Intervalle de confiance", publicName: "Zone d’incertitude", simple: "Une plage plausible autour d’une estimation.", expert: "Un intervalle bootstrap groupé tenant compte de la dépendance entre observations." },
  { term: "FDR", publicName: "Contrôle des faux résultats", simple: "Réduit le risque de retenir une coïncidence parmi beaucoup de tests.", expert: "False Discovery Rate, contrôlé ici par une correction de Benjamini–Hochberg." },
  { term: "Point-in-time", publicName: "Disponible à cet instant", simple: "Une donnée dont on prouve qu’elle existait avant le match.", expert: "Contrainte temporelle imposant response_received_at avant cutoff_at, lui-même avant kickoff_at." },
  { term: "Fenêtre de capture", publicName: "Moment prévu de collecte", simple: "Un intervalle où Robin cherche une famille de données.", expert: "Une unité planifiée, idempotente et bornée par une ouverture, une échéance et un cutoff." },
  { term: "Cutoff", publicName: "Heure limite", simple: "Après cette heure, la donnée est considérée trop tardive.", expert: "Borne temporelle stricte qui sépare preuve pré-match et information tardive." },
  { term: "Gate", publicName: "Vérification obligatoire", simple: "Une porte qui reste fermée tant qu’une preuve manque.", expert: "Un prédicat versionné sur couverture, temporalité, qualité et support minimal." },
  { term: "Replay", publicName: "Reconstruction", simple: "Robin reconstitue l’état depuis les preuves stockées.", expert: "Réexécution déterministe sans appel fournisseur ni consommation de crédit." },
  { term: "R2", publicName: "Stockage de preuves", simple: "L’espace qui conserve les captures immuables.", expert: "Stockage objet append-only utilisé comme source durable des payloads et reçus." },
  { term: "PostgreSQL", publicName: "Registre structuré", simple: "La base qui organise les fenêtres, reçus et états.", expert: "Base relationnelle de projection, reconstructible depuis les preuves R2 vérifiées." },
];

const contractDefinitions: Record<
  string,
  Pick<GlossaryEntry, "simple" | "expert">
> = {
  Drawdown: {
    simple:
      "La plus forte baisse du capital de simulation avant une éventuelle remontée.",
    expert:
      "Écart maximal entre un sommet du capital simulé et le creux qui le suit.",
  },
  Feature: {
    simple: "Une information précise utilisée pour étudier une hypothèse.",
    expert:
      "Variable versionnée et disponible à l’heure limite, utilisée par une règle ou un modèle.",
  },
  FDR: {
    simple:
      "Un contrôle qui limite les coïncidences retenues lorsque beaucoup d’idées sont testées.",
    expert:
      "False Discovery Rate contrôlé par une correction de Benjamini–Hochberg.",
  },
  Gate: {
    simple:
      "Une vérification qui reste fermée tant qu’une preuve nécessaire manque.",
    expert:
      "Prédicat versionné sur la couverture, la temporalité, la qualité et le support minimal.",
  },
  "q-value": {
    simple:
      "Une estimation prudente du risque qu’un résultat retenu soit un faux positif.",
    expert:
      "Plus petit niveau de False Discovery Rate auquel le résultat resterait sélectionné.",
  },
  "Walk-forward": {
    simple:
      "Une validation qui apprend sur le passé puis vérifie sur la période suivante, sans regarder l’avenir.",
    expert:
      "Évaluation chronologique glissante avec fenêtres d’apprentissage et de test strictement ordonnées.",
  },
};
const contractPublicNames: Partial<Record<string, string>> = {
  Drawdown: "Baisse maximale du capital simulé",
};

const contractGlossary = Object.entries(hypothesisGlossary)
  .filter(([key]) => key !== "note" && key !== "schema_version")
  .map<GlossaryEntry>(([publicName, term]) => ({
    term,
    publicName: contractPublicNames[term] ?? publicName,
    simple:
      contractDefinitions[term]?.simple ??
      "Une notion définie par le contrat scientifique de l’univers.",
    expert:
      contractDefinitions[term]?.expert ??
      "Terme technique conservé pour assurer la traçabilité du contrat.",
  }));
const contractTerms = new Set(contractGlossary.map((entry) => entry.term));

export const glossary: GlossaryEntry[] = [
  ...coreGlossary.filter((entry) => !contractTerms.has(entry.term)),
  ...contractGlossary,
];

export function glossaryEntry(term: string) {
  return glossary.find((entry) => entry.term === term);
}
