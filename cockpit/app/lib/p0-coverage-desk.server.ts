import rawCoverageProjection from "../../private-coverage/p0-denominator-status-v1.json";

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
    rawCoverageProjection,
    canonicalCalendarPropertyIds,
  );
  return cachedModel;
}
