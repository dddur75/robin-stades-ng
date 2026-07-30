import type { Metadata } from "next";

import { DataQualityDiagnostics } from "../../components/expert/data-quality-diagnostics";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export const metadata: Metadata = {
  title: "Qualité et disponibilité des données",
  description:
    "Diagnostics de valeurs manquantes, couverture, disponibilité et provenance, séparés des hypothèses football.",
};

export default function DataQualityRoute() {
  return (
    <ExperienceShell active="expert">
      <DataQualityDiagnostics />
    </ExperienceShell>
  );
}
