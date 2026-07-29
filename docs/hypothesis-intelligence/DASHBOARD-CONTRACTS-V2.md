# Contrats du futur dashboard

Les contrats publics stables se trouvent sous
`reports/hypothesis-genome/` :

- `hypothesis-universe-summary.json` ;
- `hypothesis-family-catalog.json` ;
- `hypothesis-tags-catalog.json` ;
- `hypothesis-facets.json` ;
- `hypothesis-tree-root-index.json` ;
- `hypothesis-family-tree-index.json` ;
- `hypothesis-global-rankings.json` ;
- `hypothesis-rankings-by-competition.json` ;
- `hypothesis-rankings-by-family.json` ;
- `hypothesis-status-funnel.json` ;
- `hypothesis-live-activity.json` ;
- `hypothesis-glossary-fr.json` ;
- `manifest.json`.

Les pages de nœuds détaillées sont générées par pages de 50 sous
`artifacts/hypothesis-genome/hypothesis-tree-node-pages/`. Elles ne sont pas
versionnées dans Git.

Les libellés publics sont français. Les termes techniques historiques restent
dans la Vue Expert. Les vues séparent :

- meilleur signal historique brut ;
- priorité exploratoire ;
- observation prospective ;
- stratégie validée.

`strategies_validees` reste vide tant qu'aucune décision scientifique manuelle
et prospective n'existe.
