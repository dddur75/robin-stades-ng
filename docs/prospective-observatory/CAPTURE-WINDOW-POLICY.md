# Politique des fenêtres de capture

Version active : `prospective-capture-window-v2` (Option B).

Source machine : `configs/prospective_observatory_v1.json`. Le document décrit
ce contrat ; le runtime doit refuser une divergence.

## Tolérance et consolidation Option B

Les fenêtres éloignées conservent la tolérance opérationnelle horaire. Les
fenêtres rapprochées ne se chevauchent plus :

```text
H-2          : [kickoff_at - 3 h, kickoff_at - 1 h)
NEAR_KICKOFF : [kickoff_at - 1 h, kickoff_at)
```

La borne de code de `NEAR_KICKOFF` est exactement
`kickoff_at - 1 µs`, car le modèle exige un cutoff strictement antérieur au
kickoff. Cette consolidation est l’Option B : un scheduler horaire ne prétend
plus produire des observations indépendantes à H-1, H-0:45, H-0:30 et H-0:15.
Une exécution horaire sélectionne les fixtures dues ; elle ne transforme pas
GitHub Actions en boucle.

## Fixtures et statut général

```text
J-21
J-14
J-7
J-3
J-1
H-6
H-2
NEAR_KICKOFF
```

## Blessures et disponibilités

```text
J-7
J-3
J-1
H-6
H-2
NEAR_KICKOFF
```

## Joueurs et squads

```text
J-7
J-3
J-1
```

## Lineups et formations

```text
H-2
NEAR_KICKOFF
```

## Cotes

```text
J-7
J-3
J-1
H-6
H-2
NEAR_KICKOFF
```

Marchés initiaux : `1X2` et `OVER_UNDER_2_5`. Aucun marché joueur n’appartient
au Jalon 12.

## Profils par compétition

- `FULL` : toutes les familles et toutes les fenêtres ; profil de la Ligue 1.
- `DEEP_FULL_ODDS_REDUCED` : toutes les familles API-Football, mais seulement
  `J-1`, `H-2` et `NEAR_KICKOFF` pour `ODDS` ; profil de Premier League, Liga,
  Bundesliga et Serie A.
- `FIXTURE_ONLY` : registre fixture uniquement.
- `DISABLED` : aucune fenêtre opérationnelle.

Le scheduler lit le profil de chaque fixture depuis le registre central. Une
fenêtre non autorisée par le profil n’est jamais créée ; elle ne peut donc ni
être forcée, ni acquitter un gate.

`EVENT_STATUS` suit les huit fenêtres de `FIXTURE`. Au total, la politique v2
planifie 49 observations sémantiques par fixture : 24 pour
`FIXTURE`/`TEAM`/`EVENT_STATUS`, 3 pour `SQUAD`, 12 pour
`PLAYER_STATUS`/`INJURY`, 4 pour `LINEUP`/`FORMATION` et 6 pour `ODDS`.
Pour neuf fixtures, cela donne 441 fenêtres actives. Les 531 fenêtres v1 du
pilote restent append-only pour l’audit, mais sont inactives et ne peuvent
acquitter aucun gate v2.

## Classification

- avant l’ouverture : `NOT_DUE` ;
- entre ouverture et cutoff : `DUE` ;
- réponse valide durable : `CAPTURED` ;
- réponse vide admissible pour player-status, injury, lineup ou formation :
  `CAPTURED_EMPTY` ;
- problème temporaire dans la fenêtre : `RETRY_PENDING` ;
- fin de fenêtre sans capture admissible : `MISSED_WINDOW`.

Une fenêtre ne peut être capturée qu’une fois par identité métier et hash. Un
second passage identique est un replay, pas une nouvelle observation.

Chaque reçu expose un `physical_capture_id` dérivé par SHA-256 du fournisseur,
de l’endpoint, des temps de requête/réponse et du statut HTTP. Pour
API-Football, la fixture appartient aussi à cette identité : la capture est
fixture-scoped. Pour la réponse globale The Odds API `/sports/.../odds`, la
fixture est volontairement neutralisée : tous les reçus issus du même transport
partagent un seul identifiant physique, même s’ils concernent plusieurs matchs.

Le ledger produit un événement physique par `physical_capture_id`, puis une
preuve temporelle par `physical_capture_id × fixture`. Les familles issues de
la même réponse y restent des alias techniques. Les gates conservent leur
périmètre de famille mais dédupliquent les captures au moyen de l’identité
physique ; une réponse mutualisée ne devient jamais plusieurs temps
indépendants.

L’identifiant opérationnel v2 `prospective-window-v3:<sha256>` lie aussi la
fenêtre au `registry_hash` complet de la version immuable de la fixture. Une
correction fournisseur du kickoff, des équipes, de la phase ou de la saison
crée donc une nouvelle génération de fenêtres. Les anciennes fenêtres restent
dans l’audit append-only, mais sont exclues des fenêtres actives et ne peuvent
plus satisfaire un gate de la fixture corrigée. Les fenêtres héritées du
pilote ne sont acceptées que si leur kickoff correspond encore et si elles
n’ont pas été planifiées avant l’enregistrement de la version courante.

Un statut fournisseur explicite `TBD`, reporté ou annulé crée un tombstone
append-only à partir de la dernière fixture admise. Il désactive immédiatement
toutes ses fenêtres sans effacer leur historique. Si la fixture redevient
ensuite active avec le même kickoff, un hash de cycle chaîné crée une nouvelle
version et de nouvelles fenêtres ; une simple réobservation du même état reste
idempotente.

## Horizon

Le registre résout les trente prochains jours, au plus trois journées par
compétition, avec phase et saison vérifiées. Les matchs annulés et les
kickoffs non fiables sont exclus ou restent explicitement non planifiables.
Les équipes et saisons ne sont pas codées en dur hors registre.

## Exécution sûre

Avant chaque lot, publier fixtures suivies, fenêtres prévues, fenêtres dues,
coût maximum et réserves. `windows_due=0` est un succès sans appel fournisseur.
Une fenêtre passée n’est jamais reconstruite pour améliorer artificiellement
la couverture.

Pour `capture-player` et `capture-lineup`, un contrôle API-Football
`/fixtures?id=...` est effectué une seule fois par fixture réellement due,
avant l’appel de données. Il vérifie le kickoff, l’identité et le statut
courants. Seul le statut exact `NS` est admissible ; tout autre statut,
y compris live, terminé, reporté, annulé ou TBD, donne `REGISTRY_STALE`.
Un kickoff avancé ou retardé donne le même échec contrôlé. La capture générale
applique ce contrôle à sa propre réponse. Ce preflight est interdit quand
aucune fenêtre n’est due.

Le cutoff est revérifié après la sélection initiale, avant le preflight, avant
chaque transport profond et à la réception. Une réponse arrivée au cutoff ou
après porte `TEMPORALITY_FAILED`. Lors du replay, un reçu de fenêtre n’est
admissible que si `opens_at <= response_received_at < cutoff_at < kickoff_at`.

Le contrat de sortie sans travail est exact :

```text
status=NO_DUE_WINDOW_SUCCESS
provider_calls=0
odds_api_credits=0
r2_puts=0
recovery_r2_puts=<objets réparés depuis une intention antérieure>
capture_attempts=0
```

`r2_puts=0` désigne uniquement les écritures d’une nouvelle capture. Une
intention write-ahead antérieure peut rematérialiser des objets manquants sans
fournisseur ; ce travail est publié séparément dans `recovery_r2_puts` et ne
transforme pas le run en capture due.

La matrice à horloge gelée couvre H-2:30, H-2:00, H-1:30, H-1:00, H-0:50,
H-0:45, H-0:37, H-0:30, H-0:17, H-0:15, H-0:05, H+0:01 et H+1:00,
ainsi que kickoff avancé/retardé, reporté, annulé, TBD puis fixé et modifié
après planification. Avant H-1 seule `H-2` peut être active ; à partir de H-1
seule `NEAR_KICKOFF` peut l’être ; après kickoff aucune capture n’est
admissible.

Les cinq compétitions sont inscrites dans le registre actif, chacune restant
soumise à son gate d’activation. Cette politique ne déverrouille ni modèle, ni
stratégie, ni pari : `PRODUCTION_LOCKED`,
`REAL_BETS=false` et `NO_BET_DEFAULT=true` restent obligatoires.
