import { TipstersPilot } from "../../components/expert/tipsters-pilot";
import { TipsterConnectors } from "../../components/expert/tipster-connectors";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export default function CollectionAdminRoute() {
  return <ExperienceShell active="collection-admin"><TipstersPilot admin><TipsterConnectors /></TipstersPilot></ExperienceShell>;
}
