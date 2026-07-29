import type { Metadata } from "next";

import { HypothesisRankingsPage } from "../../components/hypotheses/hypothesis-rankings-page";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export const metadata: Metadata = {
  title: "Classements des hypothèses",
};

export default async function RankingsPage({
  searchParams,
}: {
  searchParams: Promise<{ competition?: string }>;
}) {
  const { competition = "GLOBAL" } = await searchParams;
  return (
    <ExperienceShell active="hypotheses">
      <HypothesisRankingsPage initialCompetition={competition} />
    </ExperienceShell>
  );
}
