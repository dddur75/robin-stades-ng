# Couverture du cumul livré

Claim : `DATA.CLV202627.CUMUL.V1`. Statut **PARTIAL** : tous les rapports
normalisés récupérables ont été traités ; l'exhaustivité du stock durable R2
n'est pas établie et un match contradictoire est exclu.

- Base : `main` à `92a4ee192fce946e3d81461ce2825e5dd3122b1c`, après la PR #119.
- Inventaire GitHub en lecture seule : 9 562 artefacts retournés, rétention
  visible remontant au 27 juillet 2026. Parmi eux, 270 `robin-autonomous-lab-*`
  contiennent `robin-real-data.json`, du 4 au 19 octobre. Tous ont été téléchargés.
  Chaque JSON correspond au SHA-256 `normalized_json_sha256` de son reçu public
  (270/270). Identifiants, hashes ZIP/JSON/reçu : `ARTIFACTS.json`.
- Les copies des 4 octobre reprennent les observations du 3 octobre dès
  20:53:57 UTC. Les copies/reprises sont incluses ; la sélection du moteur ne
  crée qu'une ligne par match/issue/book/horizon, indépendamment des répétitions.
- Les 144 artefacts `prospective-odds-capture-*` du 28 juillet au 9 août ont tous
  été inspectés : fichiers estimate/report uniquement, zéro `capture_attempts`
  et zéro `observatory.captures.by_family.ODDS.captured`. Aucun snapshot à charger.
- Aucun `odds-snapshots.jsonl` réel suivi dans le dépôt ou présent dans ces
  artefacts. Le magasin prévu est `data/shadow/**/odds-snapshots.jsonl` ;
  `data/shadow-demo` est une démonstration et reste exclu.
- Le run source `37153158456` du 3 octobre retourne zéro artefact. Son reçu
  suivi indique un rapport privé durable dans R2. Les copies normalisées reprises
  sont exploitables, mais aucun accès R2 n'est configuré dans cet environnement
  pour vérifier qu'elles couvrent toutes les captures, notamment celles du pilote
  antérieur. Aucun état local d'explorateur supplémentaire n'est disponible.
- Borne explicite : 19 octobre 2026 inclus. Les matchs sont groupés par coup
  d'envoi UTC, avec toutes les observations antérieures disponibles, y compris
  celles capturées plusieurs jours avant. Aucun jour sans match n'est inventé.

## Résultat et exclusions

95 matchs FR exploitables sur 8 jours ; 3 141 lignes, dont 2 691 CLV calculables
et 450 `MISSING_HORIZON` (14,327 %). Une ligne late=True, CLV +21,877 % ;
1 134 late non calculables (champ vide). Aucun autre statut manquant dans ce lot.
Les CSV détaillés permettent de vérifier ces comptes et les horaires réels.

Lorient–AS Monaco (`f4453043-b24d-5183-a459-7f369be4453b`) apparaît au
18 octobre à 13:15 UTC et à 15:15 UTC dans les sources. Les 253 snapshots
correspondants sont exclus du calcul, sans privilégier la version majoritaire.
`EXCLUSIONS.csv` garde les deux horaires et le motif. Les CSV du 18 restent
présents pour les autres matchs. Aucune correction rétroactive n'a été faite.

| Jour UTC | Matchs avec book FR | Lignes | CLV calculables |
|---|---:|---:|---:|
| 2026-10-09 | 3 | 81 | 81 |
| 2026-10-10 | 24 | 639 | 639 |
| 2026-10-11 | 17 | 594 | 489 |
| 2026-10-12 | 4 | 144 | 132 |
| 2026-10-16 | 4 | 144 | 144 |
| 2026-10-17 | 21 | 747 | 546 |
| 2026-10-18 | 18 | 648 | 552 |
| 2026-10-19 | 4 | 144 | 108 |

Les tests synthétiques prouvent les calculs, les fenêtres, le dénominateur,
l'exclusion des contradictions et la reproduction à l'octet. Une vérification
séparée des CSV réels confirme unicité des clés, formule price×fair−1 et
n/moyennes des résumés quotidiens. Les IC de Student restent descriptifs ; les
95 matchs ne constituent pas 2 691 observations indépendantes.

Aucun appel fournisseur, achat, pari réel, accès Neon/R2, dispatch, changement de
scheduler, de configuration existante ou de données sources. La revue indépendante
et la fusion restent à la charge de Qualité ; cette livraison ne les déclare pas acquises.
