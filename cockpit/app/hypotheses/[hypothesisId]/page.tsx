import type { Metadata } from "next";

import {
  HistoricalEvidenceConditionsAndCoverage,
} from "../../components/hypotheses/historical-evidence-visuals";
import { HistoricalEvidenceDetail } from "../../components/hypotheses/historical-evidence-detail";
import { HistoricalEvidenceVisualsLoader } from "../../components/hypotheses/historical-evidence-visuals-loader";
import { HypothesisDetailPage } from "../../components/hypotheses/hypothesis-detail-page";
import { ExperienceShell } from "../../components/navigation/experience-shell";
import { getHistoricalHypothesisEvidence } from "../../lib/hypothesis-evidence.server";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ hypothesisId: string }>;
}): Promise<Metadata> {
  const { hypothesisId } = await params;
  const decodedId = decodeURIComponent(hypothesisId);
  const evidence = getHistoricalHypothesisEvidence(decodedId);
  return {
    description: evidence
      ? "Preuve historique réconciliée, statut scientifique et provenance."
      : "Fiche d’hypothèse de Robin des Stades.",
    title: evidence?.labelFr ?? "Fiche d’hypothèse",
  };
}

export default async function HypothesisPage({
  params,
}: {
  params: Promise<{ hypothesisId: string }>;
}) {
  const { hypothesisId } = await params;
  const decodedId = decodeURIComponent(hypothesisId);
  const historicalEvidence =
    getHistoricalHypothesisEvidence(decodedId);
  return (
    <ExperienceShell active="hypotheses">
      {historicalEvidence ? (
        <div className="hu-page hu-detail-page">
          <HistoricalEvidenceDetail
            conditionsAndCoverage={
              <HistoricalEvidenceConditionsAndCoverage
                evidence={historicalEvidence}
              />
            }
            evidence={historicalEvidence}
            visualizations={
              <HistoricalEvidenceVisualsLoader
                evidence={historicalEvidence}
              />
            }
          />
        </div>
      ) : (
        <HypothesisDetailPage
          hypothesisId={decodedId}
        />
      )}
    </ExperienceShell>
  );
}
