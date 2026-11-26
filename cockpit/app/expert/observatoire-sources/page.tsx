import type { Metadata } from "next";

import { SourceObservatory, type SourceObservatorySnapshot } from "../../components/expert/source-observatory";
import { ExperienceShell } from "../../components/navigation/experience-shell";
import snapshot from "../../source-observatory-snapshot.json";

export const metadata: Metadata = {
  title: "Observatoire des sources",
  description: "Suivi du pilote Ligue 1 de collecte des pronostics publics.",
};

export default function SourceObservatoryRoute() {
  return (
    <ExperienceShell active="source-observatory">
      <SourceObservatory snapshot={snapshot as SourceObservatorySnapshot} />
    </ExperienceShell>
  );
}
