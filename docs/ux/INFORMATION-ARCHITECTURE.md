# Architecture de l’information — Robin Experience V1

## Principe

L’architecture suit une règle : comprendre avant d’explorer, explorer avant d’analyser, analyser avant d’opérer.

```text
Accueil
├── situation actuelle
├── prochaine capture
├── depuis la dernière visite
├── rencontres suivies
├── hypothèses
└── garanties
Matchs
├── recherche, filtres, tri, liste/calendrier
└── fiche match
    ├── Synthèse
    ├── Cotes
    ├── Équipes
    ├── Joueurs
    ├── Absences
    ├── Composition
    ├── Tactique
    ├── Chronologie
    └── Données et preuves
Observatoire
├── indicateurs
├── prochaines captures
├── matrice de couverture
├── gates
└── fournisseurs / stockage résumés
Laboratoire
├── huit hypothèses
└── progression de recherche
Résultats
├── recherche historique
├── tests prospectifs
├── décisions shadow
└── résultats réglés
Méthode
├── Observer → Vérifier → Tester → Publier → Suivre
├── NO BET, pertes et limites
└── glossaire
Espace Expert
├── Données et qualité
├── Modèles
├── Simulations historiques
├── Coûts et quotas
└── Système
```

## Routes publiques

| Route | Rôle | Réponse attendue en moins de dix secondes |
|---|---|---|
| `/robin-live` | meilleure entrée publique | 9 matchs sont suivis ; 18 preuves existent ; aucune mise réelle ; prochaine capture le 31 juillet |
| `/matchs` | explorer les rencontres | quelles équipes, quelles données, quelle couverture et quand la prochaine capture |
| `/matchs/[id]` | comprendre une rencontre | ce qui est observé, absent, attendu, tardif et prouvé |
| `/observatoire` | suivre la collecte | où en sont les 441 fenêtres actives, les familles et les gates |
| `/laboratoire` | comprendre la recherche | quelle question est étudiée, quelles données manquent et pourquoi elle attend |
| `/resultats` | consulter sans ambiguïté | aucune décision simulée pour le moment ; bankroll fictive inchangée |
| `/methode` | comprendre les garanties | aucune promesse, aucune mise, preuve temporelle et publication des pertes |
| `/expert` | vérifier les détails | données, modèles, coûts, workflows, invariants et provenance |
| `/` | compatibilité | rend la même expérience que l’accueil public |

## Progressive disclosure

La Vue essentielle est la valeur serveur et le défaut local. Elle montre la situation, les explications et les actions de lecture. La Vue expert révèle les codes, timestamps UTC, révisions, hashes, provenance, stockage, modèles et tableaux. Le changement de vue est enregistré sous `robin-experience-view-mode` dans le stockage local et ne touche aucune donnée métier.

## Personas et parcours

### Visiteur

`Accueil → Pourquoi aucun pari ? → Méthode → Résultats`

Le jargon n’est pas nécessaire. Les garanties sont visibles sans ouvrir Expert.

### Passionné

`Matchs → filtre équipe/date → fiche → Cotes/Composition/Tactique`

Chaque absence de donnée est formulée ; aucune cote individuelle n’est inventée.

### Analyste

`Vue expert → fiche Données et preuves → Laboratoire → Expert/Modèles`

Les hashes, cutoffs, métriques et provenance apparaissent après une action explicite.

### Opérateur

`Vue expert → Observatoire → Expert/Système ou Coûts`

Les invariants restent visibles et les contrôles opérationnels sont séparés du récit public.

## Navigation responsive

- Desktop : rail latéral de 258 px, espace Expert repliable, en-tête sticky.
- Tablette : rail retiré, en-tête compact, navigation inférieure lorsque nécessaire.
- Smartphone : barre inférieure à six destinations, cartes empilées, tableaux ou matrices convertis.
- Le glossaire et le sélecteur de vue restent toujours disponibles.

## Mapping des anciennes vues

| Nouvelle destination | Anciennes vues regroupées |
|---|---|
| Accueil | Robin Live, Command Center, état prospectif, alertes |
| Matchs | Match Center, Odds Explorer, Player Explorer, Lineup Explorer |
| Observatoire | Coverage Explorer, Observatoire prospectif, états des fenêtres |
| Laboratoire | Matchup Lab, Feature Lab public, Strategy Lab public |
| Résultats | Shadow Performance, décisions, bankroll, résultats publiables |
| Méthode | garanties, limites, vocabulaire, preuve |
| Expert / Données | Data Explorer, Dataset Readiness, Historical Data Quality, Pipeline |
| Expert / Modèles | Model Lab, Model Arena, External Validation |
| Expert / Simulations | Backtest Explorer, campagnes, contrôles négatifs |
| Expert / Coûts | budgets fournisseurs, appels, réserves |
| Expert / Système | Deep Data Center, Backfill, Market & Storage, R2, PostgreSQL, workflows |
