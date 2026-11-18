import { TipstersPilot } from "../../components/expert/tipsters-pilot";
import { TipstersRecurringControl } from "../../components/expert/tipsters-recurring-control";
import { ExperienceShell } from "../../components/navigation/experience-shell";

export default async function RecurringRoute({ searchParams }: {searchParams: Promise<{view?: string}>}) {
  const {view} = await searchParams;
  return <ExperienceShell active="collection-admin"><TipstersPilot endpoint="/api/tipsters/recurring" admin={view !== "tipsters"}>
    <TipstersRecurringControl />
  </TipstersPilot></ExperienceShell>;
}
