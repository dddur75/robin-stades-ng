import type { Metadata } from "next";

import { HypothesisUniversePage } from "../components/hypotheses/hypothesis-universe-page";
import { ExperienceShell } from "../components/navigation/experience-shell";

export const metadata: Metadata = {
  title: "L’Univers des hypothèses",
  description:
    "Explorez les familles, arbres, observations et preuves de l’univers scientifique de Robin des Stades.",
};

export default function HypothesesPage() {
  return (
    <ExperienceShell active="hypotheses">
      <HypothesisUniversePage />
    </ExperienceShell>
  );
}
