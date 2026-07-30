import assert from "node:assert/strict";
import test from "node:test";

import {
  buildBankrollGeometry,
  buildDivergingBars,
  chartDomain,
  computeConcentrationShares,
  historicalMatchAccessibleLabel,
  historicalMatchHref,
  historicalMatchPublicLabel,
  scaleLinear,
} from "../app/components/hypotheses/historical-evidence-chart-utils";

test("la bankroll ajoute toujours une origine à zéro et mesure les drawdowns", () => {
  const geometry = buildBankrollGeometry([2, 1, 3, -1, 3]);

  assert.equal(geometry.points[0]?.value, 0);
  assert.equal(geometry.points.length, 6);
  assert.equal(geometry.maxDrawdown, 4);
  assert.deepEqual(
    geometry.drawdownZones.map((zone) => ({
      endIndex: zone.endIndex,
      peakValue: zone.peakValue,
      startIndex: zone.startIndex,
      troughValue: zone.troughValue,
    })),
    [
      { endIndex: 3, peakValue: 2, startIndex: 1, troughValue: 1 },
      { endIndex: 5, peakValue: 3, startIndex: 3, troughValue: -1 },
    ],
  );
  assert.deepEqual(
    geometry.segments.map((segment) => segment.drawdown),
    [false, true, false, true, false],
  );
});

test("le domaine reste honnête autour de zéro et la mise à l’échelle conserve les bornes", () => {
  const [minimum, maximum] = chartDomain([10, 20], true, 0);
  assert.equal(minimum, 0);
  assert.equal(maximum, 20);
  assert.equal(scaleLinear(0, minimum, maximum, 100, 0), 100);
  assert.equal(scaleLinear(20, minimum, maximum, 100, 0), 0);
});

test("les barres divergentes partagent le même axe zéro", () => {
  const geometry = buildDivergingBars([-2, 0, 4]);
  const [negative, zero, positive] = geometry.bars;

  assert.ok(negative);
  assert.ok(zero);
  assert.ok(positive);
  assert.ok(negative.endX < geometry.zeroX);
  assert.equal(zero.endX, geometry.zeroX);
  assert.ok(positive.endX > geometry.zeroX);
  assert.equal(positive.width, (geometry.width - 60 - 190) / 2);
});

test("les parts de concentration utilisent le dénominateur explicite lorsqu’il existe", () => {
  assert.deepEqual(computeConcentrationShares([25, 15, 10], 100), [
    0.25,
    0.15,
    0.1,
  ]);
  assert.deepEqual(computeConcentrationShares([25, 15, 10]), [0.5, 0.3, 0.2]);
  assert.deepEqual(computeConcentrationShares([0, 0]), [0, 0]);
});

test("le lien historique est explicite et encode l’identifiant du match", () => {
  assert.equal(
    historicalMatchHref({ matchId: "Premier League/2024 10" }),
    "/matchs/historique/Premier%20League%2F2024%2010",
  );
  assert.equal(
    historicalMatchHref({
      matchHref: "/preuves/match-personnalise",
      matchId: "ignoré",
    }),
    "/preuves/match-personnalise",
  );
  assert.equal(historicalMatchHref({}), undefined);
});

test("les libellés publics utilisent la rencontre humaine et jamais l’identifiant", () => {
  const reference = {
    matchDate: "2024-01-02",
    matchId: "api-football:123",
    matchLabel: "Home – Away",
  };
  assert.equal(historicalMatchPublicLabel(reference), "Home – Away");
  const accessible = historicalMatchAccessibleLabel(reference);
  assert.match(accessible, /^Home – Away, /u);
  assert.match(accessible, /2024/u);
  assert.doesNotMatch(accessible, /api-football/iu);
  assert.equal(
    historicalMatchPublicLabel({ matchId: "api-football:123" }),
    "Match historique de référence",
  );
});
