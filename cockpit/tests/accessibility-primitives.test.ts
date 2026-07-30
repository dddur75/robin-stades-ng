import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  nextEnabledTabIndex,
  type AccessibleTab,
} from "../app/components/common/accessible-tabs";
import {
  Pagination,
  paginationHref,
  paginationItems,
} from "../app/components/common/pagination";

const tabs: readonly AccessibleTab<"summary" | "odds" | "evidence">[] = [
  { id: "summary", label: "Résumé", panel: "Résumé" },
  { disabled: true, id: "odds", label: "Cotes", panel: "Cotes" },
  { id: "evidence", label: "Preuves", panel: "Preuves" },
];

test("les flèches, Début et Fin ignorent les onglets désactivés et bouclent", () => {
  assert.equal(nextEnabledTabIndex(tabs, 0, "ArrowRight"), 2);
  assert.equal(nextEnabledTabIndex(tabs, 2, "ArrowRight"), 0);
  assert.equal(nextEnabledTabIndex(tabs, 0, "ArrowLeft"), 2);
  assert.equal(nextEnabledTabIndex(tabs, 2, "Home"), 0);
  assert.equal(nextEnabledTabIndex(tabs, 0, "End"), 2);
});

test("les touches incompatibles avec l’orientation ne déplacent pas le focus", () => {
  assert.equal(
    nextEnabledTabIndex(tabs, 0, "ArrowDown", "horizontal"),
    0,
  );
  assert.equal(
    nextEnabledTabIndex(tabs, 0, "ArrowRight", "vertical"),
    0,
  );
  assert.equal(
    nextEnabledTabIndex(tabs, 0, "ArrowDown", "vertical"),
    2,
  );
});

test("la fenêtre de pagination reste concise et annonce les ruptures", () => {
  assert.deepEqual(paginationItems(1, 1), [1]);
  assert.deepEqual(paginationItems(5, 10), [
    1,
    "ellipsis",
    4,
    5,
    6,
    "ellipsis",
    10,
  ]);
});

test("les liens de pagination conservent les filtres et réinitialisent les défauts", () => {
  const filters = new URLSearchParams(
    "statut=PARTIAL&competition=Ligue+1&page=4",
  );
  assert.equal(
    paginationHref("/matchs", filters, 1, 25),
    "/matchs?competition=Ligue+1&statut=PARTIAL",
  );
  assert.equal(
    paginationHref("/matchs", filters, 2, 50),
    "/matchs?competition=Ligue+1&page=2&statut=PARTIAL&taille=50",
  );
});

test("le choix de taille de page est regroupé par fieldset et legend", () => {
  const html = renderToStaticMarkup(
    createElement(Pagination, {
      pagination: {
        from: 1,
        hasNext: true,
        hasPrevious: false,
        page: 1,
        pageSize: 25,
        to: 25,
        totalItems: 30,
        totalPages: 2,
      },
      pathname: "/matchs",
    }),
  );
  assert.match(html, /<fieldset class="pagination-sizes">/u);
  assert.match(html, /<legend>Résultats par page<\/legend>/u);
});
