import type { ReactNode } from "react";

import { getShellSummary } from "../../lib/presentation.server";
import {
  ExperienceShellClient,
  type PublicSection,
} from "./experience-shell-client";

export type { PublicSection } from "./experience-shell-client";

export function ExperienceShell({
  active,
  children,
}: {
  active: PublicSection;
  children: ReactNode;
}) {
  return (
    <ExperienceShellClient
      active={active}
      summary={getShellSummary()}
    >
      {children}
    </ExperienceShellClient>
  );
}
