import type { Metadata } from "next";

import { DataQualityDiagnostics } from "../../components/expert/data-quality-diagnostics";
import { ExperienceShell } from "../../components/navigation/experience-shell";
import { getP0CoverageDeskModel } from "../../lib/p0-coverage-desk.server";

export const metadata: Metadata = {
  title: "Qualité et disponibilité des données",
  description:
    "Diagnostics de valeurs manquantes, couverture, disponibilité et provenance, séparés des hypothèses football.",
};

export default function DataQualityRoute() {
  const p0Coverage = getP0CoverageDeskModel();
  return (
    <ExperienceShell active="expert">
      <DataQualityDiagnostics p0Coverage={p0Coverage} />
    </ExperienceShell>
  );
}
