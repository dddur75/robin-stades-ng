# Next Mission Brief — E2 targeted fixes and E3A V1

## Configuration

```text
OUTIL = Codex
DÉPÔT = dddur75/robin-stades-ng
BRANCHE D’ACCUEIL VISIBLE = codex/hypothesis-universe-experience-v1
PR À REVOIR = #34
BRANCHE À REVOIR = codex/p0-e2-capability-sample-v1
MODÈLE = GPT-5.6 Sol
RAISONNEMENT = Très élevé
ACCÈS = Complet
DURÉE = 20 à 50 heures utiles
```

Cette mission est préparée mais n'a pas été exécutée.

## Point de départ autoritatif

E2 a mesuré 100 fixtures réelles, 20 par ligue, sur le run GitHub Actions
`31192408221`. Le coût est de 161 GET et 6 434 224 octets. Le replay et la
réconciliation hors réseau sont byte-identiques.

```text
selection_hash = 5f0ad80ce5ae43b4b4010c0e06dff8828330bcd60282bf940c9f1e87e601286b
E1A = 3036 = 2681 + 206 + 149
ABSENCE_CAUSE_EXACT = STOPPED_LOCAL_CAMPAIGN
E3A executed = false
masks built = false
```

Contrat autoritatif :
`configs/data/capability-scoped-evidence-ladder-v2.json`.

Revoir la PR #34, ses rapports, ses claims, son head exact et sa CI. La fusionner
par merge commit uniquement si elle reste saine, puis vérifier la CI de `main`.

## Correctifs ciblés obligatoires

1. `PLAYER_STATISTICS` : expliquer et corriger, sans attribution inventée, la
   seule divergence Liga de la fixture `1208603`, strate 6, objet signé
   `2a106520004fcd3945b821db8130f2a671ad8ef7d17b83c8077fc495338c7135`.
   L'état E2 reste 4 208 reçues / 4 209 attendues, 1 `UNKNOWN`, 1 invalide tant
   qu'une preuve distincte ne le résout pas.
2. `CALENDAR` : définir une preuve `KNOWN_AS_OF` qui n'utilise pas l'état final
   post-match comme preuve de disponibilité pré-match.

Toute nouvelle lecture R2 exige un manifeste exact-key, une décision append-only,
un budget borné et la revue DP6/C2/DP5. Aucun fallback fournisseur ou SQL.

## Capacités candidates E3A

```text
TEAM
PLAYER
LINEUP
FORMATION
EVENTS
TEAM_STATISTICS
DISCIPLINE_GENERIC
```

Exécuter E3A seulement pour les capacités dont le grain, la temporalité et les
dépendances sont explicitement admissibles. `PLAYER_STATISTICS` et `CALENDAR`
ne rejoignent E3A qu'après leur correctif ciblé et une nouvelle décision.

## Bornes

- ne lancer ni E1A ni une troisième architecture, et ne pas reclasser les 149
  `ABSENCE_CAUSE_UNKNOWN` ;
- ne déclarer aucune readiness globale à partir de l'échantillon E2 ;
- ne pas exécuter E3B/E4 ;
- ne pas construire de masque, propriété, paire ou triple avant un verdict E3A ;
- ne pas appeler API-Football, Odds ou SQL ;
- ne pas écrire dans R2 ;
- ne pas déployer, publier, parier ou promouvoir ;
- maximum deux tentatives techniques au même périmètre.

## Fin attendue

Publier les correctifs E2 prouvés, exécuter un E3A borné pour les seules capacités
admissibles, recalculer les gates locales, produire coûts et replay, puis rendre
`PASS_AND_HOLD` ou `PARTIAL_AND_HOLD`. S'arrêter avant E3B et avant les masques.
