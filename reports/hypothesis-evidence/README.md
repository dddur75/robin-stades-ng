# Preuves historiques Jalon 10

Ce dossier versionne uniquement les contrats, les schémas, les hashes et les
rapports compacts de la reconstruction cache-only. Les lignes détaillées ne
sont pas suivies par Git.

## Source gelée

- révision historique logique : `5c85cf20b932df44dca8665de00e52e3f1e02236` ;
- arbre Parquet : `986010a776cb7c0f4948098660febea9577f159e` ;
- hash du dataset : `3197b6cbe13dcbc4e851ad83550f4fed0741812df5eb4c386b2a52236a27d495` ;
- registre des 700 règles :
  `cb928f00340f64893e90cc40aaed9bd4ba22e4ef39d59e5f66994dd79331d731` ;
- résultat de campagne :
  `edd5f84a84ebbe63fdfeaea0451478fc3baf3387265a9831b620fd6ef0f8194b`.

Les révisions `518cb4b708b214f550e38c519d1226a0d34f1e38` et
`4678a30a72bc1cbe138508c4f5881275d97e9b47` contiennent une réplique
octet-identique du même arbre Parquet. Elles ne remplacent pas la révision
logique de campagne.

## Contrat de stockage

La reconstruction produit trois Parquet normalisés dans un répertoire
d’artefacts ignoré :

1. `historical_fixture_evidence` — une rencontre historique source, identifiée
   sans ambiguïté et reliée à son hash de ligne ;
2. `hypothesis_fixture_membership` — une appartenance sparse entre une règle
   J10 et une rencontre strictement éligible ;
3. `hypothesis_historical_evidence_summary` — un résumé réconcilié par règle.

Les clés, grains et champs exacts sont publiés par
`robin.hypothesis_evidence.schema_contract()`. Le manifeste compact Git
référence chaque artefact par son nombre de lignes, sa taille et son SHA-256.
Les appartenances détaillées, les lignes fournisseur et les payloads bruts ne
sont jamais copiés dans PostgreSQL ni dans un JSON suivi par Git.

La projection PostgreSQL de cette PR est limitée aux agrégats et aux index
d’artefacts nécessaires à la recherche et à la pagination. La migration est
testée sur une base temporaire ; aucune écriture PostgreSQL live n’est
effectuée. Les Parquet détaillés restent destinés à R2 après fusion, mais cette
mission effectue zéro écriture R2.

## Temporalité des prix

Le dataset porte `SOURCE_PRICE_CLASS_ONLY`. Il documente une classe de prix
historique (closing ou pre-closing), sans horodatage intrajournalier exact. La
reconstruction ne doit donc revendiquer ni cote observée à une minute précise,
ni CLV, ni disponibilité prouvée à H-2. Cette limite est conservée dans chaque
appartenance et dans les rapports publics.

## Reprise et publication

Le calcul est segmenté par lots et acquitte un checkpoint déterministe après
chaque lot. Une reprise vérifie les hashes d’entrée et les lots déjà produits
avant de continuer. Toute divergence de source, de registre, de replay ou des
trois résultats autoritatifs provoque un arrêt fail-closed avant publication
des lignes détaillées.

Budgets de cette PR :

```text
API_FOOTBALL_CALLS = 0
ODDS_API_CREDITS = 0
PAID_WEATHER_CALLS = 0
R2_WRITES = 0
POSTGRESQL_LIVE_WRITES = 0
```
