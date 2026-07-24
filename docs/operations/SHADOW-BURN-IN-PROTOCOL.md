# Protocole de burn-in shadow

Statut : `SHADOW_BURN_IN_ACTIVE`. Production : `PRODUCTION_LOCKED`.

## Objectif

Observer la fiabilité prospective de la chaîne sur au moins 30 jours calendaires
avant tout jalon supplémentaire. Le burn-in couvre trois axes distincts :

- technique : workflows, stockage, replay, provenance, incidents ;
- couverture : fenêtres éligibles, marchés disponibles et collecte effective ;
- statistique : descriptive seulement, sans promotion ni conclusion de rendement.

## Cadence

- chaque run met à jour les métriques quotidiennes ;
- `daily-health.yml` produit les rapports quotidien, hebdomadaire et matchday ;
- une fenêtre planifiée peut être `COLLECTED`, `COLLECTED_LATE`,
  `NO_MARKET_AVAILABLE`, `PROVIDER_FAILED`, `SKIPPED_QUOTA` ou `PENDING` ;
- une collecte diagnostique hors fenêtre n’entre pas dans la couverture ;
- les rapports distinguent toujours legacy, OOS historique et live shadow.

## Critères de santé

Les cibles sont : ≥95 % de workflows réussis, ≥90 % des fenêtres éligibles
collectées, 100 % de provenance, ≥20 % de réserve quota, 0 perte silencieuse,
0 doublon non résolu, 0 fuite temporelle, 0 secret exposé et 0 donnée démo
présentée comme live.

Moins de trois runs ou aucune fenêtre éligible donne
`INSUFFICIENT_OBSERVATION`, pas `HEALTHY`.

## Alertes

Le journal append-only ouvre un seul incident par code. Une issue GitHub ne doit
être ouverte que pour un incident critique persistant après reprise, jamais pour
une absence normale de marché ni pour répéter la même alerte. Toute résolution
ajoute cause, impact, données concernées et correction.

## Interdiction statistique

ÉCHANTILLON INSUFFISANT — AUCUNE CONCLUSION STATISTIQUE.

Un burn-in vert ne déverrouille pas la production.
