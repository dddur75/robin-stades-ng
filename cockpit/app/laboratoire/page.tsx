import { LaboratoryPage } from "../components/laboratory/laboratory-page";
import { ExperienceShell } from "../components/navigation/experience-shell";

export default function LaboratoryRoute() {
  return (
    <ExperienceShell active="laboratory">
      <LaboratoryPage />
    </ExperienceShell>
  );
}
