# Rapport d'audit — Jalon 2

Date : 2026-07-24  
Branche : `codex/jalon-2-shadow-data`  
Statut produit : `PARTIAL`  
Statut shadow : `SHADOW_INFRASTRUCTURE_READY`  
Paris réels : `PRODUCTION_LOCKED`

## Résultat

Le Jalon 1 a été vérifié puis fusionné par squash. Le Jalon 2 installe une chaîne
prospective Ligue 1 entièrement testable : adaptateurs fournisseurs, neuf
fenêtres de collecte, payloads et snapshots append-only, contrôles qualité,
prédictions simples horodatées, journal des décisions et règlement shadow.

La migration non destructive a examiné 36 423 lignes et produit 37 024 mappings.
La couverture certaine atteint 98,668 %, sans collision, ambiguïté ou non-résolu.
Les 493 correspondances `PROBABLE` restent exclues par défaut des usages
exigeant une identité certaine.

## Validation statistique

Le walk-forward 2025–2026 inclut baselines, marge, contraintes de bankroll,
drawdown, intervalles à 95 % et sensibilité des seuils. Aucune stratégie n'est
promue. L'Over 2,5 affiche +2,83 % sur 396 paris, mais son intervalle
`[-8,00 % ; +13,66 %]` rend le résultat inconclusif.

## Cockpit et exploitation

Le Cockpit V1 expose six vues et sépare strictement `DEMO DATA`,
`LEGACY SOURCE` et `LIVE SOURCE`. Cinq workflows planifiés sont idempotents,
verrouillés par concurrence, exécutables manuellement et publient leurs artefacts
même en échec.

Déploiement privé :
`https://robin-stades-shadow-cockpit.dddur.chatgpt.site`.

## Limites honnêtes

- aucune période prospective suffisante n'existe encore ;
- aucun snapshot réel n'est présenté dans l'artefact local ;
- l'adaptateur API-Football reste en `READY_NO_KEY` ;
- aucune stratégie, prédiction ou cote ne peut autoriser un pari réel.

Ces limites n'empêchent pas la vérification de l'infrastructure Jalon 2 ; elles
conditionnent le prochain jalon d'accumulation prospective.
