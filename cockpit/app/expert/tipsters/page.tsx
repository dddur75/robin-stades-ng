import { TipstersPilot } from "../../components/expert/tipsters-pilot";
import { TipsterConnectors } from "../../components/expert/tipster-connectors";
import { TipstersRecurringControl } from "../../components/expert/tipsters-recurring-control";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export default function TipstersRoute() {
  return <ExperienceShell active="tipsters"><TipstersPilot><TipstersRecurringControl compact /><TipsterConnectors compact /></TipstersPilot></ExperienceShell>;
}
