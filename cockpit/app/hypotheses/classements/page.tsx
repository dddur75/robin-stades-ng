import type { Metadata } from "next";

import { HistoricalEvidenceRankingsPage } from "../../components/hypotheses/historical-evidence-rankings-page";
import { ExperienceShell } from "../../components/navigation/experience-shell";
import {
  getHistoricalEvidenceRankingPage,
  getHistoricalEvidenceReportSummary,
} from "../../lib/hypothesis-evidence.server";
import {
  parseRankingListQuery,
  serializeRankingListQuery,
  type SearchParamRecord,
} from "../../lib/query-params";

export const metadata: Metadata = {
  title: "Classements des hypothèses",
};

export default async function RankingsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParamRecord>;
}) {
  const query = parseRankingListQuery(await searchParams);
  const evidencePage = getHistoricalEvidenceRankingPage(query);
  const summary = getHistoricalEvidenceReportSummary();
  return (
    <ExperienceShell active="hypotheses">
      <HistoricalEvidenceRankingsPage
        canonicalSearchParams={serializeRankingListQuery(query).toString()}
        page={evidencePage}
        summary={summary}
      />
    </ExperienceShell>
  );
}
