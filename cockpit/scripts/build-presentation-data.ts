import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { buildPresentationModel } from "../app/lib/presentation-model";

const inputUrl = new URL("../app/cockpit-data.json", import.meta.url);
const outputUrl = new URL("../app/cockpit-presentation.json", import.meta.url);
const expertOutputUrl = new URL("../app/cockpit-expert-data.json", import.meta.url);
const hypothesisOutputUrl = new URL(
  "../app/hypothesis-universe-data.json",
  import.meta.url,
);
const hypothesisGlossaryOutputUrl = new URL(
  "../app/hypothesis-glossary-data.json",
  import.meta.url,
);
const hypothesisContractRoot = new URL(
  "../../reports/hypothesis-genome/",
  import.meta.url,
);
const hypothesisNodeArtifactRoot = new URL(
  "../../artifacts/hypothesis-genome/hypothesis-tree-node-pages/",
  import.meta.url,
);
const hypothesisNodePublicRoot = new URL(
  "../public/data/hypotheses/nodes/",
  import.meta.url,
);
const hypothesisContractNames = [
  "hypothesis-universe-summary",
  "hypothesis-family-catalog",
  "hypothesis-tags-catalog",
  "hypothesis-facets",
  "hypothesis-tree-root-index",
  "hypothesis-family-tree-index",
  "hypothesis-global-rankings",
  "hypothesis-rankings-by-competition",
  "hypothesis-rankings-by-family",
  "hypothesis-status-funnel",
  "hypothesis-live-activity",
  "hypothesis-glossary-fr",
  "competition-identity-catalog",
  "campaign-catalog",
  "prospective-freeze-provenance-v2",
  "security-locks",
  "manifest",
] as const;

type JsonRecord = Record<string, unknown>;

async function readJson(url: URL): Promise<JsonRecord> {
  return JSON.parse(await readFile(url, "utf8")) as JsonRecord;
}

type NodePageManifestEntry = {
  page?: number;
  records?: number;
  sha256?: string;
};

function frozenManifestHash(contents: Buffer) {
  // The frozen pages were hashed after Python translated newlines to CRLF on
  // Windows. Treat LF and CRLF as the same JSON artifact so a Linux checkout
  // can reproduce the contract without weakening any content comparison.
  const manifestNewlines = contents
    .toString("utf8")
    .replace(/\r\n?/g, "\n")
    .replace(/\n/g, "\r\n");
  return createHash("sha256").update(manifestNewlines).digest("hex");
}

async function nodeArtifactsMatchManifest(
  root: URL,
  manifest: NodePageManifestEntry[],
) {
  if (manifest.length === 0) return false;
  for (const [index, entry] of manifest.entries()) {
    const page = entry.page ?? index + 1;
    const fileName = `page-${String(page).padStart(3, "0")}.json`;
    try {
      const contents = await readFile(new URL(fileName, root));
      if (
        entry.sha256 &&
        frozenManifestHash(contents) !== entry.sha256
      ) {
        return false;
      }
    } catch {
      return false;
    }
  }
  return true;
}

async function ensureHypothesisNodeArtifacts(): Promise<{
  root: URL;
  temporaryRoot?: string;
}> {
  const treeIndex = (await readJson(
    new URL("hypothesis-tree-root-index.json", hypothesisContractRoot),
  )) as {
    page_manifest?: NodePageManifestEntry[];
  };
  const manifest = treeIndex.page_manifest ?? [];
  if (await nodeArtifactsMatchManifest(hypothesisNodeArtifactRoot, manifest)) {
    return { root: hypothesisNodeArtifactRoot };
  }

  // A clean checkout intentionally omits detailed pages. Rebuild them into an
  // isolated temporary directory: the frontend build must never rewrite the
  // frozen reports or any scientific contract in the repository.
  const temporaryRoot = await mkdtemp(
    join(tmpdir(), "robin-hypothesis-pages-"),
  );
  const temporaryReportRoot = join(temporaryRoot, "reports");
  const temporaryArtifactOutput = join(temporaryRoot, "artifacts");
  const temporaryNodeRoot = pathToFileURL(
    `${join(temporaryArtifactOutput, "hypothesis-tree-node-pages")}${sep}`,
  );

  const provenance = (await readJson(
    new URL("prospective-freeze-provenance-v2.json", hypothesisContractRoot),
  )) as {
    frozen_at?: unknown;
    generator_hash?: unknown;
    source_code_revision?: unknown;
    source_tree_hash?: unknown;
  };
  const required = [
    provenance.source_code_revision,
    provenance.source_tree_hash,
    provenance.generator_hash,
    provenance.frozen_at,
  ];
  if (required.some((value) => typeof value !== "string")) {
    throw new Error("HYPOTHESIS_NODE_PROVENANCE_INCOMPLETE");
  }

  const repositoryRoot = fileURLToPath(new URL("../../", import.meta.url));
  // Only the generator hash contributes to tree-node payloads. Passing the
  // complete freeze provenance would also rebuild prospective contracts and
  // require the intentionally untracked 700-rule J10 registry. The frozen page
  // manifest below remains the authority for byte-for-byte equivalence.
  const args = [
    "scripts/build_universal_hypothesis_genome.py",
    "--generator-hash",
    String(provenance.generator_hash),
    "--output",
    temporaryReportRoot,
    "--artifact-output",
    temporaryArtifactOutput,
  ];
  const repositoryPython =
    process.platform === "win32"
      ? join(repositoryRoot, ".venv", "Scripts", "python.exe")
      : join(repositoryRoot, ".venv", "bin", "python");
  const candidates = [
    process.env.ROBIN_PYTHON,
    repositoryPython,
    process.platform === "win32" ? "python" : "python3",
    "python",
  ].filter((candidate): candidate is string => Boolean(candidate));
  const generated = candidates.some((command) => {
    const result = spawnSync(command, args, {
      cwd: repositoryRoot,
      encoding: "utf8",
      stdio: "pipe",
    });
    return result.status === 0;
  });
  if (!generated) {
    await rm(temporaryRoot, { force: true, recursive: true });
    throw new Error("HYPOTHESIS_NODE_BUILD_FAILED");
  }
  if (!(await nodeArtifactsMatchManifest(temporaryNodeRoot, manifest))) {
    await rm(temporaryRoot, { force: true, recursive: true });
    throw new Error("HYPOTHESIS_NODE_ARTIFACT_CONTRACT_MISMATCH");
  }
  return { root: temporaryNodeRoot, temporaryRoot };
}
const snapshot = JSON.parse(await readFile(inputUrl, "utf8")) as unknown;
const presentation = buildPresentationModel(snapshot);
const snapshotRecord = snapshot as Record<string, unknown>;
const deepData = snapshotRecord.deepData as Record<string, unknown>;
const publicPresentation = {
  dashboard: presentation.dashboard,
  matches: presentation.matches,
  leagues: presentation.leagues,
  nextCaptures: presentation.nextCaptures,
  prequentialLearning: presentation.prequentialLearning,
  hypothesisIntelligence: presentation.hypothesisIntelligence,
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
    prequentialLearning: presentation.prequentialLearning,
  }, null, 2)}\n`,
  "utf8",
);

const hypothesisNodeArtifacts = await ensureHypothesisNodeArtifacts();

const hypothesisContractEntries = await Promise.all(
  hypothesisContractNames.map(async (name) => {
    const contract = await readJson(
      new URL(`${name}.json`, hypothesisContractRoot),
    );
    return [name, contract] as const;
  }),
);
const hypothesisContracts = Object.fromEntries(
  hypothesisContractEntries,
) as Record<(typeof hypothesisContractNames)[number], JsonRecord>;
await writeFile(
  hypothesisGlossaryOutputUrl,
  `${JSON.stringify(
    hypothesisContracts["hypothesis-glossary-fr"],
    null,
    2,
  )}\n`,
  "utf8",
);
const treeIndex = hypothesisContracts[
  "hypothesis-tree-root-index"
] as JsonRecord & {
  page_manifest?: Array<{
    artifact_path?: string;
    bytes?: number;
    page?: number;
    records?: number;
    sha256?: string;
  }>;
  page_size?: number;
  roots?: unknown[];
};

await mkdir(hypothesisNodePublicRoot, { recursive: true });
const generatedNodePages: Array<{
  bytes: number;
  page: number;
  records: number;
  sha256: string | null;
  sourceSha256: string | null;
  source: "artifact" | "root-index-fallback";
  url: string;
}> = [];
const nodeLocator: Record<string, number> = {};
const childrenByParent: Record<string, string[]> = {};
const familyNodeStats: Record<
  string,
  {
    blocked: number;
    deferred: number;
    executed: number;
    longTail: number;
    materialized: number;
    pruned: number;
  }
> = {};
const familyCatalog = hypothesisContracts[
  "hypothesis-family-catalog"
] as JsonRecord & {
  items?: Array<{ family?: unknown }>;
};
for (const family of familyCatalog.items ?? []) {
  if (typeof family.family !== "string") continue;
  familyNodeStats[family.family] = {
    blocked: 0,
    deferred: 0,
    executed: 0,
    longTail: 0,
    materialized: 0,
    pruned: 0,
  };
}

for (const [index, manifestEntry] of (treeIndex.page_manifest ?? []).entries()) {
  const page = manifestEntry.page ?? index + 1;
  const fileName = `page-${String(page).padStart(3, "0")}.json`;
  let nodePage: JsonRecord;
  let source: "artifact" | "root-index-fallback" = "artifact";

  try {
    nodePage = await readJson(new URL(fileName, hypothesisNodeArtifacts.root));
  } catch {
    source = "root-index-fallback";
    nodePage = {
      items: index === 0 ? (treeIndex.roots ?? []) : [],
      page,
      page_size: treeIndex.page_size ?? 50,
      schema_version: "hypothesis-tree-node-page-fallback-v1",
      total: (treeIndex.roots ?? []).length,
    };
  }

  const serializedPage = `${JSON.stringify(nodePage)}\n`;
  const servedSha256 = createHash("sha256")
    .update(serializedPage)
    .digest("hex");
  await writeFile(
    new URL(fileName, hypothesisNodePublicRoot),
    serializedPage,
    "utf8",
  );
  if (Array.isArray(nodePage.items)) {
    for (const item of nodePage.items) {
      if (!item || typeof item !== "object") continue;
      const node = item as {
        family?: unknown;
        materialization_disposition?: unknown;
        node_id?: unknown;
        parent_id?: unknown;
        parent_ids?: unknown;
      };
      if (typeof node.node_id !== "string") continue;
      nodeLocator[node.node_id] = page;
      if (typeof node.family === "string") {
        const stats = familyNodeStats[node.family] ?? {
          blocked: 0,
          deferred: 0,
          executed: 0,
          longTail: 0,
          materialized: 0,
          pruned: 0,
        };
        stats.materialized += 1;
        switch (node.materialization_disposition) {
          case "DATA_GATE_BLOCKED":
            stats.blocked += 1;
            break;
          case "COMPUTE_DEFERRED":
            stats.deferred += 1;
            break;
          case "EXECUTED":
            stats.executed += 1;
            break;
          case "LONG_TAIL_WATCHLIST":
            stats.longTail += 1;
            break;
          case "PRUNED":
            stats.pruned += 1;
            break;
        }
        familyNodeStats[node.family] = stats;
      }
      const parentIds = Array.isArray(node.parent_ids)
        ? node.parent_ids.filter(
            (parentId): parentId is string => typeof parentId === "string",
          )
        : typeof node.parent_id === "string"
          ? [node.parent_id]
          : [];
      for (const parentId of parentIds) {
        const children = childrenByParent[parentId] ?? [];
        if (!children.includes(node.node_id)) children.push(node.node_id);
        childrenByParent[parentId] = children;
      }
    }
  }
  generatedNodePages.push({
    bytes: Buffer.byteLength(serializedPage),
    page,
    records: Array.isArray(nodePage.items) ? nodePage.items.length : 0,
    sha256: servedSha256,
    source,
    sourceSha256: manifestEntry.sha256 ?? null,
    url: `/data/hypotheses/nodes/${fileName}`,
  });
}

await writeFile(
  hypothesisOutputUrl,
  `${JSON.stringify(
    {
      contracts: hypothesisContracts,
      derivedTreeIndex: {
        childrenByParent,
        familyNodeStats,
        nodeLocator,
      },
      generatedNodePages,
      presentation: {
        hypothesisIntelligence: presentation.hypothesisIntelligence,
        sourceContracts: hypothesisContractNames,
      },
      schemaVersion: "hypothesis-universe-presentation-v1",
    },
    null,
    2,
  )}\n`,
  "utf8",
);

if (hypothesisNodeArtifacts.temporaryRoot) {
  await rm(hypothesisNodeArtifacts.temporaryRoot, {
    force: true,
    recursive: true,
  });
}
