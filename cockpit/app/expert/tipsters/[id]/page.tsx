import { TipstersPilot } from "../../../components/expert/tipsters-pilot";
import { ExperienceShell } from "../../../components/navigation/experience-shell";

export default async function TipsterRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ExperienceShell active="tipsters"><TipstersPilot tipsterId={id} /></ExperienceShell>;
}
