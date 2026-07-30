import assert from "node:assert/strict";
import test from "node:test";

import { requiredIsoInstant } from "../scripts/presentation-build-clock";

const ERROR_CODE = "COCKPIT_SNAPSHOT_GENERATED_AT_INVALID";

test("l’horloge de build accepte un instant ISO avec microsecondes", () => {
  const instant = requiredIsoInstant(
    "2026-07-29T13:21:24.202327+00:00",
    ERROR_CODE,
  );

  assert.equal(instant.toISOString(), "2026-07-29T13:21:24.202Z");
});

test("l’horloge de build refuse les instants absents ou invalides", () => {
  const invalidValues = [
    null,
    "2026-07-29T13:21:24",
    "2026-02-30T12:00:00Z",
    "2026-01-01T24:00:00Z",
    "2026-01-01T12:00:00+14:01",
  ];

  for (const value of invalidValues) {
    assert.throws(
      () => requiredIsoInstant(value, ERROR_CODE),
      { message: ERROR_CODE },
    );
  }
});
