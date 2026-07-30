import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ScientificFunnel } from "../app/components/hypotheses/hypothesis-universe-page";

function visibleText(html: string) {
  return html.replace(/<[^>]+>/gu, " ").replace(/\s+/gu, " ").trim();
}

test("l’entonnoir prospectif sépare chaque état contractuel existant", () => {
  const html = renderToStaticMarkup(createElement(ScientificFunnel));
  const text = visibleText(html);

  assert.match(text, /Contrats gelés 3/u);
  assert.match(text, /Observations réelles 0/u);
  assert.match(text, /Observations réglées 0/u);
  assert.match(text, /Stratégies validées 0/u);
  assert.equal((html.match(/data-zero="true"/gu) ?? []).length, 3);
  assert.match(
    text,
    /3 contrats gelés, 0 observations réelles, 0 observations réglées et 0 stratégies validées/u,
  );
});

test("une valeur nulle ne produit aucune largeur de barre", async () => {
  const css = await readFile(
    new URL("../app/hypotheses.css", import.meta.url),
    "utf8",
  );

  assert.match(
    css,
    /\.hu-funnel li > span\[data-zero="true"\]\s*\{[^}]*min-width:\s*0;[^}]*width:\s*0\s*!important;/su,
  );
});
