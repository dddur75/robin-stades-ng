# Audit de l'écart courant

## Conclusion

Avant Hypothesis Intelligence Factory V1, le cockpit ne pouvait pas distinguer
une proposition de David d'une découverte machine. Le snapshot exposait
uniquement `owner_hypotheses`, tandis que le rapport J10 et son registre de
700 règles restaient des artefacts historiques isolés. Il n'existait ni registre
commun versionné, ni origine obligatoire, ni cycle prospectif attaché à une
hypothèse.

La chaîne précédente était donc :

`J10 isolé -> rapport agrégé -> aucune promotion -> cockpit propriétaire seul`

La chaîne corrigée est :

`découverte -> registre canonique -> classement explicable -> gel prospectif -> observation -> règlement -> ledger append-only -> cockpit`

## Preuves J10 conservées

- registre : 700 règles uniques ;
- support insuffisant : 167 ;
- rendement brut positif : 118 ;
- walk-forward brut positif : 24 ;
- survivants FDR : 0 ;
- survivants cross-ligue : 0 ;
- promotions shadow : 0 ;
- verdict : `NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE` ;
- hash du registre : `cb928f00340f64893e90cc40aaed9bd4ba22e4ef39d59e5f66994dd79331d731` ;
- hash du résultat : `edd5f84a84ebbe63fdfeaea0451478fc3baf3387265a9831b620fd6ef0f8194b`.

Le replay cache-only reproduit ces deux hashes, sans appel fournisseur, sans
crédit odds et sans doublon.

## Écarts fermés par V1

1. Les 700 règles J10 entrent dans un registre versionné avec origine
   `MACHINE_DISCOVERED`.
2. Les huit hypothèses H11 restent explicitement `OWNER_PROPOSED`.
3. Les statuts, transitions et événements sont auditables ; aucune validation
   automatique n'est permise.
4. Les trois meilleures découvertes machine sont gelées dans des contrats
   prospectifs séparés du classement historique.
5. Les observations, règlements et corrections sont idempotents et append-only.
6. Le cockpit sépare découvertes machine, hypothèses de David, observation
   prospective et éléments bloqués/rejetés.
7. Le mode Expert charge le registre par pages bornées de 50 entrées.

## Écarts volontairement non fermés

- aucune hypothèse n'est déclarée robuste ou validée ;
- aucune prédiction réelle n'est créée ;
- aucun règlement réel ni entraînement réel n'est exécuté ;
- aucun fournisseur n'est appelé ;
- aucun pari, réseau social ou déploiement n'est déclenché.
