import type { Metadata } from "next";

import { HypothesisDetailPage } from "../../components/hypotheses/hypothesis-detail-page";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export const metadata: Metadata = {
  title: "Fiche d’hypothèse",
};

export default async function HypothesisPage({
  params,
}: {
  params: Promise<{ hypothesisId: string }>;
}) {
  const { hypothesisId } = await params;
  return (
    <ExperienceShell active="hypotheses">
      <HypothesisDetailPage
        hypothesisId={decodeURIComponent(hypothesisId)}
      />
    </ExperienceShell>
  );
}
