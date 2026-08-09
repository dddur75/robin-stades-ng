# Contrat Point-in-Time Price V1

La capture V1 est limitée à `MATCH_RESULT_90M` et
`TOTAL_GOALS_2_5_90M`. Elle interroge explicitement les cinq clés françaises
`betclic_fr`, `netbet_fr`, `pmu_fr`, `unibet_fr` et `winamax_fr`. Aucun livre
absent n'est remplacé; l'état devient `NO_PRICE`.

Chaque observation conserve le bookmaker, la région, le marché, la sélection,
la ligne, la cote source, le reçu, le hash du payload brut et les quatre heures
de provenance. `known_at` est l'heure de réception Robin, pas `last_update` du
fournisseur. L'égalité au cutoff est admise par le contrat known-at.

Une ligne 1X2 exige HOME/DRAW/AWAY dans un même reçu et un même bookmaker. Un
total exige OVER/UNDER sur la ligne exacte 2,5. Les marchés incomplets restent
auditables mais ne sont pas confirmatoires.

La couche dérivée ne remplace jamais la cote source. Elle calcule la probabilité
implicite, l'overround signé et un devig proportionnel par bookmaker, puis la
médiane inter-bookmaker des probabilités et une renormalisation. Le meilleur
prix est descriptif et n'entre pas dans le consensus.

Documentation fournisseur primaire :

- https://the-odds-api.com/liveapi/guides/v4/
- https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
