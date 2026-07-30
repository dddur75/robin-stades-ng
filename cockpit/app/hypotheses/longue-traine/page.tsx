import type { Metadata } from "next";

import { HypothesisRankingsPage } from "../../components/hypotheses/hypothesis-rankings-page";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export const metadata: Metadata = {
  title: "Longue traîne des hypothèses",
};

export default function LongTailPage() {
  return (
    <ExperienceShell active="hypotheses">
      <HypothesisRankingsPage variant="longue-traine" />
    </ExperienceShell>
  );
}
