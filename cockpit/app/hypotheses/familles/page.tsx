import type { Metadata } from "next";

import { HypothesisFamiliesPage } from "../../components/hypotheses/hypothesis-families-page";
import { ExperienceShell } from "../../components/navigation/experience-shell";
import { hypothesisFamilies } from "../../lib/hypothesis-universe";

export const metadata: Metadata = {
  title: "Familles d’hypothèses",
  description: `Explorez les ${hypothesisFamilies.length} familles du registre scientifique de Robin, leurs propriétés, leurs branches et leurs limites.`,
};

export default function FamiliesPage() {
  return (
    <ExperienceShell active="hypotheses">
      <HypothesisFamiliesPage />
    </ExperienceShell>
  );
}
