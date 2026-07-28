# Matrice de capacité des fournisseurs prospectifs

Cette matrice décrit ce que les intégrations réelles savent observer. Elle ne
transforme pas une réponse vide en absence certaine.
L'horodatage de preuve reste l'horodatage HTTP local
`requested_at`/`response_received_at`; aucun horodatage fournisseur n'est
actuellement mappé dans le reçu canonique.

| Famille | Fournisseur et endpoint réel | Donnée effectivement observable | Horodatage fournisseur | Réponse vide |
|---|---|---|---|---|
| `FIXTURE` | API-Football, `/fixtures` avec `id` | identité, kickoff UTC, statut et score courant de la fixture | `fixture.timestamp` décrit le kickoff, pas l'observation ; horodatage fournisseur absent/non mappé | non légitime pour une fixture active connue : conserver la preuve vide, échouer identité/couverture |
| `TEAM` | API-Football, `/fixtures` avec `id` | identités domicile/extérieur attachées à la fixture ; pas une fiche équipe complète | absent/non mappé | non légitime si l'identité de la fixture est attendue |
| `SQUAD` | API-Football, `/players/squads` avec `team`, une requête par équipe | effectif déclaré pour chaque côté | absent/non mappé | invalide si un côté ou ses joueurs manquent ; jamais interprété comme « aucun joueur » |
| `PLAYER_STATUS` | API-Football, `/injuries` avec `fixture` | projection des indisponibilités signalées, pas un statut exhaustif de tous les joueurs | absent/non mappé | `CAPTURED_EMPTY` admissible comme réponse vide, sans satisfaire à lui seul le gate joueur |
| `INJURY` | API-Football, `/injuries` avec `fixture` | blessures/suspensions publiées pour la fixture | absent/non mappé | `CAPTURED_EMPTY` est la preuve bornée `NO_INJURY_REPORTED_AT_CAPTURE`, pas une garantie médicale d'absence |
| `LINEUP` | API-Football, `/fixtures/lineups` avec `fixture` | onze, remplaçants et métadonnées publiées | absent/non mappé | légitime avant publication ; `CAPTURED_EMPTY` bloque le gate de couverture |
| `FORMATION` | API-Football, `/fixtures/lineups` avec `fixture` | formation dérivée de la même réponse lineup | absent/non mappé | légitime avant publication ; aucune formation ne doit être imputée |
| `EVENT_STATUS` | API-Football, `/fixtures` avec `id` | statut fournisseur au moment de la réponse | `fixture.timestamp` n'est pas un horodatage de statut ; absent/non mappé | seul `NS` est admis ; tout autre statut produit `REGISTRY_STALE` |
| `ODDS` | The Odds API, `/v4/sports/{sport}/odds` (`h2h`, `totals`) | événements, bookmakers, marchés 1X2 et O/U 2,5 | `last_update` peut exister dans le payload mais reste non mappé au reçu ; la réception HTTP fait foi | légitime si aucun bookmaker/marché n'est publié pour la fixture correctement appariée |

## Mutualisation et identité

- `FIXTURE`, `TEAM` et `EVENT_STATUS` partagent une réponse `/fixtures`.
- `PLAYER_STATUS` et `INJURY` partagent une réponse `/injuries`.
- `LINEUP` et `FORMATION` partagent une réponse `/fixtures/lineups`.
- `SQUAD` nécessite deux appels, domicile puis extérieur.
- une requête Odds est globale à une cohorte et peut mutualiser plusieurs
  fixtures ; l'appariement exige équipes et kickoff cohérents avant admission.

Une réponse partagée ne devient pas plusieurs captures physiques. Pour
API-Football, `physical_capture_id` inclut la fixture mais mutualise les
familles issues de la même réponse fixture-scoped. Pour `/sports/.../odds`,
la fixture est neutralisée : une réponse globale multi-fixtures conserve un
seul identifiant physique. Le ledger publie ensuite au plus une preuve
temporelle par identifiant physique et fixture.

## Activation par compétition

| Compétition | API-Football | The Odds API | Profil |
|---|---:|---|---|
| Ligue 1 | 61 | `soccer_france_ligue_one` | `FULL` |
| Premier League | 39 | `soccer_epl` | `DEEP_FULL_ODDS_REDUCED` |
| Liga | 140 | `soccer_spain_la_liga` | `DEEP_FULL_ODDS_REDUCED` |
| Bundesliga | 78 | `soccer_germany_bundesliga` | `DEEP_FULL_ODDS_REDUCED` |
| Serie A | 135 | `soccer_italy_serie_a` | `DEEP_FULL_ODDS_REDUCED` |

La présence d’un mapping ne suffit pas à rendre la ligue active. Fixtures,
identités, kickoffs, R2, PostgreSQL, replay et budget doivent tous être verts.

Toute valeur sans identité, kickoff fiable, horodatage de réception ou réponse
HTTP vérifiable est rejetée. `CAPTURED_EMPTY` est une preuve de réponse vide,
pas une donnée imputée à zéro.

La sélection due est revérifiée avant tout preflight et transport, puis
`response_received_at` est comparé au cutoff. Une réponse de fenêtre n’est
temporellement admissible que dans
`opens_at <= response_received_at < cutoff_at < kickoff_at`.
