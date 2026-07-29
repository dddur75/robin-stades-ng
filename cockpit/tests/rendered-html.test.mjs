import assert from "node:assert/strict";
import { access, readdir, readFile, stat } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const snapshot = JSON.parse(
  await readFile(new URL("../app/cockpit-data.json", import.meta.url), "utf8"),
);
const firstFixture = snapshot.prospectiveObservatory.fixtures.registry[0];
const unresolvedTeam = "Équipe en cours d’identification";
const firstHome = firstFixture.home_name ?? unresolvedTeam;
const firstAway = firstFixture.away_name ?? unresolvedTeam;

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${path}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request(`http://localhost${path}`, {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

function visibleText(html) {
  return html
    .replace(/<script\b[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ");
}

const publicRoutes = [
  ["/", "Robin suit les cinq grands championnats"],
  ["/robin-live", "À comprendre aujourd’hui"],
  ["/matchs", "Les matchs observés"],
  ["/observatoire", "Matrice de couverture"],
  ["/apprentissage", "Robin apprend uniquement après les matchs"],
  ["/laboratoire", "Laboratoire des hypothèses"],
  ["/resultats", "Aucun pari simulé pour le moment"],
  ["/methode", "Comment Robin travaille"],
  ["/expert", "Activez la vue expert"],
];

test("rend toutes les routes Robin Experience V1 en français", async () => {
  for (const [path, expected] of publicRoutes) {
    const response = await render(path);
    assert.equal(response.status, 200, path);
    assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
    const html = await response.text();
    assert.match(html, /<html lang="fr-FR"/);
    assert.match(html, new RegExp(expected));
    assert.match(html, /Vue essentielle/);
    assert.match(html, /Vue expert/);
    assert.match(html, /Glossaire Robin/);
    assert.match(html, /Aucun pari réel/);
  }
});

test("rend une vraie fiche match avec ses états vides pédagogiques", async () => {
  const response = await render(`/matchs/${firstFixture.fixture_id}`);
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, new RegExp(firstHome));
  assert.match(html, new RegExp(firstAway));
  assert.match(html, /Synthèse/);
  assert.match(html, /Chronologie/);
  assert.match(html, /Niveau de couverture/);
  assert.doesNotMatch(visibleText(html), /PRODUCTION_LOCKED|BLOCKED_BY_COVERAGE/);
});

test("n’expose ni anciens libellés anglais ni statuts techniques bruts en vue publique", async () => {
  const forbiddenLabels = [
    "Command Center",
    "Coverage Explorer",
    "Odds Explorer",
    "Match Center",
    "Shadow Performance",
    "Data Explorer",
    "Backfill Monitor",
    "Dataset Readiness",
    "Player Explorer",
    "Lineup Explorer",
    "Feature Lab",
    "Model Lab",
    "Scientific Model Arena",
    "Matchup Lab",
    "External Validation",
    "Strategy Lab",
    "Backtest Explorer",
    "Historical Data Quality",
  ];
  const forbiddenStatuses = [
    "BLOCKED_BY_COVERAGE",
    "WAITING_FOR_OBSERVATIONS",
    "LIVE_PROSPECTIVE_CAPTURE",
    "PROSPECTIVE_GATES_ACCUMULATING",
    "PRODUCTION_LOCKED",
    "STORAGE_PAUSED",
    "PROMOTION_LOCKED",
    "TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT",
  ];
  for (const [path] of publicRoutes.filter(([route]) => route !== "/expert")) {
    const text = visibleText(await (await render(path)).text());
    for (const label of forbiddenLabels) assert.doesNotMatch(text, new RegExp(label), `${path}: ${label}`);
    for (const status of forbiddenStatuses) assert.doesNotMatch(text, new RegExp(status), `${path}: ${status}`);
  }
});

test("préserve exactement les invariants et les résultats scientifiques du snapshot", async () => {
  const data = JSON.parse(
    await readFile(new URL("../app/cockpit-data.json", import.meta.url), "utf8"),
  );
  const simulationPolicy = JSON.parse(
    await readFile(new URL("../../configs/shadow_simulation_v1.json", import.meta.url), "utf8"),
  );
  assert.equal(
    data.patternResearch.bankroll.initialUnits,
    simulationPolicy.initial_bankroll_units,
  );
  assert.equal(
    data.patternResearch.bankroll.currentUnits,
    data.patternResearch.bankroll.curve.at(-1),
  );
  assert.equal(data.patternResearch.results.roi, null);
  assert.equal(data.patternResearch.productionStatus, "PRODUCTION_LOCKED");
  assert.equal(data.patternResearch.realBets, false);
  assert.equal(data.patternResearch.noBetDefault, true);
  assert.equal(data.patternResearch.socialPublishingEnabled, false);
  assert.equal(data.patternResearch.demoModeEnabled, false);
  assert.equal(data.matchupLab.costs.storageStatus, "STORAGE_PAUSED");
  assert.equal(data.matchupLab.costs.secondaryTasks, "P3_P4_PAUSED");
  assert.equal(data.matchupLab.promotion.promoted, false);
  assert.equal(data.matchupLab.decision.decisions, 0);
  assert.equal(data.matchupLab.replay.providerCalls, 0);
  assert.equal(data.matchupLab.replay.oddsApiCredits, 0);
  assert.equal(data.prospectiveObservatory.invariants.raw_payloads_in_git, 0);
  assert.equal(data.prequentialLearning.schema_version, "prequential-learning-status-v1");
  assert.equal(data.prequentialLearning.predictions.frozen, 0);
  assert.equal(data.prequentialLearning.settlements.fixtures, 0);
  assert.equal(data.prequentialLearning.training.runs, 0);
  assert.equal(data.prequentialLearning.promotion_status, "PROMOTION_LOCKED");
  assert.deepEqual(data.prequentialLearning.security, {
    production_locked: true,
    real_bets: false,
    no_bet_default: true,
    social_publishing_enabled: false,
  });
});

test("sépare l’apprentissage réel des historiques et masque le ROI sans décision", async () => {
  const learning = visibleText(await (await render("/apprentissage")).text());
  const results = visibleText(await (await render("/resultats")).text());
  assert.match(
    learning,
    /Robin apprend uniquement après les matchs, sans modifier les prédictions déjà publiées\./,
  );
  assert.match(learning, /Aucune prédiction réelle gelée/);
  assert.match(learning, /replays historiques et les fixtures synthétiques ne sont pas comptés ici/);
  assert.doesNotMatch(results, /\bROI\b/);
});

test("inclut navigation, accessibilité structurelle et formats français", async () => {
  const html = await (await render("/robin-live")).text();
  assert.match(html, /href="\/matchs"/);
  assert.match(html, /href="\/observatoire"/);
  assert.match(html, /href="\/apprentissage"/);
  assert.match(html, /href="\/laboratoire"/);
  assert.match(html, /href="\/resultats"/);
  assert.match(html, /href="\/methode"/);
  assert.match(html, /href="\/expert/);
  assert.match(html, /aria-label="Navigation principale"/);
  assert.match(html, /Aller au contenu principal/);
  assert.match(html, /<main id="contenu-principal"/);
  const formattedBankroll = new Intl.NumberFormat("fr-FR", {
    maximumFractionDigits: 1,
  }).format(snapshot.patternResearch.bankroll.currentUnits);
  assert.match(html, new RegExp(`${formattedBankroll.replace(/\s/g, "[\\s\\u202f]")} unités`));
  assert.match(html, new RegExp(new Date(snapshot.prospectiveObservatory.generated_at).getUTCFullYear().toString()));
  assert.doesNotMatch(html, /1,000|Jul 27, 2026|24\.1 KB/);
});

test("livre un bundle borné et les métadonnées Robin", async () => {
  const [layout, packageJson] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  assert.match(layout, /Observer avant de conclure/);
  assert.match(layout, /locale: "fr_FR"/);
  assert.match(layout, /twitter:/);
  assert.match(layout, /images: \["\/og\.png"\]/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  const assetsDir = new URL("../dist/client/assets/", import.meta.url);
  const files = await readdir(assetsDir);
  const jsFiles = files.filter((file) => file.endsWith(".js"));
  const totalBytes = (
    await Promise.all(jsFiles.map((file) => stat(new URL(file, assetsDir))))
  ).reduce((sum, item) => sum + item.size, 0);
  assert.ok(totalBytes < 1_000_000, `bundle client: ${totalBytes} octets`);
  await access(new URL("../public/og.png", import.meta.url));
});

test("ne conserve aucun squelette de démarrage", async () => {
  try {
    assert.deepEqual(
      await readdir(new URL("../app/_sites-preview", import.meta.url)),
      [],
    );
  } catch (error) {
    assert.equal(error.code, "ENOENT");
  }
  await assert.rejects(access(new URL("package-lock.json", root)));
});
