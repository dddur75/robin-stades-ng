import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { HypothesisBankrollChart } from "../app/components/hypotheses/hypothesis-bankroll-chart";
import { HypothesisFoldValidation } from "../app/components/hypotheses/hypothesis-fold-validation";
import { HypothesisOddsDistribution } from "../app/components/hypotheses/hypothesis-odds-distribution";
import { HypothesisSeasonBreakdown } from "../app/components/hypotheses/hypothesis-season-breakdown";
import { HypothesisTeamConcentration } from "../app/components/hypotheses/hypothesis-team-concentration";

const reference = {
  matchDate: "2024-01-02",
  matchHref: "/matchs/historique/api-football%3A123",
  matchId: "api-football:123",
  matchLabel: "Home FC – Away FC",
} as const;

test("graphiques et tableaux accessibles n’exposent jamais l’identifiant technique", () => {
  const html = [
    renderToStaticMarkup(
      createElement(HypothesisBankrollChart, {
        points: [
          {
            ...reference,
            cumulativeProfitUnits: 1,
            playedAt: "2024-01-02",
          },
        ],
      }),
    ),
    renderToStaticMarkup(
      createElement(HypothesisSeasonBreakdown, {
        seasons: [
          {
            ...reference,
            losses: 0,
            matches: 1,
            profitUnits: 1,
            roi: 1,
            season: "2024",
            wins: 1,
          },
        ],
      }),
    ),
    renderToStaticMarkup(
      createElement(HypothesisOddsDistribution, {
        bins: [
          {
            ...reference,
            label: "2,00–2,99",
            matches: 1,
            maximumOdds: 3,
            minimumOdds: 2,
            profitUnits: 1,
            wins: 1,
          },
        ],
      }),
    ),
    renderToStaticMarkup(
      createElement(HypothesisFoldValidation, {
        folds: [
          {
            ...reference,
            fold: 1,
            label: "Saison 2024",
            matches: 1,
            positive: true,
            profitUnits: 1,
            roi: 1,
          },
        ],
        interpretation: "chronological-periods",
      }),
    ),
    renderToStaticMarkup(
      createElement(HypothesisTeamConcentration, {
        items: [
          {
            ...reference,
            losses: 0,
            matches: 1,
            profitUnits: 1,
            share: 0.5,
            team: "Home FC",
            voids: 0,
            wins: 1,
          },
        ],
        totalMatches: 2,
      }),
    ),
  ].join("");

  assert.match(
    html,
    /href="\/matchs\/historique\/api-football%3A123"/u,
  );
  const publicMarkup = html.replace(/\shref="[^"]*"/gu, "");
  assert.match(publicMarkup, /Home FC – Away FC/u);
  assert.match(
    publicMarkup,
    /aria-label="Ouvrir le match(?: de référence)? Home FC – Away FC/iu,
  );
  assert.doesNotMatch(publicMarkup, /api-football(?::|%3A)/iu);
});
