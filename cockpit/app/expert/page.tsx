import { ExpertPage } from "../components/expert/expert-page";
import { ExperienceShell } from "../components/navigation/experience-shell";

export default function ExpertRoute() {
  return (
    <ExperienceShell active="expert">
      <ExpertPage />
    </ExperienceShell>
  );
}
