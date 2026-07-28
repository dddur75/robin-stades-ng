import { DashboardPage } from "./components/dashboard/dashboard-page";
import { ExperienceShell } from "./components/navigation/experience-shell";

export default function HomePage() {
  return (
    <ExperienceShell active="home">
      <DashboardPage />
    </ExperienceShell>
  );
}
