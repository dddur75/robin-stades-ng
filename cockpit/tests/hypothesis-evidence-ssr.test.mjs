import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { isAbsolute, relative, resolve, sep } from "node:path";
import test from "node:test";

const publicRoot = fileURLToPath(new URL("../public/", import.meta.url));
const missingAssets = {
  fetch: async () => new Response("Not found", { status: 404 }),
};

async function exists(path) {
  try {
    await access(path);
    return true;
  } catch (error) {
    if (
      error &&
      typeof error === "object" &&
      "code" in error &&
      error.code === "ENOENT"
    ) {
      return false;
    }
    throw error;
  }
}

const publishedEvidenceAvailable = await exists(resolve(
  publicRoot,
  "data/hypothesis-evidence/manifest.json",
));
const publishedEvidenceTestOptions = publishedEvidenceAvailable
  ? {}
  : { skip: "les preuves historiques publiees sont absentes" };

function publishedAssets(requestedPaths) {
  return {
    async fetch(input) {
      const request =
        input instanceof Request ? input : new Request(input);
      const url = new URL(request.url);
      requestedPaths.push(url.pathname);
      if (request.method !== "GET" && request.method !== "HEAD") {
        return new Response("Method not allowed", { status: 405 });
      }

      let pathname;
      try {
        pathname = decodeURIComponent(url.pathname);
      } catch {
        return new Response("Not found", { status: 404 });
      }
      const candidate = resolve(
        publicRoot,
        pathname.replace(/^[/\\]+/u, ""),
      );
      const localPath = relative(publicRoot, candidate);
      if (
        localPath.length === 0 ||
        localPath === ".." ||
        localPath.startsWith(`..${sep}`) ||
        localPath.startsWith("../") ||
        isAbsolute(localPath)
      ) {
        return new Response("Not found", { status: 404 });
      }

      try {
        const body = await readFile(candidate);
        return new Response(request.method === "HEAD" ? null : body, {
          headers: {
            "content-length": String(body.byteLength),
            "content-type": "application/json; charset=utf-8",
          },
        });
      } catch (error) {
        if (
          error &&
          typeof error === "object" &&
          "code" in error &&
          (error.code === "ENOENT" || error.code === "EISDIR")
        ) {
          return new Response("Not found", { status: 404 });
        }
        throw error;
      }
    },
  };
}

async function render(
  path,
  { assets = missingAssets, includeRuntimeBindings = true } = {},
) {
  const origin = "http://localhost";
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set(
    "historical-evidence-test",
    `${process.pid}-${Date.now()}-${path}`,
  );
  const { default: worker } = await import(workerUrl.href);
  const request = new Request(`${origin}${path}`, {
    headers: {
      accept: "text/html",
      host: new URL(origin).host,
      "x-forwarded-proto": "http",
    },
  });
  if (!includeRuntimeBindings) return worker.fetch(request);
  return worker.fetch(request, { ASSETS: assets }, {
    passThroughOnException() {},
    waitUntil() {},
  });
}

async function renderWithPublishedAssets(path) {
  const requestedPaths = [];
  const response = await render(path, {
    assets: publishedAssets(requestedPaths),
  });
  return { requestedPaths, response };
}

function visibleText(html) {
  return html
    .replace(/<script\b[\s\S]*?<\/script>/giu, " ")
    .replace(/<style\b[\s\S]*?<\/style>/giu, " ")
    .replace(/<[^>]+>/gu, " ")
    .replace(/\s+/gu, " ")
    .trim();
}

async function withGlobalFetch(fetcher, callback) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = fetcher;
  try {
    return await callback();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test(
  "le worker Vinext rend une route publique sans bindings Cloudflare",
  { timeout: 5_000 },
  async () => {
    const response = await render("/robin-live", {
      includeRuntimeBindings: false,
    });
    assert.equal(response.status, 200);
    assert.match(visibleText(await response.text()), /Robin des Stades/u);
  },
);

test(
  "le worker sans env utilise le fallback HTTP pour les ressources statiques",
  { ...publishedEvidenceTestOptions, timeout: 5_000 },
  async () => {
    const requestedPaths = [];
    const fallback = publishedAssets(requestedPaths);
    const response = await withGlobalFetch(
      fallback.fetch,
      () => render("/hypotheses/J10-M002/matchs", {
        includeRuntimeBindings: false,
      }),
    );
    assert.equal(response.status, 200);
    assert.deepEqual(new Set(requestedPaths), new Set([
      "/data/hypothesis-evidence/hypotheses/J10-M002/memberships/25/page-0001.json",
      "/data/hypothesis-evidence/hypotheses/J10-M002/summary.json",
    ]));
  },
);

test(
  "le worker avec env utilise ASSETS sans fallback HTTP",
  { ...publishedEvidenceTestOptions, timeout: 5_000 },
  async () => {
    const requestedPaths = [];
    let fallbackCalls = 0;
    const response = await withGlobalFetch(
      async () => {
        fallbackCalls += 1;
        return new Response("Unexpected fallback", { status: 500 });
      },
      () => render("/hypotheses/J10-M002/matchs", {
        assets: publishedAssets(requestedPaths),
      }),
    );
    assert.equal(response.status, 200);
    assert.equal(fallbackCalls, 0);
    assert.deepEqual(new Set(requestedPaths), new Set([
      "/data/hypothesis-evidence/hypotheses/J10-M002/memberships/25/page-0001.json",
      "/data/hypothesis-evidence/hypotheses/J10-M002/summary.json",
    ]));
  },
);

test(
  "le worker transforme une ressource statique absente en 404 sans exception",
  { timeout: 5_000 },
  async () => {
    const response = await render("/hypotheses/J10-M002/matchs", {
      assets: missingAssets,
    });
    assert.equal(response.status, 404);
  },
);

test("le classement historique est rendu côté serveur et borné", async () => {
  const response = await render(
    "/hypotheses/classements?competition=Liga&tri=profit-desc",
  );
  assert.equal(response.status, 200);
  const html = await response.text();
  const text = visibleText(html);
  assert.match(text, /Classements des hypothèses/u);
  assert.match(text, /Preuve Jalon 10 réconciliée/u);
  assert.match(text, /Victoire à l’extérieur en La Liga/u);
  assert.match(text, /\+43,43 u/u);
  assert.match(text, /limite serveur 10/u);
  assert.match(
    text,
    /Exploratoire, non validée après correction/u,
  );
  assert.doesNotMatch(text, /\bDISCOVERED\b|\bVALIDATED\b/u);
});

test("les dimensions de classement sans source sont canonisées vers le ROI historique", async () => {
  const [canonicalResponse, unsupportedResponse] = await Promise.all([
    render("/hypotheses/classements"),
    render(
      "/hypotheses/classements?categorie=validated&tri=risk-asc",
    ),
  ]);
  assert.equal(canonicalResponse.status, 200);
  assert.equal(unsupportedResponse.status, 200);
  assert.equal(
    visibleText(await unsupportedResponse.text()),
    visibleText(await canonicalResponse.text()),
  );
});

test("la fiche J10 issue du rapport B est rendue sans prospectif inventé", async () => {
  const response = await render("/hypotheses/J10-M001");
  assert.equal(response.status, 200);
  const text = visibleText(await response.text());
  assert.match(text, /Victoire à l’extérieur en La Liga/u);
  assert.match(text, /\+16,64\s*%/u);
  assert.match(text, /\+43,43 u/u);
  assert.match(text, /Simulation historique/u);
  assert.match(text, /Observation depuis le gel/u);
  assert.match(text, /Marge du marché/u);
  assert.match(text, /inférieure ou égale à 6,00\s*%/u);
  assert.match(text, /Groupes statistiques distincts 225/u);
  assert.match(text, /Pourquoi ce signal n’est pas validé/u);
  assert.match(text, /aucune preuve prospective/iu);
  assert.doesNotMatch(text, /stratégie gagnante|conseil de mise/iu);
});

test("une hypothèse du top 10 absente de l’ancien modèle possède sa fiche", async () => {
  const response = await render("/hypotheses/J10-4167DA0870A37E46");
  assert.equal(response.status, 200);
  const text = visibleText(await response.text());
  assert.match(text, /J10-4167DA0870A37E46/u);
  assert.match(text, /Victoire à l’extérieur en Serie A/u);
  assert.match(text, /Pourquoi ce signal n’est pas validé/u);
});

test(
  "la liste SSR J10-M002 charge ses fragments publiés et mène vers la preuve du match",
  publishedEvidenceTestOptions,
  async () => {
  const { requestedPaths, response } = await renderWithPublishedAssets(
    "/hypotheses/J10-M002/matchs",
  );
  assert.equal(response.status, 200);
  assert.deepEqual(new Set(requestedPaths), new Set([
    "/data/hypothesis-evidence/hypotheses/J10-M002/memberships/25/page-0001.json",
    "/data/hypothesis-evidence/hypotheses/J10-M002/summary.json",
  ]));

  const html = await response.text();
  const text = visibleText(html);
  assert.match(text, /Matchs de J10-M002/u);
  assert.match(text, /363 occurrences historiques/u);
  assert.match(text, /1 à 25 sur 363 résultats/u);
  assert.match(text, /Genoa – Crotone/u);
  assert.match(text, /3,23/u);
  assert.match(text, /Perdu/u);
  assert.match(
    html,
    /href="\/matchs\/historique\/api-football%3A608482\?hypothese=J10-M002&amp;retour=%2Fhypotheses%2FJ10-M002%2Fmatchs"/u,
  );
  assert.match(
    html,
    /href="\/hypotheses\/J10-M002\/matchs\?page=2"/u,
  );
});

test(
  "la fiche SSR du match reconstruit score, contexte et navigation chronologique",
  publishedEvidenceTestOptions,
  async () => {
  const { requestedPaths, response } = await renderWithPublishedAssets(
    "/matchs/historique/api-football%3A608482",
  );
  assert.equal(response.status, 200);
  assert.deepEqual(new Set(requestedPaths), new Set([
    "/data/hypothesis-evidence/hypotheses/J10-M002/memberships/25/page-0001.json",
    "/data/hypothesis-evidence/hypotheses/J10-M002/summary.json",
    "/data/hypothesis-evidence/matches/81d46a152b95530d6d51be24334a28e9967e50519b0e29b4bea89b4f4f79c40a.json",
  ]));

  const html = await response.text();
  const text = visibleText(html);
  assert.match(text, /Genoa – Crotone/u);
  assert.match(html, /aria-label="Score final 4 – 1"/u);
  assert.match(
    text,
    /70 règle\s*s historique\s*s réconciliée\s*s/u,
  );
  assert.match(text, /1 relation navigable/u);
  assert.match(text, /Contexte actif : J10-M002/u);
  assert.match(
    text,
    /Pourquoi ce match appartenait à cette hypothèse/u,
  );
  assert.match(text, /Cote observée 3,23/u);
  assert.match(text, /Profit simulé -1,00 unité/u);
  assert.match(text, /Début de la série/u);
  assert.match(text, /Verona – Udinese/u);
  assert.match(
    html,
    /href="\/hypotheses\/J10-M002\/matchs"/u,
  );
  assert.match(
    html,
    /href="\/matchs\/historique\/api-football%3A608499\?hypothese=J10-M002&amp;retour=%2Fhypotheses%2FJ10-M002%2Fmatchs"/u,
  );
  assert.match(
    text,
    /Aucune observation prospective n’est incluse dans cette fiche/u,
  );
});
