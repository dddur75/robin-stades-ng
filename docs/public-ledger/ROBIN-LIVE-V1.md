# Robin Live V1

Version : `robin-live-v1`

Robin Live est une vue statique du Public Evidence Ledger. Il ne lit jamais
Neon ou R2 depuis le navigateur.

## Sections

### Aujourd’hui

Matchs analysés, décisions shadow, `NO BET`, heure de publication, justification
courte et disponibilité des données.

### Résultats

Décisions gagnées, perdues ou void, profit et historique complet. Une décision
et son règlement restent deux événements distincts.

### Bankroll

Bankroll initiale de 1 000 unités, valeur courante, profit, ROI, drawdown et
courbe issus uniquement du ledger audité.

### Stratégies

Patterns en recherche, candidats, shadow et rejetés avec statut, version,
support et raison.

### Laboratoire

Nombre total d’hypothèses, résultats bruts, correction FDR, walk-forward,
contrôles négatifs et limites temporelles.

### Méthodologie

Explication du backtest, du corpus exposé, du shadow, de l’incertitude et de la
publication obligatoire des pertes et `NO BET`.

## États techniques distincts

```text
ROBIN_LIVE_BUILD_SUCCESS
ROBIN_LIVE_ARTIFACT_PUBLISHED
ROBIN_LIVE_PRIVATE_DEPLOYED
```

Un artefact construit n’est pas présenté comme déployé. Le build échoue si la
chaîne de hashes est invalide ou si une donnée démo est étiquetée réelle.

## État initial honnête

Tant que la campagne réelle et le gate live ne produisent aucun candidat,
Robin Live affiche zéro pari, zéro règlement et une bankroll shadow inchangée.
Des fixtures synthétiques ne sont autorisées que dans les tests et portent une
étiquette explicite.

Le bandeau permanent affiche :

```text
PRODUCTION_LOCKED
REAL_BETS=false
SOCIAL_PUBLISHING_ENABLED=false
AUCUNE GARANTIE
```
