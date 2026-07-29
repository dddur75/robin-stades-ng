import type { Metadata } from "next";
import type { ReactNode } from "react";

import "../hypotheses.css";

export const metadata: Metadata = {
  title: "L’Univers des hypothèses",
  description:
    "Explorez les familles et les arbres d’hypothèses football de Robin, avec des preuves datées, sans pari réel ni promesse de gain.",
  openGraph: {
    title: "L’Univers des hypothèses · Robin des Stades",
    description:
      "Explorer, comparer et comprendre les idées football que Robin teste sans réécrire le passé.",
  },
  twitter: {
    card: "summary_large_image",
    title: "L’Univers des hypothèses · Robin des Stades",
    description:
      "Une exploration football transparente, sans pari réel ni promesse de gain.",
  },
};

export default function HypothesesLayout({
  children,
}: {
  children: ReactNode;
}) {
  return children;
}
