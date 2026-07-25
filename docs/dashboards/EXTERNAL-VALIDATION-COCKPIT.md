# Cockpit External Validation

Le Cockpit ajoute une page dédiée qui lit uniquement le snapshot serveur
sanitisé. Elle affiche :

- External Readiness et les cinq gates par compétition ;
- League Transfer Matrix ;
- Leave-One-League-Out ;
- Player Generalization ;
- Strategy External Validation ;
- Preseason Package avec `NO_BET_DEFAULT`, `REAL_BETS=false` et
  `PRODUCTION_LOCKED`.

Les statuts de publication restent distincts :

```text
COCKPIT_BUILD_SUCCESS
COCKPIT_ARTIFACT_PUBLISHED
COCKPIT_PRIVATE_STALE ou COCKPIT_PRIVATE_DEPLOYED
```

GitHub Actions ne prétend jamais déployer le site privé. Le redéploiement privé
est effectué séparément avec Sites, sans exposer PostgreSQL ni aucun secret au
navigateur.
