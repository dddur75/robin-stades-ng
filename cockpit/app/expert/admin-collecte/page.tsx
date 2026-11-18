import { TipstersPilot } from "../../components/expert/tipsters-pilot";
import { TipsterConnectors } from "../../components/expert/tipster-connectors";
import { TipstersRecurringControl } from "../../components/expert/tipsters-recurring-control";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export default function CollectionAdminRoute() {
  return <ExperienceShell active="collection-admin"><TipstersPilot admin><TipstersRecurringControl /><TipsterConnectors /></TipstersPilot></ExperienceShell>;
}
