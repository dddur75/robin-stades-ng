type JsonObject = Record<string, unknown>;

function object(value: unknown): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("PRESENTATION_WIRE_OBJECT_INVALID");
  }
  return value as JsonObject;
}

function array(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error("PRESENTATION_WIRE_ARRAY_INVALID");
  return value;
}

function owns(value: JsonObject, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

/** Factor repeated timeline policies and parent metadata; preserve every presented field. */
export function encodePresentationWire(value: unknown): JsonObject {
  const source = object(value);
  if (owns(source, "timelinePolicyVersions")) {
    throw new Error("PRESENTATION_WIRE_DICTIONARY_COLLISION");
  }
  const policies: string[] = [];
  const indices = new Map<string, number>();
  const matches = [];
  for (const item of array(source.matches)) {
    const match = object(item);
    if (owns(match, "timelineMatchMetadataShared")) {
      throw new Error("PRESENTATION_WIRE_MATCH_METADATA_COLLISION");
    }
    const windows = array(match.timeline);
    const shared = windows.length > 0 && typeof match.id === "string" && typeof match.kickoff === "string"
      && windows.every((item) => {
        const window = object(item);
        return owns(window, "fixtureId") && owns(window, "kickoffAt")
          && window.fixtureId === match.id && window.kickoffAt === match.kickoff;
      });
    const timeline = [];
    for (const item of windows) {
      const window = object(item);
      if (owns(window, "policyVersionIndex")) {
        throw new Error("PRESENTATION_WIRE_INDEX_COLLISION");
      }
      const { policyVersion, ...fields } = window;
      if (!owns(window, "policyVersion") || typeof policyVersion !== "string") {
        throw new Error("PRESENTATION_WIRE_POLICY_INVALID");
      }
      let index = indices.get(policyVersion);
      if (index === undefined) {
        index = policies.length;
        policies.push(policyVersion);
        indices.set(policyVersion, index);
      }
      if (shared) { delete fields.fixtureId; delete fields.kickoffAt; }
      timeline.push({ ...fields, policyVersionIndex: index });
    }
    matches.push({ ...match, ...(shared ? { timelineMatchMetadataShared: true } : {}), timeline });
  }
  return { ...source, matches, timelinePolicyVersions: policies };
}

/** Fail closed before exposing a decoded presentation to client consumers. */
export function decodePresentationWire(value: unknown): JsonObject {
  const wire = object(value);
  if (!owns(wire, "timelinePolicyVersions")) {
    throw new Error("PRESENTATION_WIRE_DICTIONARY_MISSING");
  }
  const policies = array(wire.timelinePolicyVersions);
  const uniquePolicies = new Set<string>();
  for (const policy of policies) {
    if (typeof policy !== "string" || uniquePolicies.has(policy)) {
      throw new Error("PRESENTATION_WIRE_DICTIONARY_INVALID");
    }
    uniquePolicies.add(policy);
  }
  const matches = [];
  for (const item of array(wire.matches)) {
    const match = object(item);
    const { timelineMatchMetadataShared, ...matchFields } = match;
    const shared = owns(match, "timelineMatchMetadataShared");
    if (shared && (timelineMatchMetadataShared !== true || typeof match.id !== "string"
      || typeof match.kickoff !== "string" || array(match.timeline).length === 0)) {
      throw new Error("PRESENTATION_WIRE_MATCH_METADATA_INVALID");
    }
    const timeline = [];
    for (const item of array(match.timeline)) {
      const window = object(item);
      if (owns(window, "policyVersion")) {
        throw new Error("PRESENTATION_WIRE_POLICY_COLLISION");
      }
      const { policyVersionIndex, ...fields } = window;
      if (
        !owns(window, "policyVersionIndex") ||
        typeof policyVersionIndex !== "number" ||
        !Number.isSafeInteger(policyVersionIndex) ||
        policyVersionIndex < 0 ||
        policyVersionIndex >= policies.length
      ) {
        throw new Error("PRESENTATION_WIRE_INDEX_INVALID");
      }
      if (shared) {
        if (owns(window, "fixtureId") || owns(window, "kickoffAt")) {
          throw new Error("PRESENTATION_WIRE_MATCH_METADATA_COLLISION");
        }
        fields.fixtureId = match.id;
        fields.kickoffAt = match.kickoff;
      }
      timeline.push({ ...fields, policyVersion: policies[policyVersionIndex] });
    }
    matches.push({ ...matchFields, timeline });
  }
  const result: JsonObject = { ...wire, matches };
  delete result.timelinePolicyVersions;
  return result;
}

