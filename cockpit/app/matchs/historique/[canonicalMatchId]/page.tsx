import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";

import { HistoricalEvidenceUnavailable } from "../../../components/common/historical-evidence-unavailable";
import { HistoricalMatchDetailPage } from "../../../components/matches/historical-match-detail-page";
import { ExperienceShell } from "../../../components/navigation/experience-shell";
import {
  historicalEvidenceErrorCode,
  historicalEvidenceLoaderOptionsFromHeaders,
  isHistoricalEvidenceNotFound,
  loadHistoricalMatchDetailPage,
} from "../../../lib/historical-match-evidence.server";
import {
  historicalMatchDetailPath,
  parseHistoricalMatchContext,
} from "../../../lib/historical-match-evidence";
import type { SearchParamRecord } from "../../../lib/query-params";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  description:
    "Fiche sourcée d’un match historique et des hypothèses auxquelles il appartenait, sans mélange prospectif.",
  title: "Preuve historique d’un match",
};

function decodePathSegment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    notFound();
  }
}

export default async function HistoricalMatchDetailRoute({
  params,
  searchParams,
}: {
  params: Promise<{ canonicalMatchId: string }>;
  searchParams: Promise<SearchParamRecord>;
}) {
  const [{ canonicalMatchId: rawCanonicalMatchId }, rawSearchParams] =
    await Promise.all([params, searchParams]);
  const canonicalMatchId = decodePathSegment(rawCanonicalMatchId);
  const context = parseHistoricalMatchContext(rawSearchParams);
  let retryHref = `/matchs/historique/${encodeURIComponent(canonicalMatchId)}`;
  let data: Awaited<ReturnType<typeof loadHistoricalMatchDetailPage>> | null =
    null;
  let failureCode = "HISTORICAL_EVIDENCE_UNAVAILABLE";
  try {
    retryHref = historicalMatchDetailPath(canonicalMatchId, {
      hypothesisId: context.hypothesisId,
      returnTo: context.returnTo,
    });
    const requestHeaders = await headers();
    data = await loadHistoricalMatchDetailPage(
      canonicalMatchId,
      context,
      historicalEvidenceLoaderOptionsFromHeaders(requestHeaders),
    );
  } catch (error) {
    if (isHistoricalEvidenceNotFound(error)) notFound();
    failureCode = historicalEvidenceErrorCode(error);
  }
  if (data === null) {
    return (
      <ExperienceShell active="matches">
        <HistoricalEvidenceUnavailable
          code={failureCode}
          retryHref={retryHref}
        />
      </ExperienceShell>
    );
  }
  return (
    <ExperienceShell active="matches">
      <HistoricalMatchDetailPage data={data} />
    </ExperienceShell>
  );
}
