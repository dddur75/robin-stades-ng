# Robin des Stades 2.0 — Data Source Strategy V1

Date de décision initiale : 14 août 2026
Convergence PR57/PR58 validée : 15 août 2026

Base immuable auditée : `6cb8de636890959bd2ddb7e1c791a2eb04ee8763`
Main intégré : `72e6cd625f7668fdcc095e63a847b6e7e9cf860f`
Manifest de convergence : `269f4066b13e88f4397aecd6f1a3d7ba154dc8468415581ce0f6b8922f1537b4`

Statut : inventaire et recommandation uniquement — aucune source activée

## Décision

Robin ne possède pas aujourd'hui de corpus historique source **receipt-backed** qui permette un replay scientifique point-in-time. Le dépôt contient des résultats, des cotes historiques agrégées, des features reconstruites, des manifests et des hashes utiles ; il ne contient toutefois aucun reçu source historique observé, aucune surface strictement point-in-time prouvée sur 72, ni aucun des 15 résultats historiques rejouable à partir d'entrées immuables connues avant le cutoff.

La priorité prospective unique est désormais :

> **Conserver en `DESIGN_ONLY` le pilote `ROBIN_FIRST_RECEIPT_BACKED_CAPTURE_PILOT_V1` : Ligue 1, deux journées, 18 fixtures maximum, 5 canaris, 75 appels HTTP dont 73 facturables et 88 crédits maximum.**

Cette mission ne l'active pas. Aucun secret, appel authentifié, achat, abonnement, base de production, R2, workflow live ou code Robin n'a été utilisé ou modifié.

## Autorité de convergence PR57 × PR56

Le calcul canonique n'est plus « journées × fenêtres ». L'ordonnanceur part de chaque `fixture_id`, de son `kickoff_at` UTC et des fenêtres admissibles par rôle. Deux captures ne sont mutualisées que si le `sport_key`, les marchés, la région et toutes les bornes de staleness restent compatibles, sans jamais fournir une TARGET à un chemin PREDICTOR.

Résultats reproduits par `tools/data-sourcing/recalculate_convergence.py` :

- 25 protocoles PR57 mappés exactement une fois ; classes A/B/C/D = `8/11/5/1` ;
- 335 exigences fixture-fenêtre ramenées à 227 appels compatibles ; 108 appels et crédits évités ;
- `0/25` expérience exécutable aujourd'hui ; aucune expérience exécutée, promue ou qualifiée profitable ;
- H24 reste PREDICTOR avec 120 minutes de staleness maximale ; H2 reste PREDICTOR ou TARGET distincte selon le protocole, avec 15 minutes maximum ; H1 reste TARGET lorsqu'elle est exigée ;
- EXP009 conserve seulement un design candidat `H24/H12/H6/H2` et reste bloquée par `EXP009_PROTOCOL_SUCCESSOR_REQUIRED_BEFORE_EXECUTION` ;
- le scénario S6 vaut 13 236 crédits/an et requiert une capacité mensuelle de référence de 1 986 crédits réserve comprise.

The Odds API v4 reste la Source 1 candidate, exclusivement sur `the-odds-api.com`. Le fournisseur signale `theoddsapi.com` sans tirets comme imposteur. La documentation officielle event-odds expose `bookmakers[].markets[].last_update`, donc la synchronisation est `MARKET_SYNCHRONIZATION_OBSERVABLE_DESIGN_ONLY` au grain bookmaker-marché ; sa couverture réelle h2h/totals doit encore être mesurée. `totals` reste `TOTALS_COVERAGE_TO_BE_PROVEN`.

Les conditions publiques autorisent des outils analytiques, interdisent la redistribution brute autonome et ne constituent pas une confirmation écrite de conservation indéfinie. Pour le seul pilote de recherche borné, `INTERNAL_MARKET_DATA_RETENTION_POLICY_V1` impose un stockage brut local non synchronisé, une TTL de 30 jours et la suppression automatisée, tout en enregistrant `NON_ZERO_BOUNDED_INTERNAL_DECISION`. Cette décision interne n'est pas une autorisation contractuelle explicite et n'autorise ni archive brute permanente ni saison complète. Les statuts restent `NOT_AUTHORIZED`, `NO_PROVIDER_CALL`, `NO_PURCHASE`, `NO_PROMOTION` et `NO_BET`.

## Pourquoi cette décision

Le manque le plus coûteux scientifiquement n'est pas le nombre de matchs. Robin possède déjà 36 423 matchs historiques dans `data/matches.parquet`. Le manque décisif est l'absence d'une preuve de ce que Robin pouvait réellement voir à un instant donné, en particulier pour les mouvements de marché :

- 0 reçu source historique observé ;
- 0 surface strictement point-in-time prouvée ou receipt-bounded sur 72 ;
- 0 résultat historique rejouable sur 15 résultats logiques et 45 occurrences physiques ;
- aucun corpus local de snapshots intraday ;
- un ledger de 86 événements dont les deux indicateurs de capture sont tous faux et dont le dernier snapshot est toujours nul ;
- des colonnes « opening » et « closing » utiles, mais sans heure exacte de collecte, publication ou première observation Robin.

Le volume historique reste scientifiquement de profil **B** pour des benchmarks descriptifs et des contrôles de robustesse, pas pour revendiquer une performance as-of sans fuite. Une source dont les droits de rétention/réutilisation ne sont pas prouvés reste néanmoins **D** jusqu'à clarification écrite : le veto juridique prévaut sur le profil temporel.

## Périmètre et méthode

L'inventaire couvre exhaustivement les fichiers suivis ayant une extension de données : 487 fichiers pour 38 125 043 octets. Ces fichiers sont regroupés par dataset logique dans [l'inventaire existant](../../reports/data-sourcing/existing-data-inventory-v1.json), afin de distinguer les octets locaux des références externes, des surfaces absentes et des artefacts perdus.

Les sources candidates sont séparées en produits logiques lorsque leurs garanties temporelles diffèrent : les cotes courantes et l'archive historique d'un même fournisseur n'appartiennent pas nécessairement à la même classe. Chaque candidat a exactement une classe :

- **A** : historique avec preuve de disponibilité point-in-time fiable ;
- **B** : historique utile, mais disponibilité temporelle non prouvable ;
- **C** : capture prospective pouvant recevoir un reçu complet après ses gates d'accès et de licence ;
- **D** : source redondante, interdite, juridiquement douteuse, indisponible ou disproportionnée.

La classe D est un hard gate fail-closed : `UNCLEAR`, `UNCLEAR_CONDITIONAL`, `HIGH_RISK_CONDITIONAL`, `PARTIAL`, restriction, interdiction ou contrat sur mesure non exécuté imposent D, quel que soit le score numérique. Le Top 5 ci-dessous exclut donc D.

Le score sur 100 additionne les neuf critères demandés. Une interdiction contractuelle ou l'absence d'accès légal constitue néanmoins un **veto** : une source D peut avoir une forte valeur technique sans devenir admissible. Les scores, maximums et justifications par critère sont reproductibles avec `tools/data-sourcing/source_inventory.py` et publiés dans le [scorecard](../../reports/data-sourcing/source-priority-scorecard-v1.json).

## Ce qui existe réellement dans le dépôt

| Dataset logique | Volume vérifié | Preuve disponible | Usage recevable |
|---|---:|---|---|
| `data/matches.parquet` | 36 423 matchs, 9 ligues, 11 saisons | Octets/hash locaux ; date événementielle seulement | Baseline historique B, jamais replay PIT |
| Mappings legacy | 37 024 mappings, 493 ambiguïtés | Octets/hash locaux | Aide d'identité ; les 493 `PROBABLE` restent en quarantaine |
| Ledger odds | 86 lignes | Aucun snapshot ; 0 crédit enregistré | Inutilisable comme preuve de capture |
| Exports `resultats_vague*` | 56 416 lignes dérivées | Octets locaux, sans reçus amont | Descriptif uniquement |
| Phase C V1 | 1 756 fixtures et features reconstruites | Tous les hashes gzip vérifiés | `RECONSTRUCTED_NOT_PROVEN` |
| Phase C V2 source | 1 756 fixtures, 3 512 team-fixtures | Intégrité vérifiée ; `point_in_time_source_provenance=false` | Schéma/recherche, pas preuve source |
| Shards Phase C V2 | 144 gzip, 9,23 Mo | Transport et contenu vérifiés | Reproduction de résultats, pas disponibilité |
| Références P0/selection/live-proof | objets, hashes et coordonnées externes | Bytes payload/reçus absents localement | `EXTERNAL_REFERENCE`, récupération séparément autorisée seulement |
| Surfaces PostgreSQL | 37 | Non observées | État inconnu ; aucune requête effectuée |
| Surfaces déclarées absentes | 8 | Absence vérifiée | À capturer prospectivement ou exclure |
| Pack LOOP55 antérieur | perdu/écrasé | Hashes logiques insuffisants | Non récupérable byte-for-byte |

L'intégrité locale est bonne sans être une preuve temporelle : les 157 fichiers JSON.GZ suivis passent la vérification de leurs hashes de transport et de contenu applicables. Inversement, le sidecar de `cockpit/app/cockpit-data.json` ne correspond ni aux octets physiques ni au contenu du blob Git. Ce défaut est consigné, mais le cockpit est protégé et n'a pas été modifié.

## Couverture et limites de `data/matches.parquet`

Le Parquet principal couvre `2015-07-31` à `2026-05-24`, les saisons `2015-16` à `2025-26`, et les ligues `D1`, `E0`, `E1`, `F1`, `F2`, `I1`, `N1`, `P1`, `SP1`. Il possède 36 423 `match_id` distincts et aucune duplication exacte.

Sa couverture n'est pas uniforme :

- 34 674 lignes ont le triplet 1X2 d'ouverture complet ;
- 34 755 ont le triplet 1X2 de clôture complet ;
- 21 168 ont le O/U 2,5 d'ouverture complet ;
- 21 211 ont le O/U 2,5 de clôture complet ;
- 26 172 arbitres sont manquants ;
- chaque colonne cartes/corners a 1 990 valeurs manquantes.

Surtout, aucune ligne ne porte `source_published_at`, `robin_first_observed_at`, `robin_ingested_at`, `available_at`, un hash de payload source ou un identifiant de reçu. La date sans fuseau n'autorise ni l'ordre intraday ni un cutoff exact.

## Résultat du marché des sources

### Top 5 global admissible

| Rang | Source | Classe | Score | Lecture |
|---:|---|:---:|---:|---|
| 1 | The Odds API — cotes courantes | C | 94 | Meilleur rapport valeur temporelle / marchés / coût / intégration |
| 2 | Sportmonks Premium Odds | C | 89 | Très riche mais minimum public estimé à 158 €/mois avec core |
| 3 | Open-Meteo prospective forecast | C | 87 | Excellente météo forecast-as-known, secondaire face aux cotes |
| 4 | Sportmonks Football core | C | 85 | Contexte football profond et droits contractuels plus lisibles |
| 5 | MET Norway Locationforecast | C | 84 | Météo prospective CC BY gratuite, secondaire face aux cotes |

### Top 3 historique

1. **Open-Meteo Single Runs archive — B, 84.** Les runs émis sont adressables, mais `run` signifie initialisation et les délais publiés ne sont que typiques : sans journal historique immuable de publication ni reçu Robin contemporain, la disponibilité stricte n'est pas prouvée. [Documentation officielle](https://open-meteo.com/en/docs/single-runs-api)
2. **The Odds API historical — B, 83.** Archive depuis le 6 juin 2020, snapshots de 10 minutes puis 5 minutes depuis septembre 2022, avec timestamp et pointeurs précédent/suivant. La documentation prévoit cependant la correction d'erreurs historiques : une réponse obtenue en 2026 ne prouve pas que ses octets étaient identiques en 2021. Accès payant, non activé. [Guide officiel](https://the-odds-api.com/liveapi/guides/v4/)
3. **Wikidata revisioned venue geography — A, 82.** Les IDs, octets de révision et timestamps CC0 permettent de reconstruire les assertions géographiques publiées, sous réserve de contrôler les lieux neutres. [Accès officiel](https://www.wikidata.org/wiki/Help:Data_access)

Football-Data.co.uk a un profil scientifique historique B (72) : long et familier à Robin, mais sans timestamp de disponibilité par ligne. Il est toutefois classé D par veto juridique tant qu'aucune permission écrite ne couvre la rétention et la réutilisation commerciales. Ses notes documentent les changements de bookmakers et le sens des colonnes ; elles ne transforment pas ces colonnes en snapshots as-of. [Données](https://www.football-data.co.uk/data.php) et [notes de champs](https://www.football-data.co.uk/notes.txt)

### Top 3 prospectif

1. **The Odds API current — C, 94.** [Marchés](https://the-odds-api.com/sports-odds-data/betting-markets.html), [fréquences indicatives](https://the-odds-api.com/sports-odds-data/update-intervals.html), [conditions](https://the-odds-api.com/terms-and-conditions.html).
2. **Sportmonks Premium Odds — C, 89.** Environ une minute, ouverture et changements, 120+ bookmakers/42 marchés en Pro, mais historique glissant limité à sept jours après kickoff et coût élevé. [Produit officiel](https://www.sportmonks.com/football-api/premium-odds-feed/)
3. **Open-Meteo prospective forecast — C, 87.** Forecasts explicites par modèle/run ; le free tier est non commercial et une utilisation commerciale exige un plan. [Conditions](https://open-meteo.com/en/terms)

Sportmonks core (C, 85) est le meilleur candidat contextuel admissible. API-Football aurait une forte valeur technique (85), mais reste D : ses conditions ne concèdent pas les droits de publication sous-jacents, donc un avis écrit est nécessaire avant tout corpus durable. football-data.org et NOAA restent également D jusqu'à clarification écrite de leurs droits de rétention/réutilisation. [Tarifs API-Football](https://www.api-football.com/pricing), [couverture](https://www.api-football.com/coverage), [conditions](https://www.api-football.com/terms)

### Sources exclues

- **Sportradar, Stats Perform/Opta, Betfair Historical** : excellente valeur technique, mais prix/contrats personnalisés ou achat préalable, donc disproportionnés/non autorisés ici.
- **Pinnacle** : accès public général fermé depuis le 23 juillet 2025 ; extraction non approuvée interdite. [Documentation officielle](https://github.com/pinnacleapi/pinnacleapi-documentation)
- **StatsBomb Open Data** : données événementielles/xG remarquables, mais l'accord public examiné interdit l'exploitation commerciale et restreint la fourniture/reproduction des données ou analyses dérivées ; classe D pour le corpus Robin. [Dépôt](https://github.com/hudl/open-data), [accord](https://github.com/hudl/open-data/blob/master/LICENSE.pdf)
- **FBref** : conditions Sports Reference incompatibles avec l'automatisation prédictive/scoring. [Conditions](https://www.sports-reference.com/termsofuse.html)
- **Transfermarkt** : bots, scraping et data mining interdits ; aucune extraction n'a été tentée. [Conditions](https://www.transfermarkt.com/intern/anb)
- **Meteostat** : contradiction officielle CC BY / CC BY-NC non résolue. [Licence](https://dev.meteostat.net/license), [FAQ](https://dev.meteostat.net/faq.html)
- **ClubElo** : licence de réutilisation et interface programmatique opérationnelle non prouvées ; Robin peut recalculer un Elo à partir de fixtures admises.

## Matrice des familles de données

| Famille | État historique recevable | Meilleure voie prospective | Décision |
|---|---|---|---|
| Fixtures/résultats | OpenFootball en B ; Football-Data.co.uk D juridique | Sportmonks avec reçus ; API-Football/football-data.org seulement après clearance écrite | Conserver le legacy comme benchmark ; capturer les mutations |
| 1X2 et O/U 2,5 | Opening/closing B, pas intraday | The Odds API current | Priorité 1 |
| DNB/double chance/BTTS/AH | Pas de corpus PIT local | Marchés additionnels The Odds API ou Sportmonks | Retarder après preuve sur `h2h,totals` |
| Opening/closing/intraday | Labels B uniquement | Captures J-7 à near-kickoff | Ne jamais rétro-dater |
| Dispersion/mouvements | Aucun snapshot local | Bookmakers et `last_update` The Odds API | Calculer seulement depuis raw+reçus admis |
| Classements/forme/repos | Dérivables des fixtures | Transformation cutoff-safe | Pas besoin d'une source séparée si résultats admis |
| Statistiques équipe/arbitres | Legacy partiel, disponibilité non prouvée | Sportmonks ; API-Football seulement après clearance écrite | Deuxième vague |
| xG | Pas de corpus local autorisé/reçu | Sportmonks xG ou fournisseur contractuel | Ne pas utiliser StatsBomb/FBref en production |
| Compositions | Références/sanitized non PIT | Sportmonks ; API-Football seulement après clearance écrite | Captures H-2 et near-kickoff après droits |
| Blessures/suspensions | Aucun flux public légal complet identifié | Fournisseur licencié | Gate juridique ; jamais Transfermarkt scraping |
| Entraîneurs | Partiel selon fournisseur | Sportmonks ; API-Football seulement après clearance écrite | Faible fréquence, secondaire |
| Voyage | Pas de corpus match-venue audité | Wikidata révisionné + overrides | Après la capture odds |
| Météo | Réanalyse non équivalente au forecast connu | Open-Meteo runs ou MET Norway | Après odds ; garder modèle/run et reçu |

OpenFootball constitue une bonne baseline CC0 pour fixtures/résultats mais reste B : un commit Git aide à rejouer une version, sans prouver quand chaque donnée était disponible avant un match. [Projet officiel](https://openfootball.github.io/)

MET Norway est la meilleure alternative météo gratuite si l'usage commercial doit être clair : données CC BY 4.0, usage commercial admis, User-Agent identifiant et cache obligatoires, sans SLA. [Service](https://api.met.no/) et [conditions](https://api.met.no/doc/TermsOfService)

## Deux micro-échantillons publics

Deux fichiers seulement ont été téléchargés, sans authentification et hors Git dans `ROBIN-DATA-RECOVERY-WORKSPACE/data-recovery-source-inventory-v1/samples/` :

| Source | HTTP | Octets | Lignes | SHA-256 | Première/dernière valeur événementielle |
|---|---:|---:|---:|---|---|
| Football-Data.co.uk F1 2025-26 | 200 | 158 471 | 306 | `898b7ddcd373cfe955ae353b1a98cf7f1c8757ca10b69d53039f4e098e88f192` | 2025-08-15 / 2026-05-17 |
| StatsBomb competitions | 200 | 34 887 | 80 | `e6cd42f5d8956d6aa30fb917ce8d4c3b3df1879a93f02f8feba820930a6971fa` | 2023-06-28 / 2026-05-15 (manifest publication fields) |

Les URLs, timestamps UTC, statuts, empreintes de schéma et notes de licence figurent dans l'[inventaire candidat](../../reports/data-sourcing/source-candidate-inventory-v1.json). L'échantillon StatsBomb confirme le schéma public ; ses conditions conduisent tout de même à l'exclusion D pour Robin.

## Contrat de reçu candidat

Chaque réponse future doit conserver les bytes bruts avant parsing et produire les champs suivants :

```text
source_name
source_url
request_identity
payload_sha256
source_published_at
robin_first_observed_at
robin_ingested_at
available_at
schema_fingerprint
capture_code_revision
licence_status
snapshot_candidate_id
```

Règles minimales :

- `request_identity` contient méthode, chemin et paramètres/headers non secrets canonisés ; jamais la clé API ;
- `payload_sha256` porte sur les octets exacts avant parsing ;
- `robin_first_observed_at` est fixé par une horloge Robin à la réception, jamais synthétisé rétroactivement ;
- `available_at = max(source_published_at fiable, robin_first_observed_at)` ; si la date source est absente/non fiable, la première observation Robin est la borne ;
- `robin_first_observed_at <= robin_ingested_at` ;
- une observation n'est admise que si `available_at <= feature_cutoff_at` ;
- toute valeur manquante ou incohérente échoue fermée ;
- une nouvelle réponse ne remplace jamais une ancienne : elle crée un nouveau `snapshot_candidate_id`.

La spécification complète se trouve dans le [rapport de gap temporel](../../reports/data-sourcing/temporal-evidence-gap-v1.json). Aucun code Robin n'a été modifié pour l'implémenter.

## Première capture recommandée

Le plan antérieur `648 appels / 1 296 crédits`, construit par multiplication de journées et de fenêtres, est conservé uniquement comme historique non canonique. Il ne doit plus piloter un quota ni une capture.

Le premier pilote futur est [spécifié](../../reports/data-sourcing/first-receipt-backed-capture-pilot-v1.json) mais non autorisé :

- Ligue 1, deux journées et 18 fixtures maximum, sans backfill ;
- cinq canaris h2h+totals ; h2h systématique, totals uniquement comme couverture à prouver ;
- fenêtres fixture-aware H24/H12/H6/H2/H1, sous réserve des successeurs scientifiques explicitement requis ;
- 75 appels HTTP planifiés, 73 facturables, 88 crédits maximum ;
- payload brut exact et SHA-256, `source_published_at` si disponible, `robin_first_observed_at`, `robin_ingested_at`, `available_at`, fingerprint de schéma, révision du code, `snapshot_id` et contrat de replay ;
- replay hors réseau byte-identique, mapping fixture déterministe, absence de fuite future et séparation stricte PREDICTOR/TARGET/LABEL.

Le pilote s'arrête notamment si la politique interne, sa TTL brute de 30 jours ou sa suppression automatisée ne peuvent être appliquées, si le mapping est ambigu, si le reçu ou le timestamp est insuffisant, si la couverture totals/bookmakers est trop faible, si le coût dépasse le modèle ou si un secret apparaît. Une autorisation propriétaire distincte restera nécessaire pour lancer le canari, puis une décision juridique séparée sera requise avant toute rétention brute permanente ou extension pleine saison.

## Ce que cette priorité remplace ou retarde

Elle remplace comme objectif de preuve :

- le ledger vide de 86 événements ;
- l'usage des labels opening/closing comme substitut à une heure observée ;
- toute tentative d'inférer un mouvement intraday depuis le Parquet legacy.

Elle retarde volontairement :

- l'achat de l'archive historique The Odds API ;
- Sportmonks Premium Odds ;
- l'extension DNB/double chance/BTTS/AH ;
- les blessures/compositions API-Football ;
- la météo prospective.

Elle ne répare pas rétroactivement le passé. Le premier `robin_first_observed_at` réel marquera le début du futur corpus recevable.

## Risques et objections

1. **Fuite rétrospective.** Match time, `lastUpdated`, model run, Git time et labels opening/closing ne sont pas des preuves interchangeables de disponibilité.
2. **Licence.** Football-Data.co.uk n'offre pas de grant commercial clair ; API-Football laisse les droits de compétition à l'utilisateur ; StatsBomb/FBref/Transfermarkt ont des restrictions décisives.
3. **Couverture dynamique.** Bookmakers et marchés peuvent disparaître ; le corpus doit conserver les absences et versions de schéma, pas seulement les succès.
4. **Horloges.** Une source future par rapport à l'horloge Robin doit être mise en quarantaine, jamais « corrigée » silencieusement.
5. **Identité.** Les noms d'équipes ne suffisent pas ; les 493 mappings `PROBABLE`, lieux neutres et changements de stade exigent une revue.
6. **Coût.** L'ancienne projection de 1 296 crédits/an est non canonique. Le scénario S6 canonique est borné à 13 236 crédits/an, avec une capacité mensuelle de 1 986 crédits réserve comprise ; le quota réel doit toujours être contrôlé par les en-têtes de chaque réponse.
7. **Artefacts externes.** Les références potentiellement expirantes nécessitent une autorisation séparée et une récupération payload+reçu, pas un simple téléchargement de hashes.

## Livrables et reproductibilité

Le verdict `DATA_HYPOTHESIS_CONVERGENCE_REPRODUCIBLE` qualifie la transformation déterministe des autorités Git épinglées et des faits publics datés vers huit rapports byte-identiques. Il ne prétend pas prouver l'immutabilité des octets des pages web officielles. Le SHA-256 du manifeste du pack externe est enregistré comme référence de mission ; ce pack reste volontairement hors Git et n'est donc pas reproductible depuis le seul dépôt.

- [Inventaire des données existantes](../../reports/data-sourcing/existing-data-inventory-v1.json)
- [Inventaire des 23 sources candidates](../../reports/data-sourcing/source-candidate-inventory-v1.json)
- [Scorecard reproductible](../../reports/data-sourcing/source-priority-scorecard-v1.json)
- [Gap temporel et contrat de reçu](../../reports/data-sourcing/temporal-evidence-gap-v1.json)
- [Priorité prospective unique](../../reports/data-sourcing/first-prospective-capture-recommendation-v1.json)
- [Convergence data × hypothèses](../../reports/data-sourcing/data-hypothesis-convergence-v1.json)
- [Matrice expériences × données × fenêtres](../../reports/data-sourcing/experiment-data-window-matrix-v1.json)
- [Plan de capture event-aware](../../reports/data-sourcing/event-aware-capture-plan-v1.json)
- [Scénarios de budget crédits](../../reports/data-sourcing/credit-budget-scenarios-v1.json)
- [Pilote receipt-backed](../../reports/data-sourcing/first-receipt-backed-capture-pilot-v1.json)
- [Expériences bloquées](../../reports/data-sourcing/blocked-experiments-v1.json)
- [Roadmap des gaps source](../../reports/data-sourcing/source-gap-roadmap-v1.json)
- [Hypothèses sur les sources officielles](../../reports/data-sourcing/official-source-assumptions-v1.json)
- `tools/data-sourcing/source_inventory.py` : validation/scoring déterministe et profilage de petits échantillons locaux, sans réseau
- `tools/data-sourcing/recalculate_convergence.py` : reconstruction déterministe des huit rapports de convergence, sans réseau
- `tests/data-sourcing/test_source_inventory.py` : tests ciblés de score, classes, dates et profils
- `tests/data-sourcing/test_convergence_contracts.py` : contrats fermés sur les rôles temporels, budgets, gates et effets externes nuls

La décision finale est volontairement étroite : **construire désormais la preuve temporelle sur deux marchés de cotes à haute valeur, avant d'élargir les familles de données ou d'acheter de l'historique.**
