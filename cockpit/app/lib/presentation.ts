import expertSnapshot from "../cockpit-expert-data.json";
import presentation from "../cockpit-presentation.json";

import {
  type CoverageState,
  type MatchPresentation,
  type PresentationModel,
} from "./presentation-model";

export type { CoverageState, MatchPresentation };

const typedPresentation = presentation as unknown as PresentationModel;

export const operationalEvidence = typedPresentation.dashboard.operationalEvidence;
export const matches = typedPresentation.matches;
export const nextCaptures = typedPresentation.nextCaptures;
export const hypotheses = typedPresentation.hypotheses;
export const gateRows = typedPresentation.observatory.gateRows;
export const oddsSnapshots = typedPresentation.oddsSnapshots;
export const presentationSystem = typedPresentation.system;
export const presentationBankroll = typedPresentation.dashboard.bankroll;

export const dataFamilyLabels: Record<string, string> = {
  FIXTURE: "Rencontre",
  TEAM: "Équipe",
  SQUAD: "Effectif",
  PLAYER_STATUS: "État joueur",
  INJURY: "Blessures",
  LINEUP: "Composition",
  FORMATION: "Formation",
  ODDS: "Cotes",
  EVENT_STATUS: "État du match",
  FOOTEDNESS: "Pied fort",
};

export const expertData = {
  datasets: expertSnapshot.datasets,
  models: expertSnapshot.models,
  backtests: expertSnapshot.backtests,
  qualityChecks: expertSnapshot.qualityChecks,
  providers: expertSnapshot.providers,
  incidents: expertSnapshot.incidents,
  quota: expertSnapshot.quota,
  provenance: expertSnapshot.provenance,
  externalValidation: expertSnapshot.externalValidation,
  matchup: expertSnapshot.matchup,
  patternResearch: expertSnapshot.patternResearch,
};

export const scientificInvariants = expertSnapshot.patternResearch;
