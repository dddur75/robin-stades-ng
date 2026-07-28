import { ExperienceShell } from "../components/navigation/experience-shell";
import { ObservatoryPage } from "../components/observatory/observatory-page";

export default function ObservatoryRoute() {
  return (
    <ExperienceShell active="observatory">
      <ObservatoryPage />
    </ExperienceShell>
  );
}
