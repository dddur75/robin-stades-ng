import denominatorContract from "../../../configs/data/historical-coverage-denominator-contract-v1.json";
import grainCatalog from "../../../configs/data/football-grain-catalog-v1.json";
import closureSummary from "../../../reports/coverage/denominator-closure-summary-v1.json";
import propertyReadiness from "../../../reports/coverage/p0-property-readiness-v1.json";
import readinessGates from "../../../reports/coverage/p0-readiness-gates-v1.json";

import { hypothesisSemanticRoles } from "./hypothesis-quality";
import {
  buildP0CoverageDeskModel,
  type CoverageDeskModel,
} from "./p0-coverage-desk";

const calendarPrefix = "football:calendar_fatigue:";
const canonicalCalendarPropertyIds = hypothesisSemanticRoles.items
  .filter((item) => item.family === "CALENDAR_FATIGUE")
  .map((item) => item.property_id.replace(calendarPrefix, ""));

let cachedModel: CoverageDeskModel | undefined;

export function getP0CoverageDeskModel(): CoverageDeskModel {
  cachedModel ??= buildP0CoverageDeskModel(
    {
      contract: denominatorContract,
      grainCatalog,
      summary: closureSummary,
      propertyReadiness,
      readinessGates,
    },
    canonicalCalendarPropertyIds,
  );
  return cachedModel;
}
