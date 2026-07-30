import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";

import {
  EvidenceAssetPublishError,
  publishHypothesisEvidenceAssets,
} from "../scripts/prepare-hypothesis-evidence-assets";

type SyntheticEntry = {
  bytes: number;
  path: string;
  record_kind: string;
  row_count: number;
  sha256: string;
};

type SyntheticManifest = {
  content_tree_sha256: string;
  outputs: SyntheticEntry[];
  publication_scope: "TEMPORARY_PREVIEW_NOT_FOR_GIT";
  schema_version: "hypothesis-evidence-site-manifest-v1";
};

function canonicalJson(value: unknown): string {
  if (
    value === null ||
    typeof value === "boolean" ||
    typeof value === "number" ||
    typeof value === "string"
  ) {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map(
        (key) =>
          `${JSON.stringify(key)}:${canonicalJson(record[key])}`,
      )
      .join(",")}}`;
  }
  throw new TypeError("synthetic canonical JSON value invalid");
}

function treeHash(entries: readonly SyntheticEntry[]): string {
  return createHash("sha256")
    .update(canonicalJson(entries), "utf8")
    .digest("hex");
}

async function writeManifest(
  sourceRoot: string,
  entries: SyntheticEntry[],
  contentTreeSha256 = treeHash(entries),
): Promise<void> {
  const manifest: SyntheticManifest = {
    content_tree_sha256: contentTreeSha256,
    outputs: entries,
    publication_scope: "TEMPORARY_PREVIEW_NOT_FOR_GIT",
    schema_version: "hypothesis-evidence-site-manifest-v1",
  };
  await writeFile(
    join(sourceRoot, "manifest.json"),
    `${JSON.stringify(manifest)}\n`,
    "utf8",
  );
}

async function readManifest(sourceRoot: string): Promise<SyntheticManifest> {
  return JSON.parse(
    await readFile(join(sourceRoot, "manifest.json"), "utf8"),
  ) as SyntheticManifest;
}

async function rewriteJsonArtifact(
  sourceRoot: string,
  path: string,
  mutate: (value: Record<string, unknown>) => void,
): Promise<void> {
  const artifactPath = join(sourceRoot, ...path.split("/"));
  const value = JSON.parse(
    await readFile(artifactPath, "utf8"),
  ) as Record<string, unknown>;
  mutate(value);
  const contents = Buffer.from(`${JSON.stringify(value)}\n`, "utf8");
  await writeFile(artifactPath, contents);
  const manifest = await readManifest(sourceRoot);
  const entry = manifest.outputs.find((candidate) => candidate.path === path);
  assert.ok(entry);
  entry.bytes = contents.byteLength;
  entry.sha256 = createHash("sha256").update(contents).digest("hex");
  await writeManifest(sourceRoot, manifest.outputs);
}

async function writeSyntheticSource(
  sourceRoot: string,
): Promise<SyntheticEntry[]> {
  const hypothesisId = "J10-M001";
  const ruleHash = "a".repeat(64);
  const canonicalMatchId = "api-football:1";
  const matchHash = createHash("sha256")
    .update(canonicalMatchId, "utf8")
    .digest("hex");
  const summaryRef = `hypotheses/${hypothesisId}/summary.json`;
  const analysisRef = `hypotheses/${hypothesisId}/analysis.json`;
  const queryRef = `hypotheses/${hypothesisId}/query-index.json`;
  const page25Ref =
    `hypotheses/${hypothesisId}/memberships/25/page-0001.json`;
  const page50Ref =
    `hypotheses/${hypothesisId}/memberships/50/page-0001.json`;
  const matchRef = `matches/${matchHash}.json`;
  const membershipItem = {
    canonical_match_id: canonicalMatchId,
    match_detail_ref: matchRef,
    reason: { condition_definitions_ref: summaryRef },
  };
  const files = new Map<string, [string, string, number]>([
    [
      "index.json",
      [
        JSON.stringify({
          hypotheses: [
            {
              hypothesis_id: hypothesisId,
              rule_hash: ruleHash,
              summary_ref: summaryRef,
            },
          ],
          match_index_ref: "matches/index.json",
          schema_version: "hypothesis-evidence-site-index-v1",
        }),
        "HYPOTHESIS_INDEX",
        1,
      ],
    ],
    [
      "matches/index.json",
      [
        JSON.stringify({
          items: [
            {
              canonical_match_id: canonicalMatchId,
              detail_ref: matchRef,
              hypothesis_count: 1,
              published_hypothesis_count: 1,
            },
          ],
          schema_version: "hypothesis-evidence-match-index-v1",
        }),
        "HISTORICAL_MATCH_INDEX",
        1,
      ],
    ],
    [
      analysisRef,
      [
        JSON.stringify({
          bankroll_points: [
            {
              canonical_match_id: canonicalMatchId,
              match_detail_ref: matchRef,
            },
          ],
          hypothesis_id: hypothesisId,
          rule_hash: ruleHash,
          schema_version: "hypothesis-evidence-analysis-v1",
        }),
        "HYPOTHESIS_HISTORICAL_ANALYSIS",
        1,
      ],
    ],
    [
      queryRef,
      [
        JSON.stringify({
          hypothesis_id: hypothesisId,
          items: [
            {
              canonical_match_id: canonicalMatchId,
              match_detail_ref: matchRef,
            },
          ],
          rule_hash: ruleHash,
          schema_version: "hypothesis-evidence-query-index-v1",
          summary_ref: summaryRef,
          supported_page_sizes: [25, 50],
          total_items: 1,
        }),
        "HYPOTHESIS_MEMBERSHIP_QUERY_INDEX",
        1,
      ],
    ],
    [
      summaryRef,
      [
        JSON.stringify({
          analysis_ref: analysisRef,
          hypothesis_id: hypothesisId,
          membership_pages: {
            "25": {
              page_refs: [page25Ref],
              page_size: 25,
              total_pages: 1,
            },
            "50": {
              page_refs: [page50Ref],
              page_size: 50,
              total_pages: 1,
            },
          },
          query_index_ref: queryRef,
          rule_hash: ruleHash,
          schema_version: "hypothesis-evidence-site-summary-v1",
        }),
        "HYPOTHESIS_HISTORICAL_SUMMARY",
        1,
      ],
    ],
    [
      page25Ref,
      [
        JSON.stringify({
          hypothesis_id: hypothesisId,
          items: [membershipItem],
          page: 1,
          page_size: 25,
          rule_hash: ruleHash,
          schema_version: "hypothesis-evidence-membership-page-v1",
          summary_ref: summaryRef,
          total_items: 1,
          total_pages: 1,
        }),
        "HISTORICAL_MEMBERSHIP_PAGE",
        1,
      ],
    ],
    [
      page50Ref,
      [
        JSON.stringify({
          hypothesis_id: hypothesisId,
          items: [membershipItem],
          page: 1,
          page_size: 50,
          rule_hash: ruleHash,
          schema_version: "hypothesis-evidence-membership-page-v1",
          summary_ref: summaryRef,
          total_items: 1,
          total_pages: 1,
        }),
        "HISTORICAL_MEMBERSHIP_PAGE",
        1,
      ],
    ],
    [
      matchRef,
      [
        JSON.stringify({
          canonical_match_id: canonicalMatchId,
          schema_version: "hypothesis-evidence-historical-match-v1",
          top_ten_hypotheses: [
            {
              hypothesis_id: hypothesisId,
              membership_page_refs: [
                {
                  item_index: 0,
                  page: 1,
                  page_size: 25,
                  path: page25Ref,
                },
                {
                  item_index: 0,
                  page: 1,
                  page_size: 50,
                  path: page50Ref,
                },
              ],
              reason: { condition_definitions_ref: summaryRef },
              rule_hash: ruleHash,
              summary_ref: summaryRef,
            },
          ],
        }),
        "UNIQUE_HISTORICAL_MATCH_DETAIL",
        1,
      ],
    ],
  ]);
  const entries: SyntheticEntry[] = [];
  for (const [path, [contents, recordKind, rowCount]] of files) {
    const encoded = Buffer.from(`${contents}\n`, "utf8");
    const destination = join(sourceRoot, ...path.split("/"));
    await mkdir(dirname(destination), { recursive: true });
    await writeFile(destination, encoded);
    entries.push({
      bytes: encoded.byteLength,
      path,
      record_kind: recordKind,
      row_count: rowCount,
      sha256: createHash("sha256").update(encoded).digest("hex"),
    });
  }
  entries.sort((left, right) =>
    left.path < right.path ? -1 : left.path > right.path ? 1 : 0,
  );
  await writeManifest(sourceRoot, entries);
  return entries;
}

test("la publication vérifie puis remplace atomiquement le répertoire public", async (t) => {
  const temporaryRoot = await mkdtemp(
    join(tmpdir(), "robin-evidence-publisher-"),
  );
  t.after(async () => rm(temporaryRoot, { force: true, recursive: true }));
  const sourceRoot = join(temporaryRoot, "source");
  const targetRoot = join(temporaryRoot, "public", "evidence");
  const entries = await writeSyntheticSource(sourceRoot);
  await mkdir(targetRoot, { recursive: true });
  await writeFile(join(targetRoot, "stale.json"), "stale", "utf8");

  const result = await publishHypothesisEvidenceAssets({
    required: true,
    sourceRoot,
    targetRoot,
  });

  assert.equal(result.available, true);
  assert.equal(result.files, entries.length + 1);
  assert.equal(result.contentTreeSha256, treeHash(entries));
  await assert.rejects(readFile(join(targetRoot, "stale.json")));
  for (const entry of entries) {
    const published = await readFile(
      join(targetRoot, ...entry.path.split("/")),
    );
    assert.equal(
      createHash("sha256").update(published).digest("hex"),
      entry.sha256,
    );
  }
});

test("un hash invalide laisse intacte la publication précédente", async (t) => {
  const temporaryRoot = await mkdtemp(
    join(tmpdir(), "robin-evidence-publisher-"),
  );
  t.after(async () => rm(temporaryRoot, { force: true, recursive: true }));
  const sourceRoot = join(temporaryRoot, "source");
  const targetRoot = join(temporaryRoot, "public", "evidence");
  const entries = await writeSyntheticSource(sourceRoot);
  const manifest = await readManifest(sourceRoot);
  manifest.outputs[0].sha256 = "f".repeat(64);
  await writeManifest(sourceRoot, manifest.outputs);
  await mkdir(targetRoot, { recursive: true });
  await writeFile(join(targetRoot, "keep.txt"), "keep", "utf8");

  await assert.rejects(
    publishHypothesisEvidenceAssets({
      required: true,
      sourceRoot,
      targetRoot,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetPublishError &&
      error.code === "EVIDENCE_SOURCE_ARTIFACT_HASH_MISMATCH",
  );

  assert.equal(await readFile(join(targetRoot, "keep.txt"), "utf8"), "keep");
  assert.equal(entries.length, 8);
});

test("un hash d'arbre mensonger est refuse avant toute publication", async (t) => {
  const temporaryRoot = await mkdtemp(
    join(tmpdir(), "robin-evidence-publisher-"),
  );
  t.after(async () => rm(temporaryRoot, { force: true, recursive: true }));
  const sourceRoot = join(temporaryRoot, "source");
  const targetRoot = join(temporaryRoot, "public", "evidence");
  const entries = await writeSyntheticSource(sourceRoot);
  await writeManifest(sourceRoot, entries, "f".repeat(64));
  await mkdir(targetRoot, { recursive: true });
  await writeFile(join(targetRoot, "keep.txt"), "keep", "utf8");

  await assert.rejects(
    publishHypothesisEvidenceAssets({
      required: true,
      sourceRoot,
      targetRoot,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetPublishError &&
      error.code === "EVIDENCE_CONTENT_TREE_HASH_MISMATCH",
  );
  assert.equal(await readFile(join(targetRoot, "keep.txt"), "utf8"), "keep");
});

test("le mode requis refuse une topologie sans index des matchs", async (t) => {
  const temporaryRoot = await mkdtemp(
    join(tmpdir(), "robin-evidence-publisher-"),
  );
  t.after(async () => rm(temporaryRoot, { force: true, recursive: true }));
  const sourceRoot = join(temporaryRoot, "source");
  const targetRoot = join(temporaryRoot, "public", "evidence");
  await writeSyntheticSource(sourceRoot);
  const manifest = await readManifest(sourceRoot);
  manifest.outputs = manifest.outputs.filter(
    (entry) => entry.path !== "matches/index.json",
  );
  await rm(join(sourceRoot, "matches", "index.json"));
  await writeManifest(sourceRoot, manifest.outputs);

  await assert.rejects(
    publishHypothesisEvidenceAssets({
      required: true,
      sourceRoot,
      targetRoot,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetPublishError &&
      error.code === "EVIDENCE_REQUIRED_TOPOLOGY_MISSING",
  );
});

test("le mode requis refuse une reference incoherente ou traversante", async (t) => {
  const temporaryRoot = await mkdtemp(
    join(tmpdir(), "robin-evidence-publisher-"),
  );
  t.after(async () => rm(temporaryRoot, { force: true, recursive: true }));
  const sourceRoot = join(temporaryRoot, "source");
  const targetRoot = join(temporaryRoot, "public", "evidence");
  await writeSyntheticSource(sourceRoot);
  await rewriteJsonArtifact(
    sourceRoot,
    "hypotheses/J10-M001/summary.json",
    (summary) => {
      summary.analysis_ref = "../analysis.json";
    },
  );

  await assert.rejects(
    publishHypothesisEvidenceAssets({
      required: true,
      sourceRoot,
      targetRoot,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetPublishError &&
      error.code === "EVIDENCE_REQUIRED_REFERENCE_INVALID",
  );
});

test("le mode optionnel accepte seulement l'absence simultanée source/cible", async (t) => {
  const temporaryRoot = await mkdtemp(
    join(tmpdir(), "robin-evidence-publisher-"),
  );
  t.after(async () => rm(temporaryRoot, { force: true, recursive: true }));
  const sourceRoot = join(temporaryRoot, "missing");
  const targetRoot = join(temporaryRoot, "public", "evidence");

  const result = await publishHypothesisEvidenceAssets({
    required: false,
    sourceRoot,
    targetRoot,
  });

  assert.deepEqual(
    {
      available: result.available,
      bytes: result.bytes,
      files: result.files,
    },
    { available: false, bytes: 0, files: 0 },
  );
  await mkdir(targetRoot, { recursive: true });
  await assert.rejects(
    publishHypothesisEvidenceAssets({
      required: false,
      sourceRoot,
      targetRoot,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetPublishError &&
      error.code === "EVIDENCE_SOURCE_MISSING",
  );
});

test("le manifeste ne peut publier aucun chemin hors du namespace borné", async (t) => {
  const temporaryRoot = await mkdtemp(
    join(tmpdir(), "robin-evidence-publisher-"),
  );
  t.after(async () => rm(temporaryRoot, { force: true, recursive: true }));
  const sourceRoot = join(temporaryRoot, "source");
  const targetRoot = join(temporaryRoot, "public", "evidence");
  await writeSyntheticSource(sourceRoot);
  const manifestPath = join(sourceRoot, "manifest.json");
  const manifest = await readManifest(sourceRoot);
  manifest.outputs[0].path = "../secret.json";
  await writeFile(manifestPath, `${JSON.stringify(manifest)}\n`, "utf8");

  await assert.rejects(
    publishHypothesisEvidenceAssets({
      required: true,
      sourceRoot,
      targetRoot,
    }),
    (error: unknown) =>
      error instanceof EvidenceAssetPublishError &&
      error.code === "EVIDENCE_MANIFEST_PATH_FORBIDDEN",
  );
});
