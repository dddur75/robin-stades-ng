import { TipstersPilot } from "../../components/expert/tipsters-pilot";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export default function TipstersRoute() {
  return <ExperienceShell active="tipsters"><TipstersPilot /></ExperienceShell>;
}
