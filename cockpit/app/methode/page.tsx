import { MethodPage } from "../components/method/method-page";
import { ExperienceShell } from "../components/navigation/experience-shell";

export default function MethodRoute() {
  return (
    <ExperienceShell active="method">
      <MethodPage />
    </ExperienceShell>
  );
}
