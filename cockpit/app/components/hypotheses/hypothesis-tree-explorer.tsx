"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

import { formatNumber } from "../../i18n";
import {
  compactNodeId,
  familyDisplayName,
  familySlug,
  hypothesisChildrenByParent,
  hypothesisFacets,
  hypothesisFamilies,
  hypothesisNodeLocator,
  hypothesisNodePages,
  hypothesisTree,
  propertyDisplayName,
  scientificStatusLabel,
  subfamilyDisplayName,
  type HypothesisTreeNode,
} from "../../lib/hypothesis-universe";
import {
  nodeMatchesUnderstoodFilters,
  type UnderstoodFilter,
} from "../../lib/hypothesis-filter";
import { useViewMode } from "../common/view-mode";
import { NaturalLanguageFilter } from "./natural-language-filter";
import {
  HonestEmptyState,
  HypothesisBreadcrumbs,
  HypothesisSubnav,
  ScientificStatusBadge,
  TagChip,
  UniverseMetric,
  UniverseSectionHeading,
} from "./hypothesis-primitives";

type TreeLayout = "arbre" | "graphe" | "liste";
type NodePage = { items: HypothesisTreeNode[] };
type FacetSelection = "ALL" | string;

const collectionBatchSize = 60;

const cutoffLabels: Record<string, string> = {
  "H-24": "Vingt-quatre heures avant le match",
  "H-2": "Deux heures avant le match",
  NEAR_KICKOFF: "Près du coup d’envoi",
  POST_LINEUP: "Après publication des compositions",
};

const marketLabels: Record<string, string> = {
  "1X2": "Résultat du match",
  CARDS_IF_PRICED: "Cartons, si un prix existe",
  GOALS_TOTAL: "Total de buts",
  NO_MARKET_REQUIRED: "Aucun marché requis",
  OPTIONAL_MARKET: "Marché facultatif",
  OVER_UNDER_2_5: "Plus ou moins de 2,5 buts",
  PLAYER_PROPS_IF_PRICED: "Statistiques joueur, si un prix existe",
};

const familyOptions = hypothesisFamilies.filter((family) =>
  Object.hasOwn(hypothesisFacets.families, family.family),
);
const statusOptions = Object.keys(hypothesisFacets.statuses);
const cutoffOptions = hypothesisFacets.cutoffs;
const marketOptions = hypothesisFacets.markets;
const depthOptions = hypothesisFacets.tree_depths;

function normalizeInitialFamily(value: string): FacetSelection {
  if (!value) return "ALL";
  const normalized = value.toLocaleLowerCase("fr-FR");
  return (
    familyOptions.find(
      (family) =>
        family.family.toLocaleLowerCase("fr-FR") === normalized ||
        familySlug(family.family) === normalized,
    )?.family ?? "ALL"
  );
}

function normalizeInitialFacet(
  value: string,
  options: readonly string[],
): FacetSelection {
  return options.includes(value) ? value : "ALL";
}

function normalizeInitialDepth(value: string): FacetSelection {
  const depth = Number(value);
  return Number.isInteger(depth) && depthOptions.includes(depth)
    ? String(depth)
    : "ALL";
}

function normalizeInitialLayout(value: string): TreeLayout {
  return value === "graphe" || value === "liste" ? value : "arbre";
}

function nodeCutoff(node: HypothesisTreeNode) {
  const cutoff = node.technical_rule.cutoff;
  return typeof cutoff === "string" ? cutoff : null;
}

function nodeMarket(node: HypothesisTreeNode) {
  const market = node.technical_rule.market;
  return typeof market === "string" && market
    ? market
    : "NO_MARKET_REQUIRED";
}

function nodeDepth(node: HypothesisTreeNode) {
  const predicates = node.technical_rule.predicates;
  return Array.isArray(predicates) ? predicates.length : 0;
}

function lastCondition(node: HypothesisTreeNode) {
  const predicates = node.technical_rule.predicates;
  if (!Array.isArray(predicates) || !predicates.length) {
    return node.display_rule_fr;
  }
  const last = predicates[predicates.length - 1] as {
    property_id?: unknown;
    value?: unknown;
  };
  if (typeof last.property_id !== "string") return node.display_rule_fr;
  const property = propertyDisplayName(last.property_id);
  const publicValues: Record<string, string> = {
    LEFT: "Gauche",
    true: "Oui",
  };
  const value =
    last.value == null
      ? null
      : publicValues[String(last.value)] ?? String(last.value);
  return value == null ? property : `${property} · ${value}`;
}

function NodeCard({
  compareIds,
  expanded,
  layout,
  node,
  onCompare,
  onToggle,
}: {
  compareIds: string[];
  expanded: boolean;
  layout: TreeLayout;
  node: HypothesisTreeNode;
  onCompare: (nodeId: string) => void;
  onToggle: (node: HypothesisTreeNode) => void;
}) {
  const childIds = hypothesisChildrenByParent[node.node_id] ?? [];
  const selected = compareIds.includes(node.node_id);
  const comparisonDisabled = compareIds.length >= 4 && !selected;
  return (
    <article
      className={`hu-tree-node hu-tree-node-${layout}`}
      data-disposition={node.materialization_disposition}
    >
      <div className="hu-tree-node-rail" aria-hidden="true">
        <span />
      </div>
      <div className="hu-tree-node-main">
        <div className="hu-tree-node-head">
          <span className="hu-node-id">{compactNodeId(node.node_id)}</span>
          <ScientificStatusBadge status={node.materialization_disposition} />
        </div>
        <h3>{node.display_rule_fr}</h3>
        <p className="hu-node-condition">
          Condition ajoutée : <strong>{lastCondition(node)}</strong>
        </p>
        <div className="hu-tag-list">
          <TagChip kind="family" tagId={`family:${node.family}`}>
            {familyDisplayName(node.family)}
          </TagChip>
          <TagChip tagId={`subfamily:${node.subfamily}`}>
            {subfamilyDisplayName(node.subfamily)}
          </TagChip>
          <TagChip kind="value">Profondeur {nodeDepth(node)}</TagChip>
          <TagChip kind="science">
            {node.support == null
              ? "Support non disponible"
              : `${formatNumber(node.support)} matchs`}
          </TagChip>
        </div>
        <dl className="hu-node-facts">
          <div>
            <dt>Disponibilité</dt>
            <dd>{node.data_gates.map(scientificStatusLabel).join(" · ")}</dd>
          </div>
          <div>
            <dt>Enfants connus</dt>
            <dd>{formatNumber(childIds.length)}</dd>
          </div>
          <div>
            <dt>Parents</dt>
            <dd>{formatNumber(node.parent_ids.length)}</dd>
          </div>
        </dl>
        <div className="hu-node-actions">
          {childIds.length ? (
            <button
              aria-expanded={expanded}
              onClick={() => onToggle(node)}
              type="button"
            >
              {expanded ? "Replier" : `Développer (${childIds.length})`}
            </button>
          ) : (
            <span>Aucun descendant matérialisé</span>
          )}
          <label>
            <input
              checked={selected}
              disabled={comparisonDisabled}
              onChange={() => onCompare(node.node_id)}
              type="checkbox"
            />
            Comparer
          </label>
          <Link href={`/hypotheses/${node.node_id}`}>Fiche complète</Link>
        </div>
      </div>
    </article>
  );
}

function Comparator({
  nodes,
  onClear,
  onRemove,
}: {
  nodes: HypothesisTreeNode[];
  onClear: () => void;
  onRemove: (nodeId: string) => void;
}) {
  if (!nodes.length) return null;
  return (
    <section
      aria-label="Comparateur d’hypothèses"
      aria-live="polite"
      className="hu-comparator"
    >
      <div className="hu-comparator-head">
        <div>
          <p className="hu-kicker">Comparaison locale</p>
          <h2>
            {nodes.length} hypothèse{nodes.length > 1 ? "s" : ""} sélectionnée
            {nodes.length > 1 ? "s" : ""}
          </h2>
          <p>Sélectionnez entre deux et quatre branches pour les comparer.</p>
        </div>
        <button onClick={onClear} type="button">
          Vider
        </button>
      </div>
      <div className="hu-comparison-cards">
        {nodes.map((node, index) => {
          const parent = nodes.find((candidate) =>
            node.parent_ids.includes(candidate.node_id),
          );
          return (
            <article key={node.node_id}>
              <div>
                <span>Hypothèse {index + 1}</span>
                <button
                  aria-label={`Retirer ${node.display_rule_fr}`}
                  onClick={() => onRemove(node.node_id)}
                  type="button"
                >
                  ×
                </button>
              </div>
              <h3>{node.display_rule_fr}</h3>
              <dl>
                <div>
                  <dt>Famille</dt>
                  <dd>{familyDisplayName(node.family)}</dd>
                </div>
                <div>
                  <dt>Profondeur</dt>
                  <dd>{nodeDepth(node)}</dd>
                </div>
                <div>
                  <dt>Support</dt>
                  <dd>
                    {node.support == null
                      ? "Non disponible"
                      : formatNumber(node.support)}
                  </dd>
                </div>
                <div>
                  <dt>Résultat historique</dt>
                  <dd>
                    {node.historical_metrics == null
                      ? "Non disponible"
                      : "Disponible dans le contrat"}
                  </dd>
                </div>
                <div>
                  <dt>Résultat prospectif</dt>
                  <dd>
                    {node.prospective_metrics == null
                      ? "Aucune observation"
                      : "Disponible dans le contrat"}
                  </dd>
                </div>
                <div>
                  <dt>Statut</dt>
                  <dd>{scientificStatusLabel(node.materialization_disposition)}</dd>
                </div>
                <div>
                  <dt>Données requises</dt>
                  <dd>{node.data_gates.map(scientificStatusLabel).join(", ")}</dd>
                </div>
              </dl>
              <p className="hu-added-condition">
                <strong>
                  {parent ? "Ce que l’enfant ajoute" : "Condition distinctive"}
                </strong>
                {lastCondition(node)}
              </p>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function HypothesisTreeExplorer({
  initialCutoff = "",
  initialDepth = "",
  initialFamily = "",
  initialHideBlocked = false,
  initialLayout = "",
  initialMarket = "",
  initialOnlyLongTail = false,
  initialQuery = "",
  initialStatus = "",
  initialTreeId,
}: {
  initialCutoff?: string;
  initialDepth?: string;
  initialFamily?: string;
  initialHideBlocked?: boolean;
  initialLayout?: string;
  initialMarket?: string;
  initialOnlyLongTail?: boolean;
  initialQuery?: string;
  initialStatus?: string;
  initialTreeId?: string;
}) {
  const { mode } = useViewMode();
  const initialNodes = useMemo(
    () =>
      Object.fromEntries(
        hypothesisTree.roots.map((node) => [node.node_id, node]),
      ),
    [],
  );
  const [nodes, setNodes] =
    useState<Record<string, HypothesisTreeNode>>(initialNodes);
  const [expandedIds, setExpandedIds] = useState<string[]>([]);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [layout, setLayout] = useState<TreeLayout>(() =>
    normalizeInitialLayout(initialLayout),
  );
  const [family, setFamily] = useState<FacetSelection>(() =>
    normalizeInitialFamily(initialFamily),
  );
  const [status, setStatus] = useState<FacetSelection>(() =>
    normalizeInitialFacet(initialStatus, statusOptions),
  );
  const [cutoff, setCutoff] = useState<FacetSelection>(() =>
    normalizeInitialFacet(initialCutoff, cutoffOptions),
  );
  const [market, setMarket] = useState<FacetSelection>(() =>
    normalizeInitialFacet(initialMarket, marketOptions),
  );
  const [depth, setDepth] = useState<FacetSelection>(() =>
    normalizeInitialDepth(initialDepth),
  );
  const [hideBlocked, setHideBlocked] = useState(initialHideBlocked);
  const [onlyLongTail, setOnlyLongTail] = useState(initialOnlyLongTail);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadedPageCount, setLoadedPageCount] = useState(0);
  const [understoodFilters, setUnderstoodFilters] = useState<
    UnderstoodFilter[]
  >([]);
  const [collectionWindow, setCollectionWindow] = useState({
    limit: collectionBatchSize,
    signature: "",
  });
  const pagePromises = useRef(
    new Map<number, Promise<HypothesisTreeNode[]>>(),
  );
  const loadedPages = useRef(new Set<number>());
  const loadPage = useCallback(async (page: number) => {
    const existing = pagePromises.current.get(page);
    if (existing) return existing;
    const descriptor = hypothesisNodePages.find(
      (candidate) => candidate.page === page,
    );
    if (!descriptor) return [];
    const promise = (async () => {
      try {
        const response = await fetch(descriptor.url);
        if (!response.ok) throw new Error(`PAGE_${page}_UNAVAILABLE`);
        const payload = (await response.json()) as NodePage;
        const items = payload.items;
        setNodes((current) => {
          const next = { ...current };
          for (const node of items) next[node.node_id] = node;
          return next;
        });
        loadedPages.current.add(page);
        setLoadedPageCount(loadedPages.current.size);
        return items;
      } catch {
        pagePromises.current.delete(page);
        setLoadError(
          "Une page de branches n’a pas pu être chargée. Les résultats affichés sont incomplets.",
        );
        return [];
      }
    })();
    pagePromises.current.set(page, promise);
    return promise;
  }, []);

  const ensureNodes = useCallback(
    async (nodeIds: string[]) => {
      const pages = Array.from(
        new Set(
          nodeIds
            .map((nodeId) => hypothesisNodeLocator[nodeId])
            .filter((page): page is number => typeof page === "number"),
        ),
      );
      setLoadError(null);
      setLoading(true);
      try {
        await Promise.all(pages.map(loadPage));
      } finally {
        setLoading(false);
      }
    },
    [loadPage],
  );

  const loadAllMaterialized = useCallback(async () => {
    setLoadError(null);
    setLoading(true);
    try {
      await Promise.all(
        hypothesisNodePages.map((descriptor) => loadPage(descriptor.page)),
      );
    } finally {
      setLoading(false);
    }
  }, [loadPage]);

  useEffect(() => {
    const url = new URL(window.location.href);
    const setOrDelete = (name: string, value: string, emptyValue = "ALL") => {
      if (!value || value === emptyValue) url.searchParams.delete(name);
      else url.searchParams.set(name, value);
    };

    setOrDelete(
      "famille",
      family === "ALL" ? "" : familySlug(family),
      "",
    );
    setOrDelete("statut", status);
    setOrDelete("cutoff", cutoff);
    setOrDelete("marche", market);
    setOrDelete("profondeur", depth);
    setOrDelete("vue", layout, "arbre");
    if (onlyLongTail) url.searchParams.set("longue-traine", "1");
    else url.searchParams.delete("longue-traine");
    if (hideBlocked) url.searchParams.set("sans-bloquees", "1");
    else url.searchParams.delete("sans-bloquees");

    [
      "depth",
      "disposition",
      "family",
      "layout",
      "longTail",
      "market",
      "status",
    ].forEach((alias) => url.searchParams.delete(alias));
    window.history.replaceState(
      window.history.state,
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  }, [
    cutoff,
    depth,
    family,
    hideBlocked,
    layout,
    market,
    onlyLongTail,
    status,
  ]);

  const needsMaterializedPages =
    family !== "ALL" ||
    status !== "ALL" ||
    cutoff !== "ALL" ||
    market !== "ALL" ||
    depth !== "ALL" ||
    hideBlocked ||
    onlyLongTail ||
    layout !== "arbre" ||
    understoodFilters.length > 0;

  useEffect(() => {
    if (!needsMaterializedPages || !hypothesisNodePages.length) return;
    if (loadedPages.current.size === hypothesisNodePages.length) return;
    void loadAllMaterialized();
  }, [loadAllMaterialized, needsMaterializedPages]);

  useEffect(() => {
    if (!initialTreeId || nodes[initialTreeId]) return;
    void Promise.resolve().then(() => ensureNodes([initialTreeId]));
  }, [ensureNodes, initialTreeId, nodes]);

  const onNaturalFilters = useCallback(
    (filters: UnderstoodFilter[]) => {
      setUnderstoodFilters(filters);
    },
    [],
  );

  const toggleNode = useCallback(
    async (node: HypothesisTreeNode) => {
      const isExpanded = expandedIds.includes(node.node_id);
      if (isExpanded) {
        setExpandedIds((current) =>
          current.filter((nodeId) => nodeId !== node.node_id),
        );
        return;
      }
      const childIds = hypothesisChildrenByParent[node.node_id] ?? [];
      await ensureNodes(childIds);
      setExpandedIds((current) => [...current, node.node_id]);
    },
    [ensureNodes, expandedIds],
  );

  const toggleCompare = (nodeId: string) => {
    setCompareIds((current) =>
      current.includes(nodeId)
        ? current.filter((candidate) => candidate !== nodeId)
        : current.length < 4
          ? [...current, nodeId]
          : current,
    );
  };

  const filteredNodes = useMemo(
    () =>
      Object.values(nodes).filter((node) => {
        if (family !== "ALL" && node.family !== family) return false;
        if (
          status !== "ALL" &&
          node.materialization_disposition !== status &&
          node.status !== status
        ) {
          return false;
        }
        if (cutoff !== "ALL" && nodeCutoff(node) !== cutoff) return false;
        if (market !== "ALL" && nodeMarket(node) !== market) return false;
        if (depth !== "ALL" && nodeDepth(node) !== Number(depth)) return false;
        if (
          hideBlocked &&
          (node.materialization_disposition === "DATA_GATE_BLOCKED" ||
            node.data_gates.includes("DATA_GATE_BLOCKED"))
        ) {
          return false;
        }
        if (
          onlyLongTail &&
          node.materialization_disposition !== "LONG_TAIL_WATCHLIST"
        ) {
          return false;
        }
        return nodeMatchesUnderstoodFilters(node, understoodFilters);
      }),
    [
      cutoff,
      depth,
      family,
      hideBlocked,
      market,
      nodes,
      onlyLongTail,
      status,
      understoodFilters,
    ],
  );
  const collectionSignature = [
    cutoff,
    depth,
    family,
    hideBlocked ? "sans-bloquees" : "",
    layout,
    market,
    onlyLongTail ? "longue-traine" : "",
    status,
    ...understoodFilters.map(
      (filter) =>
        `${filter.segment}:${filter.operator}:${filter.field}:${filter.value}`,
    ),
  ].join("|");
  const collectionLimit =
    collectionWindow.signature === collectionSignature
      ? collectionWindow.limit
      : collectionBatchSize;
  const visibleCollectionNodes = filteredNodes.slice(0, collectionLimit);
  const filteredIds = useMemo(
    () => new Set(filteredNodes.map((node) => node.node_id)),
    [filteredNodes],
  );

  const nodeOrDescendantMatches = useMemo(() => {
    const matches = (
      nodeId: string,
      visited = new Set<string>(),
    ): boolean => {
      if (visited.has(nodeId)) return false;
      if (filteredIds.has(nodeId)) return true;
      const nextVisited = new Set(visited).add(nodeId);
      return (hypothesisChildrenByParent[nodeId] ?? []).some((childId) =>
        matches(childId, nextVisited),
      );
    };
    return matches;
  }, [filteredIds]);

  const requestedRoots = useMemo(() => {
    if (initialTreeId && nodes[initialTreeId]) return [nodes[initialTreeId]];
    return hypothesisTree.roots.filter((root) =>
      nodeOrDescendantMatches(root.node_id),
    );
  }, [initialTreeId, nodeOrDescendantMatches, nodes]);

  const renderBranch = (
    node: HypothesisTreeNode,
    depth: number,
    path: Set<string>,
  ): ReactNode => {
    if (!nodeOrDescendantMatches(node.node_id)) return null;
    const expanded = expandedIds.includes(node.node_id);
    const childIds = hypothesisChildrenByParent[node.node_id] ?? [];
    const nextPath = new Set(path).add(node.node_id);
    return (
      <li key={`${node.node_id}-${depth}`}>
        <NodeCard
          compareIds={compareIds}
          expanded={expanded}
          layout={layout}
          node={node}
          onCompare={toggleCompare}
          onToggle={toggleNode}
        />
        {expanded && childIds.length ? (
          <ul>
            {childIds.map((childId) => {
              const child = nodes[childId];
              if (!child || nextPath.has(childId)) return null;
              return renderBranch(child, depth + 1, nextPath);
            })}
          </ul>
        ) : null}
      </li>
    );
  };

  const comparedNodes = compareIds
    .map((nodeId) => nodes[nodeId])
    .filter((node): node is HypothesisTreeNode => Boolean(node));
  const resetFacets = () => {
    setFamily("ALL");
    setStatus("ALL");
    setCutoff("ALL");
    setMarket("ALL");
    setDepth("ALL");
    setHideBlocked(false);
    setOnlyLongTail(false);
    setLayout("arbre");
  };
  const hasExplicitFacet =
    family !== "ALL" ||
    status !== "ALL" ||
    cutoff !== "ALL" ||
    market !== "ALL" ||
    depth !== "ALL" ||
    hideBlocked ||
    onlyLongTail ||
    layout !== "arbre";
  const activeViewParts = [
    family === "ALL"
      ? "toutes les familles"
      : familyDisplayName(family),
  ];
  if (status !== "ALL") {
    activeViewParts.push(`ET état ${scientificStatusLabel(status)}`);
  }
  if (cutoff !== "ALL") {
    activeViewParts.push(
      `ET heure limite ${cutoffLabels[cutoff] ?? cutoff}`,
    );
  }
  if (market !== "ALL") {
    activeViewParts.push(`ET marché ${marketLabels[market] ?? market}`);
  }
  if (depth !== "ALL") {
    activeViewParts.push(`ET profondeur ${depth}`);
  }
  if (hideBlocked) activeViewParts.push("SAUF branches bloquées");
  if (onlyLongTail) activeViewParts.push("ET longue traîne");
  activeViewParts.push(
    ...understoodFilters.map(
      (filter) => `${filter.operator} ${filter.label}`,
    ),
  );

  return (
    <div className="hu-page hu-tree-page">
      <HypothesisBreadcrumbs
        items={[
          { href: "/robin-live", label: "Accueil" },
          { href: "/hypotheses", label: "Hypothèses" },
          { label: "Arbres" },
        ]}
      />
      <HypothesisSubnav />
      <header className="hu-page-header">
        <div>
          <p className="hu-kicker">Exploration sélective de l’arbre</p>
          <h1>Les arbres d’hypothèses</h1>
          <p>
            Ouvrez une branche, voyez la condition ajoutée et comparez-la à son
            parent. Les pages de nœuds sont chargées uniquement à la demande.
          </p>
        </div>
        <div className="hu-header-stats">
          <UniverseMetric
            detail="dans le pilote borné"
            label="Nœuds matérialisés"
            tone="teal"
            value={hypothesisTree.node_count}
          />
          <UniverseMetric
            detail={`${hypothesisTree.page_size} maximum par page`}
            label="Pages chargées"
            tone="blue"
            value={`${loadedPageCount}/${hypothesisNodePages.length}`}
          />
        </div>
      </header>

      <NaturalLanguageFilter
        initialQuery={initialQuery}
        onChange={onNaturalFilters}
      />

      {loadError ? (
        <div className="hu-load-error" role="alert">
          <div>
            <strong>Chargement incomplet</strong>
            <p>{loadError}</p>
          </div>
          <button onClick={() => void loadAllMaterialized()} type="button">
            Réessayer
          </button>
        </div>
      ) : null}

      <section className="hu-tree-toolbar" aria-label="Filtres de l’arbre">
        <div className="hu-advanced-facets">
          <label>
            Famille
            <select
              aria-label="Famille"
              onChange={(event) => setFamily(event.target.value)}
              value={family}
            >
              <option value="ALL">Toutes les familles</option>
              {familyOptions.map((item) => (
                <option key={item.family} value={item.family}>
                  {item.display_name_fr} ·{" "}
                  {formatNumber(hypothesisFacets.families[item.family])} propriétés
                </option>
              ))}
            </select>
          </label>
          <label>
            État matériel
            <select
              aria-label="État matériel"
              onChange={(event) => setStatus(event.target.value)}
              value={status}
            >
              <option value="ALL">Tous les états</option>
              {statusOptions.map((value) => (
                <option key={value} value={value}>
                  {scientificStatusLabel(value)} ·{" "}
                  {formatNumber(hypothesisFacets.statuses[value])}
                </option>
              ))}
            </select>
          </label>
          <label>
            Heure limite
            <select
              aria-label="Heure limite"
              onChange={(event) => setCutoff(event.target.value)}
              value={cutoff}
            >
              <option value="ALL">Toutes les heures limites</option>
              {cutoffOptions.map((value) => (
                <option key={value} value={value}>
                  {cutoffLabels[value] ?? value}
                </option>
              ))}
            </select>
          </label>
          <label>
            Marché
            <select
              aria-label="Marché"
              onChange={(event) => setMarket(event.target.value)}
              value={market}
            >
              <option value="ALL">Tous les marchés</option>
              {marketOptions.map((value) => (
                <option key={value} value={value}>
                  {marketLabels[value] ?? value}
                </option>
              ))}
            </select>
          </label>
          <label>
            Profondeur
            <select
              aria-label="Profondeur"
              onChange={(event) => setDepth(event.target.value)}
              value={depth}
            >
              <option value="ALL">Toutes les profondeurs</option>
              {depthOptions.map((value) => (
                <option key={value} value={String(value)}>
                  {value === 1 ? "1 · racine" : `${value} · niveau ${value}`}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="hu-tree-options">
          <label className="hu-check-control">
            <input
              checked={hideBlocked}
              onChange={(event) => setHideBlocked(event.target.checked)}
              type="checkbox"
            />
            Masquer les branches bloquées
          </label>
          <label className="hu-check-control">
            <input
              checked={onlyLongTail}
              onChange={(event) => setOnlyLongTail(event.target.checked)}
              type="checkbox"
            />
            Afficher seulement la longue traîne
          </label>
          <button
            disabled={!hasExplicitFacet}
            onClick={resetFacets}
            type="button"
          >
            Réinitialiser les facettes
          </button>
        </div>
        <div
          className="hu-layout-switch"
          role="group"
          aria-label="Présentation"
        >
          {(["arbre", "graphe", "liste"] as const).map((value) => (
            <button
              aria-pressed={layout === value}
              key={value}
              onClick={() => setLayout(value)}
              type="button"
            >
              Vue {value}
            </button>
          ))}
        </div>
      </section>

      <p className="hu-filter-sentence">
        <strong>Vue active :</strong> {activeViewParts.join(" ")}.
      </p>

      <div className={`hu-tree-canvas hu-tree-canvas-${layout}`}>
        <div className="hu-tree-canvas-head">
          <span aria-live="polite" role="status">
            {formatNumber(filteredNodes.length)} nœuds chargés correspondent
            {layout === "arbre"
              ? ""
              : ` · ${formatNumber(visibleCollectionNodes.length)} affichés`}
          </span>
          <button
            disabled={
              loading || loadedPageCount === hypothesisNodePages.length
            }
            onClick={() => void loadAllMaterialized()}
            type="button"
          >
            {loading
              ? "Chargement…"
              : loadedPageCount === hypothesisNodePages.length
                ? "Tous les nœuds sont chargés"
                : "Charger les nœuds matérialisés"}
          </button>
        </div>
        {layout === "arbre" ? (
          requestedRoots.length ? (
            <ul className="hu-tree-roots">
              {requestedRoots.map((root) => renderBranch(root, 0, new Set()))}
            </ul>
          ) : loading ? (
            <p className="hu-loading" role="status">
              Recherche dans les pages matérialisées…
            </p>
          ) : (
            <HonestEmptyState title="Aucune racine ne correspond encore">
              Chargez les nœuds matérialisés ou élargissez les filtres. Robin
              ne crée pas de branche pour remplir cet espace.
            </HonestEmptyState>
          )
        ) : filteredNodes.length ? (
          <>
            <div className={`hu-node-collection hu-node-collection-${layout}`}>
              {visibleCollectionNodes.map((node) => (
                <NodeCard
                  compareIds={compareIds}
                  expanded={expandedIds.includes(node.node_id)}
                  key={node.node_id}
                  layout={layout}
                  node={node}
                  onCompare={toggleCompare}
                  onToggle={toggleNode}
                />
              ))}
            </div>
            {visibleCollectionNodes.length < filteredNodes.length ? (
              <button
                className="hu-progressive-load"
                onClick={() =>
                  setCollectionWindow({
                    limit: collectionLimit + collectionBatchSize,
                    signature: collectionSignature,
                  })
                }
                type="button"
              >
                Afficher davantage de branches
                <span>
                  {formatNumber(visibleCollectionNodes.length)} sur{" "}
                  {formatNumber(filteredNodes.length)}
                </span>
              </button>
            ) : null}
          </>
        ) : loading ? (
          <p className="hu-loading" role="status">
            Recherche dans les pages matérialisées…
          </p>
        ) : (
          <HonestEmptyState title="Aucun nœud ne correspond">
            Les filtres actifs ne rencontrent aucune branche chargée. Modifiez
            la phrase ou consultez une autre famille.
          </HonestEmptyState>
        )}
      </div>

      <Comparator
        nodes={comparedNodes}
        onClear={() => setCompareIds([])}
        onRemove={toggleCompare}
      />

      <section className="hu-section hu-surface">
        <UniverseSectionHeading
          eyebrow={`Vue ${mode === "discovery" ? "Découverte" : mode === "analysis" ? "Analyse" : "Expert"}`}
          title="Comment lire un nœud"
        />
        <div className="hu-tree-legend">
          <p>
            <strong>Condition ajoutée</strong>
            La différence précise entre une branche et son parent.
          </p>
          <p>
            <strong>Support</strong>
            Le nombre de matchs observés lorsque cette valeur est disponible.
          </p>
          <p>
            <strong>Disponibilité</strong>
            La preuve temporelle nécessaire pour utiliser la branche sans
            réécrire le passé.
          </p>
          <p>
            <strong>Statut scientifique</strong>
            Une branche testée peut rester exploratoire et non validée.
          </p>
        </div>
      </section>

      {family !== "ALL" ? (
        <Link
          className="hu-secondary-action"
          href={`/hypotheses/familles/${familySlug(family)}`}
        >
          Retour à la famille
        </Link>
      ) : null}
    </div>
  );
}
