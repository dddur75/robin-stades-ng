# Prévision de coûts Jalon 4

## Recommandation

Utiliser Neon PostgreSQL. Le plan Free démarre à 0 USD, sans limite de temps,
avec 0,5 Go, 100 CU-heures par projet et restauration sur 6 heures. Pour une
petite base intermittente d’environ 1 Go, le plan Launch est estimé autour de
15 USD/mois et étend la restauration à 7 jours.

## Comparaison

| Option | Entrée de gamme | Limite déterminante | Décision |
|---|---:|---|---|
| Neon Free | 0 USD | 0,5 Go | recommandé pour démarrer |
| Neon Launch | ≈15 USD/mois à petite charge | facturation à l’usage | recommandé si >0,5 Go |
| Supabase Free | 0 USD | 0,5 Go, pause possible | non retenu pour burn-in continu |
| Supabase Pro | dès 25 USD/mois | coût fixe supérieur | alternative |
| Render Free | 0 USD | base expirée après 30 jours | rejeté |
| `shadow-data` | 0 € | pont Git, pas une base requêtable | transitoire |

## Volume

Hypothèse : 306 matchs × 9 fenêtres × 90 cotes ≈ 248 000 cotes, plus payloads
bruts, index, runs et contrôles. Fourchette prudente : 0,4 à 0,8 Go par saison.

## Quota sportif

The Odds API : 8 crédits consommés, 19 992 restants, prévision 720/mois,
plafond opérationnel 1 000 et réserve 4 000. Les scénarios à 2 compétitions,
5 compétitions ou 4 marchés restent informatifs et ne sont pas activés.

Aucun achat n’a été effectué.
