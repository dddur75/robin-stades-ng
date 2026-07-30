import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { HistoricalEvidenceUnavailableContent } from "../app/components/common/historical-evidence-unavailable-content";
import {
  HistoricalRankingAnalysisMetrics,
  HistoricalRankingCard,
} from "../app/components/hypotheses/historical-evidence-rankings-page";
import { MetricExplainer } from "../app/components/hypotheses/hypothesis-primitives";
import type { HistoricalEvidenceRankingEntry } from "../app/lib/hypothesis-evidence.server";

const entry = {
  category: "historical_raw",
  competition: "Serie A",
  cutoff: null,
  evidence: {
    confidenceInterval: [0.0043, 0.3139],
    correctedFalsePositiveRisk: 1,
    maximumDrawdown: 19.52,
    phase: "historical",
    profitUnits: 57.88,
    roi: 0.1594,
    stability: null,
    support: 363,
  },
  evidenceScope: "GLOBAL",
  family: "MATCH_RESULT",
  hypothesisId: "J10-M002",
  labelFr: "Match nul en Serie A",
  market: "1X2_DRAW",
  membershipSetHash: "membership-test",
  metrics: {
    averageOdds: 3.0949,
    confidenceInterval: [0.0043, 0.3139],
    correctedFalsePositiveRisk: 1,
    eligibleFolds: 4,
    hitRate: 0.3747,
    longestLosingStreak: 8,
    losses: 227,
    maximumDrawdownUnits: 19.52,
    medianOdds: 3,
    occurrences: 363,
    pValue: 0.25,
    positiveFolds: 4,
    profitUnits: 57.88,
    roi: 0.1594,
    settledOccurrences: 363,
    voids: 0,
    wins: 136,
  },
  origin: "GLOBAL",
  rank: 2,
  ruleHash: "rule-test",
  scientificStatus: "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING",
  selection: "DRAW",
  tieBreakKey: "rule-test",
} satisfies HistoricalEvidenceRankingEntry;

function visibleText(html: string) {
  return html.replace(/<[^>]+>/gu, " ").replace(/\s+/gu, " ").trim();
}

test("la carte Découverte conserve l’essentiel et masque les mesures Analyse", () => {
  const text = visibleText(
    renderToStaticMarkup(
      createElement(HistoricalRankingCard, { entry }),
    ),
  );

  assert.match(text, /Occurrences historiques/u);
  assert.match(text, /Taux de réussite/u);
  assert.match(text, /ROI historique brut/u);
  assert.match(text, /Profit simulé/u);
  assert.doesNotMatch(
    text,
    /Cote moyenne|Intervalle historique|Périodes positives|Baisse maximale|Risque de faux positif|Stabilité hors échantillon|Concentration/u,
  );
});

test("le complément Analyse publie l’intervalle et explicite les absences", () => {
  const text = visibleText(
    renderToStaticMarkup(
      createElement(HistoricalRankingAnalysisMetrics, { entry }),
    ),
  );

  assert.match(text, /Cote moyenne 3,09/u);
  assert.match(text, /Intervalle historique \+0,43\s*% à \+31,39\s*%/u);
  assert.match(text, /Périodes positives 4\/4/u);
  assert.match(text, /Baisse maximale 19,52 u/u);
  assert.match(text, /Risque de faux positif après correction 1,00/u);
  assert.match(
    text,
    /Stabilité hors échantillon Non disponible dans le classement compact/u,
  );
  assert.match(
    text,
    /Concentration Non disponible dans le classement compact/u,
  );
});

test("les explications techniques de mesure ne sont pas rendues hors Expert", () => {
  const html = renderToStaticMarkup(
    createElement(MetricExplainer, {
      expert: "CONTRAT_TECHNIQUE_BRUT",
      name: "Intervalle",
      simple: "La zone d’incertitude autour du résultat.",
    }),
  );

  assert.match(html, /La zone d’incertitude autour du résultat\./u);
  assert.doesNotMatch(html, /CONTRAT_TECHNIQUE_BRUT/u);
});

test("l’indisponibilité reste française et réserve le code brut à Expert", () => {
  const html = renderToStaticMarkup(
    createElement(HistoricalEvidenceUnavailableContent, {
      className: "test-state",
      code: "HISTORICAL_EVIDENCE_RAW_FAILURE",
      retryHref: "/hypotheses/J10-M002/matchs",
    }),
  );
  const text = visibleText(html);

  assert.match(
    text,
    /Cette preuve historique ne peut pas être chargée pour le moment\./u,
  );
  assert.match(text, /Réessayer depuis cette page/u);
  assert.doesNotMatch(text, /HISTORICAL_EVIDENCE_RAW_FAILURE/u);
});
