export type QualificationMetrics = {
  requests: number | null; nativeRecords: number | null; footballRecords: number | null;
  candidates: number | null; admitted: number | null;
};
export type QualificationResult = {
  id: string; label: string; checkedAt: string; dateKind: "observation" | "documentary_record" | "technical_close";
  outcome: "no_eligible" | "technical_failure" | "missing_evidence";
  summary: string; scope: string; nextStep: string; metrics: QualificationMetrics; claims: string[];
};
export type QualificationSnapshot = {
  schemaVersion: "robin-source-qualification-v1"; capturedAt: string; coverage: "partial";
  results: QualificationResult[];
};

function object(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).length !== keys.length || keys.some((key) => !Object.hasOwn(value, key))) {
    throw new Error("Invalid qualification fields");
  }
  return value as Record<string, unknown>;
}
function text(value: unknown, maximum = 500): string {
  if (typeof value !== "string" || !value.trim() || value.length > maximum || /[\u0000-\u001f]/.test(value)) {
    throw new Error("Invalid qualification text");
  }
  return value;
}
function date(value: unknown): string {
  const stamp = text(value, 40);
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(stamp)
    || !Number.isFinite(Date.parse(stamp)) || Date.parse(stamp) > Date.now() + 300_000
    || new Date(stamp).toISOString().slice(0, 19) !== stamp.slice(0, 19)) {
    throw new Error("Invalid qualification date");
  }
  return stamp;
}
const metricKeys = ["requests", "nativeRecords", "footballRecords", "candidates", "admitted"];

export function parseQualificationSnapshot(value: unknown): QualificationSnapshot {
  const data = object(value, ["schemaVersion", "capturedAt", "coverage", "results"]);
  if (data.schemaVersion !== "robin-source-qualification-v1" || data.coverage !== "partial"
    || !Array.isArray(data.results) || data.results.length > 50) throw new Error("Invalid qualification snapshot");
  const capturedAt = date(data.capturedAt);
  const ids = new Set<string>();
  const results = data.results.map((entry): QualificationResult => {
    const row = object(entry, ["id", "label", "checkedAt", "dateKind", "outcome", "summary", "scope", "nextStep", "metrics", "claims"]);
    const id = text(row.id, 80);
    if (!/^[a-z0-9-]+$/.test(id) || ids.has(id)) throw new Error("Invalid qualification identity");
    ids.add(id);
    if (row.dateKind !== "observation" && row.dateKind !== "documentary_record" && row.dateKind !== "technical_close") throw new Error("Invalid date kind");
    if (typeof row.outcome !== "string" || !["no_eligible", "technical_failure", "missing_evidence"].includes(row.outcome)) {
      throw new Error("Invalid qualification outcome");
    }
    const metrics = object(row.metrics, metricKeys);
    for (const count of Object.values(metrics)) {
      if (count !== null && (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0)) {
        throw new Error("Invalid qualification count");
      }
    }
    if (!Array.isArray(row.claims) || row.claims.length < 1 || row.claims.length > 10
      || row.claims.some((claim) => typeof claim !== "string" || claim.length > 180 || !/^[A-Z0-9_.]+$/.test(claim))) {
      throw new Error("Invalid qualification proof");
    }
    const checkedAt = date(row.checkedAt);
    if (Date.parse(checkedAt) > Date.parse(capturedAt)) throw new Error("Qualification after snapshot");
    return { id, label: text(row.label, 100), checkedAt, dateKind: row.dateKind, outcome: row.outcome as QualificationResult["outcome"],
      summary: text(row.summary), scope: text(row.scope), nextStep: text(row.nextStep),
      metrics: metrics as QualificationMetrics, claims: row.claims as string[] };
  });
  return { schemaVersion: "robin-source-qualification-v1", capturedAt, coverage: "partial", results };
}

export function qualificationCount(value: number | null): string {
  return value === null ? "Non mesuré" : String(value);
}
