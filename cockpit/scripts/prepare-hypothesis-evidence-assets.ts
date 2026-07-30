import { createHash, randomUUID } from "node:crypto";
import {
  access,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
  sep,
} from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const DEFAULT_SOURCE = fileURLToPath(
  new URL(
    "../../artifacts/hypothesis-evidence-site-pages/",
    import.meta.url,
  ),
);
const DEFAULT_TARGET = fileURLToPath(
  new URL("../public/data/hypothesis-evidence/", import.meta.url),
);
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const HYPOTHESIS_ID = "[A-Za-z0-9][A-Za-z0-9._-]{0,127}";
const HYPOTHESIS_ID_PATTERN = new RegExp(`^${HYPOTHESIS_ID}$`);
const PAGE_SIZES = [25, 50] as const;
const ALLOWED_PATHS = [
  /^index\.json$/,
  /^matches\/index\.json$/,
  /^matches\/[0-9a-f]{64}\.json$/,
  new RegExp(`^hypotheses/${HYPOTHESIS_ID}/analysis\\.json$`),
  new RegExp(`^hypotheses/${HYPOTHESIS_ID}/query-index\\.json$`),
  new RegExp(`^hypotheses/${HYPOTHESIS_ID}/summary\\.json$`),
  new RegExp(
    `^hypotheses/${HYPOTHESIS_ID}/memberships/(25|50)/page-[0-9]{4}\\.json$`,
  ),
];

type ManifestEntry = Readonly<{
  bytes: number;
  path: string;
  record_kind: string;
  row_count: number;
  sha256: string;
}>;

type SiteManifest = Readonly<{
  content_tree_sha256: string;
  outputs: readonly ManifestEntry[];
  publication_scope: "TEMPORARY_PREVIEW_NOT_FOR_GIT";
  schema_version: "hypothesis-evidence-site-manifest-v1";
}>;

export type EvidenceAssetPublishOptions = Readonly<{
  required?: boolean;
  sourceRoot?: string;
  targetRoot?: string;
}>;

export type EvidenceAssetPublishResult = Readonly<{
  available: boolean;
  bytes: number;
  contentTreeSha256: string | null;
  files: number;
  sourceRoot: string;
  targetRoot: string;
}>;

export class EvidenceAssetPublishError extends Error {
  readonly code: string;

  constructor(code: string, options?: ErrorOptions) {
    super(code, options);
    this.name = "EvidenceAssetPublishError";
    this.code = code;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as NodeJS.ErrnoException).code === "ENOENT"
  );
}

async function exists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch (error) {
    if (isMissing(error)) return false;
    throw error;
  }
}

function containsPath(parent: string, child: string): boolean {
  const pathFromParent = relative(parent, child);
  return (
    pathFromParent === "" ||
    (!pathFromParent.startsWith(`..${sep}`) &&
      pathFromParent !== ".." &&
      !isAbsolute(pathFromParent))
  );
}

function normalizeManifestPath(value: unknown): string {
  if (typeof value !== "string" || !value || value.includes("\\")) {
    throw new EvidenceAssetPublishError("EVIDENCE_MANIFEST_PATH_INVALID");
  }
  if (
    value.startsWith("/") ||
    value.split("/").some((part) => part === "" || part === "..") ||
    !ALLOWED_PATHS.some((pattern) => pattern.test(value))
  ) {
    throw new EvidenceAssetPublishError("EVIDENCE_MANIFEST_PATH_FORBIDDEN");
  }
  return value;
}

function expectedRecordKind(path: string): string {
  if (path === "index.json") return "HYPOTHESIS_INDEX";
  if (path === "matches/index.json") return "HISTORICAL_MATCH_INDEX";
  if (/^matches\/[0-9a-f]{64}\.json$/.test(path)) {
    return "UNIQUE_HISTORICAL_MATCH_DETAIL";
  }
  if (path.endsWith("/analysis.json")) {
    return "HYPOTHESIS_HISTORICAL_ANALYSIS";
  }
  if (path.endsWith("/query-index.json")) {
    return "HYPOTHESIS_MEMBERSHIP_QUERY_INDEX";
  }
  if (path.endsWith("/summary.json")) {
    return "HYPOTHESIS_HISTORICAL_SUMMARY";
  }
  return "HISTORICAL_MEMBERSHIP_PAGE";
}

function parseManifest(contents: Buffer): SiteManifest {
  let value: unknown;
  try {
    value = JSON.parse(contents.toString("utf8")) as unknown;
  } catch (error) {
    throw new EvidenceAssetPublishError("EVIDENCE_MANIFEST_JSON_INVALID", {
      cause: error,
    });
  }
  if (
    !isRecord(value) ||
    value.schema_version !== "hypothesis-evidence-site-manifest-v1" ||
    value.publication_scope !== "TEMPORARY_PREVIEW_NOT_FOR_GIT" ||
    typeof value.content_tree_sha256 !== "string" ||
    !SHA256_PATTERN.test(value.content_tree_sha256) ||
    !Array.isArray(value.outputs)
  ) {
    throw new EvidenceAssetPublishError("EVIDENCE_MANIFEST_CONTRACT_INVALID");
  }

  const outputs: ManifestEntry[] = [];
  const seen = new Set<string>();
  for (const candidate of value.outputs) {
    if (!isRecord(candidate)) {
      throw new EvidenceAssetPublishError("EVIDENCE_MANIFEST_ENTRY_INVALID");
    }
    const path = normalizeManifestPath(candidate.path);
    if (
      seen.has(path) ||
      !Number.isSafeInteger(candidate.bytes) ||
      Number(candidate.bytes) < 0 ||
      !Number.isSafeInteger(candidate.row_count) ||
      Number(candidate.row_count) < 0 ||
      typeof candidate.sha256 !== "string" ||
      !SHA256_PATTERN.test(candidate.sha256) ||
      candidate.record_kind !== expectedRecordKind(path)
    ) {
      throw new EvidenceAssetPublishError("EVIDENCE_MANIFEST_ENTRY_INVALID");
    }
    seen.add(path);
    outputs.push({
      bytes: Number(candidate.bytes),
      path,
      record_kind: candidate.record_kind,
      row_count: Number(candidate.row_count),
      sha256: candidate.sha256,
    });
  }
  if (outputs.length === 0) {
    throw new EvidenceAssetPublishError("EVIDENCE_MANIFEST_EMPTY");
  }
  const paths = outputs.map((entry) => entry.path);
  if (paths.join("\n") !== [...paths].sort().join("\n")) {
    throw new EvidenceAssetPublishError("EVIDENCE_MANIFEST_ORDER_INVALID");
  }
  return {
    content_tree_sha256: value.content_tree_sha256,
    outputs,
    publication_scope: value.publication_scope,
    schema_version: value.schema_version,
  };
}

function canonicalJson(value: unknown): string {
  if (
    value === null ||
    typeof value === "boolean" ||
    typeof value === "string"
  ) {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_MANIFEST_CANONICAL_JSON_INVALID",
      );
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .sort()
      .map(
        (key) =>
          `${JSON.stringify(key)}:${canonicalJson(value[key])}`,
      )
      .join(",")}}`;
  }
  throw new EvidenceAssetPublishError(
    "EVIDENCE_MANIFEST_CANONICAL_JSON_INVALID",
  );
}

function contentTreeSha256(outputs: readonly ManifestEntry[]): string {
  return createHash("sha256")
    .update(canonicalJson(outputs), "utf8")
    .digest("hex");
}

function requiredRecord(
  value: unknown,
  code = "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
): Record<string, unknown> {
  if (!isRecord(value)) throw new EvidenceAssetPublishError(code);
  return value;
}

function requiredArray(
  value: unknown,
  code = "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
): unknown[] {
  if (!Array.isArray(value)) throw new EvidenceAssetPublishError(code);
  return value;
}

function requiredString(
  value: unknown,
  code = "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new EvidenceAssetPublishError(code);
  }
  return value;
}

function requiredInteger(
  value: unknown,
  minimum = 0,
  code = "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
): number {
  if (!Number.isSafeInteger(value) || Number(value) < minimum) {
    throw new EvidenceAssetPublishError(code);
  }
  return Number(value);
}

function requireExactString(value: unknown, expected: string): string {
  const candidate = requiredString(value);
  if (candidate !== expected) {
    throw new EvidenceAssetPublishError(
      "EVIDENCE_REQUIRED_REFERENCE_INVALID",
    );
  }
  return candidate;
}

function requireRuleHash(value: unknown): string {
  const candidate = requiredString(value);
  if (!SHA256_PATTERN.test(candidate)) {
    throw new EvidenceAssetPublishError(
      "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
    );
  }
  return candidate;
}

function expectedMatchDetailRef(canonicalMatchId: string): string {
  return `matches/${createHash("sha256")
    .update(canonicalMatchId, "utf8")
    .digest("hex")}.json`;
}

function requireOutput(
  entriesByPath: ReadonlyMap<string, ManifestEntry>,
  path: string,
  recordKind: string,
): ManifestEntry {
  const entry = entriesByPath.get(path);
  if (!entry || entry.record_kind !== recordKind) {
    throw new EvidenceAssetPublishError(
      "EVIDENCE_REQUIRED_TOPOLOGY_MISSING",
    );
  }
  return entry;
}

function parseJsonObject(
  contentsByPath: ReadonlyMap<string, Buffer>,
  path: string,
): Record<string, unknown> {
  const contents = contentsByPath.get(path);
  if (!contents) {
    throw new EvidenceAssetPublishError(
      "EVIDENCE_REQUIRED_TOPOLOGY_MISSING",
    );
  }
  try {
    return requiredRecord(
      JSON.parse(contents.toString("utf8")) as unknown,
      "EVIDENCE_SOURCE_JSON_INVALID",
    );
  } catch (error) {
    if (error instanceof EvidenceAssetPublishError) throw error;
    throw new EvidenceAssetPublishError("EVIDENCE_SOURCE_JSON_INVALID", {
      cause: error,
    });
  }
}

function requireMatchReference(
  value: unknown,
  entriesByPath: ReadonlyMap<string, ManifestEntry>,
): string {
  const item = requiredRecord(value);
  const canonicalMatchId = requiredString(item.canonical_match_id);
  const expected = expectedMatchDetailRef(canonicalMatchId);
  const reference = requireExactString(item.match_detail_ref, expected);
  requireOutput(
    entriesByPath,
    reference,
    "UNIQUE_HISTORICAL_MATCH_DETAIL",
  );
  return canonicalMatchId;
}

function validateNestedMatchReferences(
  value: unknown,
  entriesByPath: ReadonlyMap<string, ManifestEntry>,
): void {
  if (Array.isArray(value)) {
    for (const item of value) {
      validateNestedMatchReferences(item, entriesByPath);
    }
    return;
  }
  if (!isRecord(value)) return;
  if (
    Object.hasOwn(value, "canonical_match_id") &&
    Object.hasOwn(value, "match_detail_ref")
  ) {
    requireMatchReference(value, entriesByPath);
  }
  for (const item of Object.values(value)) {
    validateNestedMatchReferences(item, entriesByPath);
  }
}

type ValidatedPage = Readonly<{
  canonicalMatchIds: readonly string[];
  items: readonly Record<string, unknown>[];
  page: number;
  pageSize: number;
}>;

type ValidatedHypothesis = Readonly<{
  hypothesisId: string;
  pages: ReadonlyMap<string, ValidatedPage>;
  pagesBySize: ReadonlyMap<number, readonly string[]>;
  ruleHash: string;
  summaryRef: string;
}>;

function validateRequiredTopology(
  manifest: SiteManifest,
  contentsByPath: ReadonlyMap<string, Buffer>,
): void {
  const entriesByPath = new Map(
    manifest.outputs.map((entry) => [entry.path, entry] as const),
  );
  const indexEntry = requireOutput(
    entriesByPath,
    "index.json",
    "HYPOTHESIS_INDEX",
  );
  const matchIndexEntry = requireOutput(
    entriesByPath,
    "matches/index.json",
    "HISTORICAL_MATCH_INDEX",
  );
  const index = parseJsonObject(contentsByPath, "index.json");
  requireExactString(
    index.schema_version,
    "hypothesis-evidence-site-index-v1",
  );
  requireExactString(index.match_index_ref, "matches/index.json");
  const hypothesisItems = requiredArray(index.hypotheses);
  if (hypothesisItems.length === 0 || indexEntry.row_count !== hypothesisItems.length) {
    throw new EvidenceAssetPublishError(
      "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
    );
  }

  const hypotheses = new Map<string, ValidatedHypothesis>();
  const allReferencedMatches = new Set<string>();
  const expectedHypothesesByMatch = new Map<string, Set<string>>();
  const declaredSummaryPaths = new Set(
    manifest.outputs
      .filter(
        (entry) =>
          entry.record_kind === "HYPOTHESIS_HISTORICAL_SUMMARY",
      )
      .map((entry) => entry.path),
  );
  const declaredAnalysisPaths = new Set(
    manifest.outputs
      .filter(
        (entry) =>
          entry.record_kind === "HYPOTHESIS_HISTORICAL_ANALYSIS",
      )
      .map((entry) => entry.path),
  );
  const declaredQueryPaths = new Set(
    manifest.outputs
      .filter(
        (entry) =>
          entry.record_kind === "HYPOTHESIS_MEMBERSHIP_QUERY_INDEX",
      )
      .map((entry) => entry.path),
  );
  const declaredPagePaths = new Set(
    manifest.outputs
      .filter(
        (entry) =>
          entry.record_kind === "HISTORICAL_MEMBERSHIP_PAGE",
      )
      .map((entry) => entry.path),
  );

  for (const rawHypothesis of hypothesisItems) {
    const hypothesis = requiredRecord(rawHypothesis);
    const hypothesisId = requiredString(hypothesis.hypothesis_id);
    if (
      !HYPOTHESIS_ID_PATTERN.test(hypothesisId) ||
      hypotheses.has(hypothesisId)
    ) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
      );
    }
    const ruleHash = requireRuleHash(hypothesis.rule_hash);
    const summaryRef = requireExactString(
      hypothesis.summary_ref,
      `hypotheses/${hypothesisId}/summary.json`,
    );
    const summaryEntry = requireOutput(
      entriesByPath,
      summaryRef,
      "HYPOTHESIS_HISTORICAL_SUMMARY",
    );
    if (summaryEntry.row_count !== 1) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
      );
    }
    declaredSummaryPaths.delete(summaryRef);
    const summary = parseJsonObject(contentsByPath, summaryRef);
    requireExactString(
      summary.schema_version,
      "hypothesis-evidence-site-summary-v1",
    );
    requireExactString(summary.hypothesis_id, hypothesisId);
    requireExactString(summary.rule_hash, ruleHash);

    const analysisRef = requireExactString(
      summary.analysis_ref,
      `hypotheses/${hypothesisId}/analysis.json`,
    );
    const analysisEntry = requireOutput(
      entriesByPath,
      analysisRef,
      "HYPOTHESIS_HISTORICAL_ANALYSIS",
    );
    declaredAnalysisPaths.delete(analysisRef);
    const analysis = parseJsonObject(contentsByPath, analysisRef);
    requireExactString(
      analysis.schema_version,
      "hypothesis-evidence-analysis-v1",
    );
    requireExactString(analysis.hypothesis_id, hypothesisId);
    requireExactString(analysis.rule_hash, ruleHash);
    validateNestedMatchReferences(analysis, entriesByPath);

    const queryRef = requireExactString(
      summary.query_index_ref,
      `hypotheses/${hypothesisId}/query-index.json`,
    );
    const queryEntry = requireOutput(
      entriesByPath,
      queryRef,
      "HYPOTHESIS_MEMBERSHIP_QUERY_INDEX",
    );
    declaredQueryPaths.delete(queryRef);
    const query = parseJsonObject(contentsByPath, queryRef);
    requireExactString(
      query.schema_version,
      "hypothesis-evidence-query-index-v1",
    );
    requireExactString(query.hypothesis_id, hypothesisId);
    requireExactString(query.rule_hash, ruleHash);
    requireExactString(query.summary_ref, summaryRef);
    const supportedPageSizes = requiredArray(
      query.supported_page_sizes,
    ).map((value) => requiredInteger(value, 1));
    if (
      supportedPageSizes.length !== PAGE_SIZES.length ||
      !PAGE_SIZES.every(
        (pageSize, index) => supportedPageSizes[index] === pageSize,
      )
    ) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
      );
    }
    const queryItems = requiredArray(query.items).map((item) =>
      requiredRecord(item),
    );
    const queryTotal = requiredInteger(query.total_items, 1);
    if (
      queryTotal !== queryItems.length ||
      queryEntry.row_count !== queryItems.length ||
      analysisEntry.row_count !== queryItems.length
    ) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
      );
    }
    const queryMatchIds = queryItems.map((item) =>
      requireMatchReference(item, entriesByPath),
    );
    if (new Set(queryMatchIds).size !== queryMatchIds.length) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
      );
    }

    const membershipPages = requiredRecord(summary.membership_pages);
    if (
      Object.keys(membershipPages).sort().join(",") !==
      PAGE_SIZES.map(String).sort().join(",")
    ) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
      );
    }
    const pages = new Map<string, ValidatedPage>();
    const pagesBySize = new Map<number, readonly string[]>();
    for (const pageSize of PAGE_SIZES) {
      const pageSet = requiredRecord(membershipPages[String(pageSize)]);
      if (requiredInteger(pageSet.page_size, 1) !== pageSize) {
        throw new EvidenceAssetPublishError(
          "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
        );
      }
      const totalPages = requiredInteger(pageSet.total_pages, 1);
      const pageRefs = requiredArray(pageSet.page_refs).map((value) =>
        requiredString(value),
      );
      if (pageRefs.length !== totalPages) {
        throw new EvidenceAssetPublishError(
          "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
        );
      }
      const sizeMatchIds: string[] = [];
      for (let index = 0; index < pageRefs.length; index += 1) {
        const pageNumber = index + 1;
        const pageRef = requireExactString(
          pageRefs[index],
          `hypotheses/${hypothesisId}/memberships/${pageSize}/page-${String(
            pageNumber,
          ).padStart(4, "0")}.json`,
        );
        const pageEntry = requireOutput(
          entriesByPath,
          pageRef,
          "HISTORICAL_MEMBERSHIP_PAGE",
        );
        declaredPagePaths.delete(pageRef);
        const page = parseJsonObject(contentsByPath, pageRef);
        requireExactString(
          page.schema_version,
          "hypothesis-evidence-membership-page-v1",
        );
        requireExactString(page.hypothesis_id, hypothesisId);
        requireExactString(page.rule_hash, ruleHash);
        requireExactString(page.summary_ref, summaryRef);
        if (
          requiredInteger(page.page_size, 1) !== pageSize ||
          requiredInteger(page.page, 1) !== pageNumber ||
          requiredInteger(page.total_pages, 1) !== totalPages ||
          requiredInteger(page.total_items, 1) !== queryTotal
        ) {
          throw new EvidenceAssetPublishError(
            "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
          );
        }
        const pageItems = requiredArray(page.items).map((item) =>
          requiredRecord(item),
        );
        const expectedRows = Math.min(
          pageSize,
          queryTotal - index * pageSize,
        );
        if (
          expectedRows < 1 ||
          pageItems.length !== expectedRows ||
          pageEntry.row_count !== pageItems.length
        ) {
          throw new EvidenceAssetPublishError(
            "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
          );
        }
        const canonicalMatchIds = pageItems.map((item) => {
          const canonicalMatchId = requireMatchReference(
            item,
            entriesByPath,
          );
          const reason = requiredRecord(item.reason);
          requireExactString(
            reason.condition_definitions_ref,
            summaryRef,
          );
          allReferencedMatches.add(canonicalMatchId);
          const relatedHypotheses =
            expectedHypothesesByMatch.get(canonicalMatchId) ??
            new Set<string>();
          relatedHypotheses.add(hypothesisId);
          expectedHypothesesByMatch.set(
            canonicalMatchId,
            relatedHypotheses,
          );
          return canonicalMatchId;
        });
        sizeMatchIds.push(...canonicalMatchIds);
        pages.set(pageRef, {
          canonicalMatchIds,
          items: pageItems,
          page: pageNumber,
          pageSize,
        });
      }
      if (
        sizeMatchIds.length !== queryMatchIds.length ||
        sizeMatchIds.some(
          (canonicalMatchId, index) =>
            canonicalMatchId !== queryMatchIds[index],
        )
      ) {
        throw new EvidenceAssetPublishError(
          "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
        );
      }
      pagesBySize.set(pageSize, pageRefs);
    }
    hypotheses.set(hypothesisId, {
      hypothesisId,
      pages,
      pagesBySize,
      ruleHash,
      summaryRef,
    });
  }

  if (
    declaredSummaryPaths.size > 0 ||
    declaredAnalysisPaths.size > 0 ||
    declaredQueryPaths.size > 0 ||
    declaredPagePaths.size > 0
  ) {
    throw new EvidenceAssetPublishError(
      "EVIDENCE_REQUIRED_TOPOLOGY_ORPHAN",
    );
  }

  const matchIndex = parseJsonObject(
    contentsByPath,
    "matches/index.json",
  );
  requireExactString(
    matchIndex.schema_version,
    "hypothesis-evidence-match-index-v1",
  );
  const matchItems = requiredArray(matchIndex.items);
  if (
    matchItems.length === 0 ||
    matchIndexEntry.row_count !== matchItems.length
  ) {
    throw new EvidenceAssetPublishError(
      "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
    );
  }
  const declaredDetailPaths = new Set(
    manifest.outputs
      .filter(
        (entry) =>
          entry.record_kind === "UNIQUE_HISTORICAL_MATCH_DETAIL",
      )
      .map((entry) => entry.path),
  );
  const indexedMatches = new Set<string>();
  for (const rawMatchItem of matchItems) {
    const matchItem = requiredRecord(rawMatchItem);
    const canonicalMatchId = requiredString(
      matchItem.canonical_match_id,
    );
    if (indexedMatches.has(canonicalMatchId)) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
      );
    }
    indexedMatches.add(canonicalMatchId);
    const detailRef = requireExactString(
      matchItem.detail_ref,
      expectedMatchDetailRef(canonicalMatchId),
    );
    const detailEntry = requireOutput(
      entriesByPath,
      detailRef,
      "UNIQUE_HISTORICAL_MATCH_DETAIL",
    );
    if (detailEntry.row_count !== 1) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
      );
    }
    declaredDetailPaths.delete(detailRef);
    const detail = parseJsonObject(contentsByPath, detailRef);
    requireExactString(
      detail.schema_version,
      "hypothesis-evidence-historical-match-v1",
    );
    requireExactString(detail.canonical_match_id, canonicalMatchId);
    const associations = requiredArray(
      detail.top_ten_hypotheses,
    ).map((item) => requiredRecord(item));
    const expectedHypotheses =
      expectedHypothesesByMatch.get(canonicalMatchId);
    if (
      !expectedHypotheses ||
      associations.length !== expectedHypotheses.size ||
      requiredInteger(matchItem.published_hypothesis_count, 1) !==
        associations.length ||
      requiredInteger(matchItem.hypothesis_count, associations.length) <
        associations.length
    ) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
      );
    }
    const actualHypotheses = new Set<string>();
    for (const association of associations) {
      const hypothesisId = requiredString(association.hypothesis_id);
      const hypothesis = hypotheses.get(hypothesisId);
      if (
        !hypothesis ||
        !expectedHypotheses.has(hypothesisId) ||
        actualHypotheses.has(hypothesisId)
      ) {
        throw new EvidenceAssetPublishError(
          "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
        );
      }
      actualHypotheses.add(hypothesisId);
      requireExactString(association.rule_hash, hypothesis.ruleHash);
      requireExactString(
        association.summary_ref,
        hypothesis.summaryRef,
      );
      const reason = requiredRecord(association.reason);
      requireExactString(
        reason.condition_definitions_ref,
        hypothesis.summaryRef,
      );
      const pageLinks = requiredArray(
        association.membership_page_refs,
      ).map((item) => requiredRecord(item));
      if (pageLinks.length !== PAGE_SIZES.length) {
        throw new EvidenceAssetPublishError(
          "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
        );
      }
      const linkedSizes = new Set<number>();
      for (const pageLink of pageLinks) {
        const pageSize = requiredInteger(pageLink.page_size, 1);
        const page = requiredInteger(pageLink.page, 1);
        const itemIndex = requiredInteger(pageLink.item_index);
        if (
          !PAGE_SIZES.includes(pageSize as (typeof PAGE_SIZES)[number]) ||
          linkedSizes.has(pageSize)
        ) {
          throw new EvidenceAssetPublishError(
            "EVIDENCE_REQUIRED_TOPOLOGY_INVALID",
          );
        }
        linkedSizes.add(pageSize);
        const path = requireExactString(
          pageLink.path,
          `hypotheses/${hypothesisId}/memberships/${pageSize}/page-${String(
            page,
          ).padStart(4, "0")}.json`,
        );
        if (!hypothesis.pagesBySize.get(pageSize)?.includes(path)) {
          throw new EvidenceAssetPublishError(
            "EVIDENCE_REQUIRED_REFERENCE_INVALID",
          );
        }
        const targetPage = hypothesis.pages.get(path);
        if (
          !targetPage ||
          targetPage.page !== page ||
          targetPage.pageSize !== pageSize ||
          targetPage.canonicalMatchIds[itemIndex] !== canonicalMatchId
        ) {
          throw new EvidenceAssetPublishError(
            "EVIDENCE_REQUIRED_REFERENCE_INVALID",
          );
        }
      }
    }
  }

  if (
    declaredDetailPaths.size > 0 ||
    indexedMatches.size !== allReferencedMatches.size ||
    [...allReferencedMatches].some(
      (canonicalMatchId) => !indexedMatches.has(canonicalMatchId),
    )
  ) {
    throw new EvidenceAssetPublishError(
      "EVIDENCE_REQUIRED_TOPOLOGY_ORPHAN",
    );
  }
}

async function listFiles(root: string, prefix = ""): Promise<string[]> {
  const output: string[] = [];
  for (const entry of await readdir(join(root, prefix), {
    withFileTypes: true,
  })) {
    const relativePath = prefix
      ? `${prefix}/${entry.name}`
      : entry.name;
    if (entry.isSymbolicLink()) {
      throw new EvidenceAssetPublishError("EVIDENCE_SOURCE_SYMLINK_FORBIDDEN");
    }
    if (entry.isDirectory()) {
      output.push(...(await listFiles(root, relativePath)));
    } else if (entry.isFile()) {
      output.push(relativePath);
    } else {
      throw new EvidenceAssetPublishError("EVIDENCE_SOURCE_ENTRY_INVALID");
    }
  }
  return output.sort();
}

async function assertSafeRoots(
  sourceRoot: string,
  targetRoot: string,
): Promise<void> {
  if (
    containsPath(sourceRoot, targetRoot) ||
    containsPath(targetRoot, sourceRoot) ||
    targetRoot.split(sep).includes(".git")
  ) {
    throw new EvidenceAssetPublishError("EVIDENCE_PUBLISH_ROOTS_UNSAFE");
  }
  if (await exists(targetRoot)) {
    const target = await lstat(targetRoot);
    if (target.isSymbolicLink() || !target.isDirectory()) {
      throw new EvidenceAssetPublishError("EVIDENCE_TARGET_INVALID");
    }
  }
}

async function atomicPublish(
  stagingRoot: string,
  targetRoot: string,
): Promise<void> {
  const backupRoot = `${targetRoot}.backup-${randomUUID()}`;
  const targetExists = await exists(targetRoot);
  if (targetExists) await rename(targetRoot, backupRoot);
  try {
    await rename(stagingRoot, targetRoot);
  } catch (error) {
    if (targetExists && !(await exists(targetRoot))) {
      await rename(backupRoot, targetRoot);
    }
    throw new EvidenceAssetPublishError("EVIDENCE_ATOMIC_PUBLISH_FAILED", {
      cause: error,
    });
  }
  if (targetExists) {
    await rm(backupRoot, { force: true, recursive: true });
  }
}

export async function publishHypothesisEvidenceAssets(
  options: EvidenceAssetPublishOptions = {},
): Promise<EvidenceAssetPublishResult> {
  const sourceRoot = resolve(options.sourceRoot ?? DEFAULT_SOURCE);
  const targetRoot = resolve(options.targetRoot ?? DEFAULT_TARGET);
  const required = options.required ?? true;
  await assertSafeRoots(sourceRoot, targetRoot);

  if (!(await exists(sourceRoot))) {
    if (required || (await exists(targetRoot))) {
      throw new EvidenceAssetPublishError("EVIDENCE_SOURCE_MISSING");
    }
    return {
      available: false,
      bytes: 0,
      contentTreeSha256: null,
      files: 0,
      sourceRoot,
      targetRoot,
    };
  }
  const sourceStat = await lstat(sourceRoot);
  if (sourceStat.isSymbolicLink() || !sourceStat.isDirectory()) {
    throw new EvidenceAssetPublishError("EVIDENCE_SOURCE_INVALID");
  }

  const manifestPath = join(sourceRoot, "manifest.json");
  let manifestContents: Buffer;
  try {
    manifestContents = await readFile(manifestPath);
  } catch (error) {
    throw new EvidenceAssetPublishError("EVIDENCE_MANIFEST_MISSING", {
      cause: error,
    });
  }
  const manifest = parseManifest(manifestContents);
  if (contentTreeSha256(manifest.outputs) !== manifest.content_tree_sha256) {
    throw new EvidenceAssetPublishError(
      "EVIDENCE_CONTENT_TREE_HASH_MISMATCH",
    );
  }
  const expectedFiles = [
    "manifest.json",
    ...manifest.outputs.map((entry) => entry.path),
  ].sort();
  const actualFiles = await listFiles(sourceRoot);
  if (actualFiles.join("\n") !== expectedFiles.join("\n")) {
    throw new EvidenceAssetPublishError("EVIDENCE_SOURCE_FILE_SET_MISMATCH");
  }

  const contentsByPath = new Map<string, Buffer>();
  for (const entry of manifest.outputs) {
    const source = join(sourceRoot, ...entry.path.split("/"));
    const sourceStat = await lstat(source);
    if (sourceStat.isSymbolicLink()) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_SOURCE_SYMLINK_FORBIDDEN",
      );
    }
    if (!sourceStat.isFile()) {
      throw new EvidenceAssetPublishError("EVIDENCE_SOURCE_ENTRY_INVALID");
    }
    const contents = await readFile(source);
    const digest = createHash("sha256").update(contents).digest("hex");
    if (contents.byteLength !== entry.bytes || digest !== entry.sha256) {
      throw new EvidenceAssetPublishError(
        "EVIDENCE_SOURCE_ARTIFACT_HASH_MISMATCH",
      );
    }
    contentsByPath.set(entry.path, contents);
  }
  if (required) validateRequiredTopology(manifest, contentsByPath);

  const targetParent = dirname(targetRoot);
  await mkdir(targetParent, { recursive: true });
  const stagingRoot = await mkdtemp(
    join(targetParent, `.${basename(targetRoot)}.staging-`),
  );
  let totalBytes = 0;
  try {
    for (const entry of manifest.outputs) {
      const destination = join(stagingRoot, ...entry.path.split("/"));
      const contents = contentsByPath.get(entry.path);
      if (!contents) {
        throw new EvidenceAssetPublishError(
          "EVIDENCE_SOURCE_FILE_SET_MISMATCH",
        );
      }
      await mkdir(dirname(destination), { recursive: true });
      await writeFile(destination, contents);
      totalBytes += contents.byteLength;
    }
    await writeFile(join(stagingRoot, "manifest.json"), manifestContents);
    totalBytes += manifestContents.byteLength;
    await atomicPublish(stagingRoot, targetRoot);
  } catch (error) {
    await rm(stagingRoot, { force: true, recursive: true });
    throw error;
  }

  return {
    available: true,
    bytes: totalBytes,
    contentTreeSha256: manifest.content_tree_sha256,
    files: manifest.outputs.length + 1,
    sourceRoot,
    targetRoot,
  };
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      optional: { default: false, type: "boolean" },
      required: { default: false, type: "boolean" },
      source: { type: "string" },
      target: { type: "string" },
    },
    strict: true,
  });
  if (values.optional && values.required) {
    throw new EvidenceAssetPublishError(
      "EVIDENCE_REQUIRED_OPTIONAL_CONFLICT",
    );
  }
  const result = await publishHypothesisEvidenceAssets({
    required: values.required || !values.optional,
    sourceRoot: values.source,
    targetRoot: values.target,
  });
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : null;
if (invokedPath === fileURLToPath(import.meta.url)) {
  await main();
}
