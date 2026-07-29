import { LearningPage } from "../components/learning/learning-page";
import { ExperienceShell } from "../components/navigation/experience-shell";

export default function LearningRoute() {
  return (
    <ExperienceShell active="learning">
      <LearningPage />
    </ExperienceShell>
  );
}
