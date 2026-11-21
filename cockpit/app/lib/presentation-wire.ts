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

/** Factor only timeline policies; preserve every other presentation field. */
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
    const timeline = [];
    for (const item of array(match.timeline)) {
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
      timeline.push({ ...fields, policyVersionIndex: index });
    }
    matches.push({ ...match, timeline });
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
      timeline.push({ ...fields, policyVersion: policies[policyVersionIndex] });
    }
    matches.push({ ...match, timeline });
  }
  const result: JsonObject = { ...wire, matches };
  delete result.timelinePolicyVersions;
  return result;
}

