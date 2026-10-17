# Mission 028 — deux calendriers argentins complémentaires

La population figée contient 204 matchs argentins de 2023 et 203 de 2024 qui ne
figurent pas dans les calendriers du championnat API-Football 128. Ils relèvent
principalement de la Copa de la Liga Profesional, compétition distincte chez le
fournisseur. La population, ses dates, ses scores et son empreinte ne changent pas.

Le plan conserve les 198 requêtes originales et ajoute uniquement
`/fixtures?league=1032&season=2023` et `season=2024`, avant de relire les archives.
Le plafond de la phase reste de 200 requêtes distinctes ; les réservations et
reçus existants empêchent de rappeler les 198 calendriers achevés.

Sources d’identification : [couverture officielle API-Football](https://www.api-football.com/coverage)
et [page du championnat GiBiScore, fournisseur API-Football et identifiant 1032 dans le chemin](https://www.gibiscore.com/competitions/copa-de-la-liga-profesional-argentina-1032).
L’identifiant doit ensuite être confirmé par la réponse : ligue et saison
identiques à la requête, date à ± 1 jour, deux noms d’équipes canoniques et score
final identiques à la ligne Football-Data. Aucun rapprochement approximatif.

La table conserve l’identifiant réel du fournisseur (128 ou 1032). Le dossier
Parquet logique reste `competition=ARG` ; ses lignes portent la compétition
API-Football effective. La phase 2 doit accepter 1032 uniquement pour ARG en
2023 et 2024. Toutes les autres exclusions et réserves restent identiques.
