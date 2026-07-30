import rawPresentation from "../cockpit-presentation.json";

import type { PresentationModel } from "./presentation-model";

/**
 * The only presentation fields allowed to cross the server/client boundary for
 * the shared shell. Keeping this flat also keeps React's serialized payload
 * small and auditable.
 */
export type ShellSummary = Readonly<{
  fixtures: number;
  freshnessStatus: string;
  generatedAt: string;
}>;

type ShellPresentation = Pick<PresentationModel, "dashboard">;

function buildShellSummary(value: unknown): ShellSummary {
  const presentation = value as ShellPresentation;
  const evidence = presentation.dashboard?.operationalEvidence;
  if (
    !evidence ||
    !Number.isInteger(evidence.fixtures) ||
    evidence.fixtures < 0 ||
    typeof evidence.generatedAt !== "string" ||
    !evidence.generatedAt ||
    typeof evidence.freshness?.status !== "string" ||
    !evidence.freshness.status
  ) {
    throw new Error("SHELL_PRESENTATION_SUMMARY_INVALID");
  }
  return Object.freeze({
    fixtures: evidence.fixtures,
    freshnessStatus: evidence.freshness.status,
    generatedAt: evidence.generatedAt,
  });
}

const shellSummary = buildShellSummary(rawPresentation);

export function getShellSummary(): ShellSummary {
  return shellSummary;
}
