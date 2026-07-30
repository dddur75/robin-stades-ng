import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ScientificFunnel } from "../app/components/hypotheses/hypothesis-universe-page";

function visibleText(html: string) {
  return html.replace(/<[^>]+>/gu, " ").replace(/\s+/gu, " ").trim();
}

test("l’entonnoir prospectif sépare chaque état contractuel existant", () => {
  const text = visibleText(
    renderToStaticMarkup(createElement(ScientificFunnel)),
  );

  assert.match(text, /Contrats gelés 3/u);
  assert.match(text, /Observations réelles 0/u);
  assert.match(text, /Observations réglées 0/u);
  assert.match(text, /Stratégies validées 0/u);
  assert.match(
    text,
    /3 contrats gelés, 0 observations réelles, 0 observations réglées et 0 stratégies validées/u,
  );
});
