import { PublicTipsters } from "../../components/expert/public-tipsters";
import { TipstersPilot } from "../../components/expert/tipsters-pilot";
import { TipsterConnectors } from "../../components/expert/tipster-connectors";
import { TipstersRecurringControl } from "../../components/expert/tipsters-recurring-control";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export default function TipstersRoute() {
  return <ExperienceShell active="tipsters"><TipstersPilot><PublicTipsters compact /><TipstersRecurringControl compact /><TipsterConnectors compact /></TipstersPilot></ExperienceShell>;
}
