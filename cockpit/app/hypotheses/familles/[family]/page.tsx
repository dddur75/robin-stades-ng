import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { HypothesisFamilyPage } from "../../../components/hypotheses/hypothesis-family-page";
import { ExperienceShell } from "../../../components/navigation/experience-shell";
import {
  familySlug,
  findFamily,
  hypothesisFamilies,
} from "../../../lib/hypothesis-universe";

export function generateStaticParams() {
  return hypothesisFamilies.map((family) => ({
    family: familySlug(family.family),
  }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ family: string }>;
}): Promise<Metadata> {
  const { family: rawFamily } = await params;
  const family = findFamily(decodeURIComponent(rawFamily));
  if (!family) return { title: "Famille introuvable" };
  return {
    title: family.display_name_fr,
    description: `Explorez les propriétés, arbres et preuves de la famille ${family.display_name_fr}.`,
  };
}

export default async function FamilyPage({
  params,
}: {
  params: Promise<{ family: string }>;
}) {
  const { family: rawFamily } = await params;
  const family = findFamily(decodeURIComponent(rawFamily));
  if (!family) notFound();

  return (
    <ExperienceShell active="hypotheses">
      <HypothesisFamilyPage family={family} />
    </ExperienceShell>
  );
}
