import { notFound } from "next/navigation";

import { MatchDetail } from "../../components/matches/match-detail";
import { ExperienceShell } from "../../components/navigation/experience-shell";
import { matches } from "../../lib/presentation";

export default async function MatchRoute({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const match = matches.find((item) => item.id === id);
  if (!match) notFound();
  return (
    <ExperienceShell active="matches">
      <MatchDetail match={match} />
    </ExperienceShell>
  );
}
