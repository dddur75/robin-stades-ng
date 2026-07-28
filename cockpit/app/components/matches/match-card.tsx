import Link from "next/link";

import {
  formatDateTime,
  formatPercent,
  t,
} from "../../i18n";
import {
  dataFamilyLabels,
  type MatchPresentation,
} from "../../lib/presentation";
import { ProgressBar, StatusBadge } from "../common/ui";
import { ExpertOnly } from "../common/view-mode";

export function MatchCard({ match }: { match: MatchPresentation }) {
  const available = Object.entries(match.families)
    .filter(([, state]) => state === "captured")
    .map(([family]) => dataFamilyLabels[family] ?? family);

  return (
    <article className="match-card">
      <div className="match-card-top">
        <span className="competition-chip">{match.competition}</span>
        <StatusBadge value={match.dataStatus} />
      </div>
      <time dateTime={match.kickoff}>{formatDateTime(match.kickoff, true)}</time>
      <div className="teams">
        <strong>{match.home}</strong>
        <span>—</span>
        <strong>{match.away}</strong>
      </div>
      <div className="match-card-data">
        <div>
          <span>{t("matches.dataAvailable")}</span>
          <strong>{available.join(" · ") || t("common.notAvailable")}</strong>
        </div>
        <div>
          <span>{t("matches.nextCapture")}</span>
          <strong>{formatDateTime(match.nextCapture)}</strong>
        </div>
      </div>
      <ProgressBar
        label={`${t("matches.coverage")} · ${formatPercent(match.coverage)}`}
        value={match.coverage}
      />
      <div className="match-card-foot">
        <span>
          {match.hypotheses} {t("matches.hypotheses")}
        </span>
        <Link href={`/matchs/${match.id}`}>
          Voir la fiche <span aria-hidden="true">→</span>
        </Link>
      </div>
      <ExpertOnly>
        <div className="technical-strip">
          <code>{match.providerId}</code>
          <code>{match.internalId.slice(0, 12)}…</code>
        </div>
      </ExpertOnly>
    </article>
  );
}
