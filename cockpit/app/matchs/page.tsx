import { MatchesPage } from "../components/matches/matches-page";
import { ExperienceShell } from "../components/navigation/experience-shell";

export default function MatchesRoute() {
  return (
    <ExperienceShell active="matches">
      <MatchesPage />
    </ExperienceShell>
  );
}
