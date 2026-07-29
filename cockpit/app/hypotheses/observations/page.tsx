import type { Metadata } from "next";

import { HypothesisRankingsPage } from "../../components/hypotheses/hypothesis-rankings-page";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export const metadata: Metadata = {
  title: "Observations prospectives",
};

export default function ObservationsPage() {
  return (
    <ExperienceShell active="hypotheses">
      <HypothesisRankingsPage variant="observations" />
    </ExperienceShell>
  );
}
