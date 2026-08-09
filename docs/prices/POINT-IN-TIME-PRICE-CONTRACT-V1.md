# Contrat Point-in-Time Price V1

La capture V1 est limitée à `MATCH_RESULT_90M` et
`TOTAL_GOALS_2_5_90M`. Elle interroge explicitement les cinq clés françaises
`betclic_fr`, `netbet_fr`, `pmu_fr`, `unibet_fr` et `winamax_fr`. Aucun livre
absent n'est remplacé ; l'état devient `NO_PRICE`.

Le contrat est activé uniquement en mode `CANARY_ONLY`. Il ne peut pas ouvrir
la campagne V3, la recherche de triples, une promotion ou une mise réelle.

Chaque observation conserve le bookmaker, la région, le marché, la sélection,
la ligne, la cote source, le reçu, le hash du payload brut et les quatre heures
de provenance. `known_at` est l'heure de réception Robin, pas `last_update` du
fournisseur. L'égalité au cutoff est admise par le contrat known-at.

`provider_updated_at` (le `last_update` du bookmaker) est obligatoire pour
admettre scientifiquement un prix. Son absence, son ancienneté au-delà de la
borne du cutoff (H24/H6 3 600 s, H2 1 800 s, near-kickoff 600 s), ou une date
future par rapport à `known_at` exclut le prix sans substitution.

Une ligne 1X2 exige HOME/DRAW/AWAY dans un même reçu et un même bookmaker. Un
total exige OVER/UNDER sur la ligne exacte 2,5. Chaque couple attendu
bookmaker-marché manquant produit un événement DQ append-only `NO_PRICE` ;
l'absence n'est donc jamais silencieuse.

La couche dérivée ne remplace jamais la cote source. Elle calcule la probabilité
implicite, l'overround signé et un devig proportionnel par bookmaker, puis la
médiane inter-bookmaker des probabilités et une renormalisation. Un marché
n'est dérivé que si son overround est strictement positif et au plus égal à
6 %. Le meilleur prix est descriptif et n'entre pas dans le consensus.

Le consensus confirmatoire n'est vrai que pour les cinq bookmakers exacts. Sa
projection agrégée est matérialisée pour un consommateur futur, mais aucun
consommateur V3 n'est activé par Chronos V1.

Documentation fournisseur primaire :

- https://the-odds-api.com/liveapi/guides/v4/
- https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
