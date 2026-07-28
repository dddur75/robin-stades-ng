import { ExperienceShell } from "../components/navigation/experience-shell";
import { ResultsPage } from "../components/results/results-page";

export default function ResultsRoute() {
  return (
    <ExperienceShell active="results">
      <ResultsPage />
    </ExperienceShell>
  );
}
