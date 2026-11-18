import { TipstersPilot } from "../../components/expert/tipsters-pilot";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export default function CollectionAdminRoute() {
  return <ExperienceShell active="collection-admin"><TipstersPilot admin /></ExperienceShell>;
}
