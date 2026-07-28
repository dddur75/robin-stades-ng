import { readFile, writeFile } from "node:fs/promises";

import { buildPresentationModel } from "../app/lib/presentation-model";

const inputUrl = new URL("../app/cockpit-data.json", import.meta.url);
const outputUrl = new URL("../app/cockpit-presentation.json", import.meta.url);
const expertOutputUrl = new URL("../app/cockpit-expert-data.json", import.meta.url);
const snapshot = JSON.parse(await readFile(inputUrl, "utf8")) as unknown;
const presentation = buildPresentationModel(snapshot);
const snapshotRecord = snapshot as Record<string, unknown>;
const deepData = snapshotRecord.deepData as Record<string, unknown>;
const publicPresentation = {
  dashboard: presentation.dashboard,
  matches: presentation.matches,
  nextCaptures: presentation.nextCaptures,
  observatory: presentation.observatory,
  hypotheses: presentation.hypotheses,
  system: presentation.system,
  oddsSnapshots: presentation.oddsSnapshots,
};

await writeFile(
  outputUrl,
  `${JSON.stringify(publicPresentation, null, 2)}\n`,
  "utf8",
);

await writeFile(
  expertOutputUrl,
  `${JSON.stringify({
    datasets: deepData.datasets,
    models: deepData.models,
    backtests: deepData.backtests,
    qualityChecks: snapshotRecord.qualityChecks,
    providers: snapshotRecord.providers,
    incidents: snapshotRecord.incidents,
    quota: snapshotRecord.quota,
    provenance: snapshotRecord.provenance,
    externalValidation: deepData.externalValidation,
    matchup: snapshotRecord.matchupLab,
    patternResearch: snapshotRecord.patternResearch,
  }, null, 2)}\n`,
  "utf8",
);
