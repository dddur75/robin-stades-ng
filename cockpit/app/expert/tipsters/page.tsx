import { TipstersPilot } from "../../components/expert/tipsters-pilot";
import { TipsterConnectors } from "../../components/expert/tipster-connectors";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export default function TipstersRoute() {
  return <ExperienceShell active="tipsters"><TipstersPilot><TipsterConnectors compact /></TipstersPilot></ExperienceShell>;
}
