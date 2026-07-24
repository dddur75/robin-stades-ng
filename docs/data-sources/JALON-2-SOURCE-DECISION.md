# Jalon 2 — Décision de sources

Date de revue : 2026-07-24  
Périmètre : Ligue 1, collecte prospective shadow, sans souscription nouvelle.

## Décision

- données sportives profondes : **API-Football**, intégration prête mais non
  activée tant que `API_FOOTBALL_KEY` est absent ;
- fixtures, résultats courts et cotes prospectives actives :
  **The Odds API**, déjà autorisée par le secret `ODDS_API_KEY` ;
- contrôle historique : **Football-Data.co.uk**, sans en faire une source
  prospective horodatée ;
- alternative premium non retenue : **Sportmonks**, meilleure profondeur mais
  abonnement payant après essai.

Cette combinaison permet de commencer sans dépense. The Odds API fournit les
identifiants d'événements, horaires, scores récents et snapshots de marché. Le
manque de joueurs, compositions et blessures reste visible jusqu'à l'activation
d'API-Football.

## Méthode

Scores de 1 à 5. Pondérations : fiabilité 25 %, capacité prospective 20 %,
horodatage 15 %, couverture utile 10 %, stabilité 10 %, coût 8 %, intégration
5 %, conditions d'usage/archivage 7 %.

### Données sportives

| Fournisseur | Fiabilité | Prospectif | Horodatage | Couverture | Stabilité | Coût | Intégration | Conditions | Score / 5 | Décision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| API-Football | 4 | 5 | 4 | 5 | 4 | 5 | 4 | 3 | 4,25 | principal faisable |
| Sportmonks | 5 | 5 | 5 | 5 | 5 | 2 | 4 | 4 | 4,60 | écarté : dépense |
| football-data.org | 4 | 3 | 3 | 3 | 5 | 5 | 5 | 3 | 3,70 | secondaire possible |
| Football-Data.co.uk | 3 | 1 | 1 | 3 | 4 | 5 | 5 | 2 | 2,55 | contrôle historique |

API-Football annonce une formule gratuite à 100 requêtes/jour et l'accès à
l'ensemble des endpoints/compétitions sur les formules payantes. Les réponses
exposent les quotas journaliers et par minute.  
Source : https://api-sports.io/sports/football et
https://api-sports.io/documentation/football/v3

football-data.org couvre la Ligue 1. Sa formule gratuite inclut 12 compétitions,
10 appels/minute, calendriers, fixtures et classements, mais avec scores et
calendriers retardés.  
Source : https://www.football-data.org/pricing et
https://www.football-data.org/coverage

Sportmonks commence à 29 € par mois pour cinq ligues, après un essai de 14 jours,
avec fixtures, événements, statistiques, lineups, joueurs, blessures et
suspensions.  
Source : https://www.sportmonks.com/football-api/plans-pricing/

### Données de marché

| Fournisseur | Fiabilité | Prospectif | Horodatage | Marchés | Stabilité | Coût | Intégration | Conditions | Score / 5 | Décision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| The Odds API | 4 | 5 | 5 | 3 | 5 | 5 | 5 | 4 | 4,48 | principal |
| API-Football odds | 3 | 4 | 3 | 4 | 4 | 5 | 4 | 3 | 3,65 | contrôle futur |
| football-data.org odds | 3 | 2 | 2 | 2 | 4 | 2 | 4 | 3 | 2,75 | non retenu |
| Football-Data.co.uk | 3 | 1 | 1 | 3 | 4 | 5 | 5 | 2 | 2,55 | historique seulement |

The Odds API couvre la Ligue 1 et plus de 40 bookmakers. Le plan gratuit offre
500 crédits/mois. Le coût d'un appel est le nombre de marchés multiplié par le
nombre de régions ; les headers retournent crédits utilisés, restants et coût du
dernier appel. Les marchés groupés fiables retenus sont `h2h` et `totals`.
Double chance et BTTS restent désactivés au lieu d'être inventés.  
Source : https://the-odds-api.com/ et
https://the-odds-api.com/liveapi/guides/v4/

Les marchés principaux sont actualisés environ toutes les 60 secondes avant
match. Le projet collecte beaucoup moins souvent afin de respecter la valeur
réelle des fenêtres et le quota.  
Source : https://the-odds-api.com/sports-odds-data/update-intervals.html

## Risques et règles

- les identifiants The Odds API peuvent changer après un report important ;
- les événements reflètent ce que les bookmakers ont ouvert, pas un calendrier
  officiel exhaustif ;
- les historiques The Odds API sont payants et ne sont pas utilisés ;
- les réponses brutes sont archivées, mais aucune redistribution publique du
  payload n'est autorisée par défaut ;
- une absence d'endpoint est `ABSENT`, une panne est `ERROR` ;
- aucune donnée demo ne porte le badge `LIVE SOURCE`.

## Valeur d'une future clé API-Football

Elle débloquera référentiels structurés, joueurs, lineups, événements,
statistiques, blessures et suspensions pour la Ligue 1. L'adaptateur, les tests,
les quotas et le secret attendu `API_FOOTBALL_KEY` sont déjà préparés. Cette clé
n'est pas indispensable au démarrage des snapshots de cotes.
