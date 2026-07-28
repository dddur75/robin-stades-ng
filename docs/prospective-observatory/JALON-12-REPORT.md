# Jalon 12 — rapport de l’Observatoire prospectif

## Synthèse technique

Le contrat, l’architecture R2-first, les fenêtres, les budgets et la surface
Robin Live sont préparés pour mesurer les captures prospectives sans conclusion
sportive prématurée. Le snapshot versionné initial est
`WAITING_FOR_FIRST_DUE_WINDOW` et sa provenance est
`NO_PROSPECTIVE_CAPTURE_YET` : zéro fixture ou capture n’est inventé.
La provenance des politiques est
`configs/prospective_observatory_v1.json`.
La politique temporelle active sur la branche de revue est
`prospective-capture-window-v2` (Option B consolidée) ; elle n’est pas encore
une preuve d’activation sur `main`.

Ce document est un rapport évolutif. Les compteurs opérationnels ne deviennent
des preuves qu’après un pilote réel sur des fenêtres effectivement dues et un
replay R2 vert.

## État observable initial

| Mesure | Valeur initiale | Interprétation |
|---|---:|---|
| Fixtures prospectives publiées | 0 | registre réel non encore injecté dans le snapshot versionné |
| Fenêtres dues | 0 | aucun appel à forcer |
| Captures revendiquées | 0 | aucune donnée démo |
| Appels API-Football | 0 | plafond pilote 5 000 |
| Crédits The Odds API | 0 | plafond pilote 250, admission planifiée 248 |
| Décisions de pari | 0 | interdites dans le jalon |
| Payloads bruts Git | 0 | objectif contractuel |

Les réserves protégées sont 5 000 appels API-Football, 4 000 crédits The Odds
API et 80 crédits dédiés aux fenêtres proches du kickoff. Les valeurs runtime
doivent porter leur provenance avant tout appel.

## Périmètre, données et définitions

Le pilote P0 couvre la Ligue 1 sur trente jours et au plus trois journées. Les
quatre autres grandes ligues restent `P1_OFF`. Les neuf familles sont suivies au grain
fixture × fournisseur × famille × fenêtre.

Une capture est temporellement admissible uniquement si :

```text
opens_at <= response_received_at < cutoff_at < kickoff_at
```

Les reçus de registre sans fenêtre conservent la règle sans `opens_at`.
`CAPTURED_EMPTY` compte comme observation réelle seulement pour les familles
où le vide est un résultat fournisseur admissible. Pour `INJURY`, il constitue
la preuve bornée « aucune blessure rapportée à cet instant » et peut satisfaire
le gate ; il ne prouve pas l’absence médicale et ne devient pas zéro.
`MISSED_WINDOW`, `TEMPORALITY_FAILED` et `IDENTITY_FAILED` restent visibles et
ne sont jamais imputés.

## Méthode

Le scheduler horaire sélectionne les fenêtres préenregistrées dues, puis vérifie
budget, réserve et circuit breaker. Les octets reçus sont hashés et stockés
append-only dans R2. PostgreSQL conserve les index et projections, jamais les
corps volumineux. Le replay reconstruit une base jetable sans fournisseur.

Robin Live lit un rapport compact nettoyé et ne contacte ni R2, ni Neon, ni un
fournisseur depuis le navigateur.

## Gates et hypothèses

Les gates joueur, blessure, lineup, formation et marché commencent à
`WAITING_FOR_OBSERVATIONS`. H11-001 à H11-008 gardent leurs seuils gelés de 80
à 120 occurrences selon le protocole. Zéro observation implique zéro test,
pas un résultat négatif.

Les cinq cartes publiques — buteur en forme contre deux centraux absents,
4-3-3 contre 4-4-2, gardien titulaire absent, continuité du onze et pied fort —
affichent données requises, accumulation, statut et première date possible.
Elles n’affichent aucune conclusion.

## Limites et robustesse

- aucun pilote réel ne peut être déclaré depuis le snapshot initial ;
- l’absence de fenêtre due ne teste pas les capacités lineup/injury/odds ;
- un workflow vert sans progression de données ne suffit pas ;
- la couverture agrégée ne remplace pas un gate au grain fixture ;
- l’historique post-match ne prouve pas la disponibilité prospective ;
- les dates possibles d’analyse dépendent des fixtures et captures réelles.

## Étapes suivantes

1. appliquer `0009_jalon12_observatory` ;
2. exécuter le registre Ligue 1 ;
3. publier le coût et les fenêtres dues ;
4. capturer seulement ces fenêtres ;
5. vérifier R2 et PostgreSQL ;
6. rejouer sur une base jetable ;
7. actualiser ce rapport et Robin Live ;
8. conserver la PR Jalon 12 non fusionnée.

## Questions ouvertes

- quelles familles le fournisseur expose-t-il réellement à chaque fenêtre ?
- combien de journées faut-il pour atteindre deux fenêtres critiques par
  famille ?
- les réserves runtime permettent-elles P1 sans menacer le live existant ?
- à quelle date chaque hypothèse atteint-elle son minimum préenregistré ?

Ces questions sont des objectifs de mesure, pas des résultats.

## Preuve opérationnelle du 27 juillet 2026

Le pilote réel borné a été exécuté sur la Ligue 1 par le run GitHub
`30304339733`. Toutes les étapes opérationnelles — migration Neon, registre,
scheduler, captures dues, replay R2 et gates — ont réussi. Le run global a
ensuite révélé une assertion frontend qui supposait encore le snapshot initial.
Le correctif n’a pas relancé le fournisseur. Après durcissement adversarial,
le run replay-only final `30314975830`, sur
`2469e57ec4b2ef2849f9e707f63843033ec026e6`, a explicitement ignoré le
registre, le scheduler et les captures réseau, puis validé replay, gates,
Robin Live et l’artefact `jalon12-pilot-30314975830`. La CI PR
`30314978406` est également verte.

### Fixtures, fenêtres et captures

| Mesure | Valeur vérifiée |
|---|---:|
| Fixtures Ligue 1 suivies | 9 |
| Horizon | 30 jours, 3 journées maximum |
| Fenêtres v1 conservées (inactives) | 531 |
| Fenêtres v2 actives projetées pour ces 9 fixtures | 441 |
| Fenêtres dues au contrôle | 0 |
| Captures `FIXTURE` | 9 |
| Captures des huit autres familles | 0 |
| Octets bruts R2 | 11 691 |
| Hashes de payload | 9 |
| Captures tardives / rejetées / invalides / manquées | 0 / 0 / 0 / 0 |

Les 531 fenêtres sont la preuve append-only du pilote v1 ; elles ne sont pas
réactivées par la v2. Les 441 fenêtres correspondent à 49 observations
sémantiques v2 par fixture et ne seront des planifications opérationnelles
prouvées qu’après un scheduler exécuté sur la version corrigée.

Les neuf reçus `FIXTURE` sont antérieurs au cutoff. Aucune lineup, blessure,
formation, donnée joueur ou cote n’est revendiquée : leurs fenêtres n’étaient
pas dues.

### Fournisseurs et budgets

| Mesure | Valeur vérifiée |
|---|---:|
| Appels API-Football du pilote | 3 |
| Crédits The Odds API | 0 |
| Erreurs / retries | 0 / 0 |
| Plafond API-Football | 5 000 |
| Plafond The Odds API | 250 |
| Réserves externes | 5 000 / 4 000 |
| Réserve Odds proche kickoff | 80 |
| Appels et crédits du replay | 0 / 0 |

### R2, PostgreSQL et ledger

- R2 : 18 objets — 9 payloads et 9 reçus —, 24 714 octets physiques
  — 11 691 de payloads et 13 023 de reçus —, 18 vérifiés, lag 0,
  suppression 0 ;
- replay complet : 18 objets examinés, 9 payloads reconstruits, sélection non
  tronquée, 0 mismatch, 0 perte, 0 appel, 0 crédit ;
- second passage : 0 insert, 9 doublons évités ;
- PostgreSQL : migration `0009_jalon12_observatory`, 12 tables, 45 nouvelles
  évaluations de gate et 9 reçus déjà présents dans le compteur de 54,
  aucun corps de payload ; le libellé historique de reconstruction du run
  précède le contrat 12.1 ;
- temporalité : 9 preuves avant cutoff, 45 évaluations de gate, 0 tardive,
  0 rejet ;
- ledger V3 historique : 586 événements, chaîne `HASH_CHAIN_VERIFIED`,
  0 décision de pari. Ce total v1 ne distinguait pas encore les neuf réponses
  physiques des neuf preuves temporelles et ne doit pas être présenté comme
  la cardinalité 12.1.

Le contrat 12.1 publie désormais `R2_REPLAY_VERIFIED` avec
`CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2` uniquement si reçus,
index payloads et journal budget sont à parité exacte entre R2 et PostgreSQL.
Sinon il publie `R2_REPLAY_PARTIAL_FIXTURE_INDEX` /
`RECONSTRUCTION_INCOMPLETE` ou un échec de parité. Ces nouveaux libellés
restent à confirmer par le prochain run de la tête corrigée.

Les cinq gates restent `BLOCKED_BY_COVERAGE` sur les neuf fixtures. H11-001 à
H11-008 restent gelées, avec 0 observation et
`WAITING_FOR_OBSERVATIONS`. Il s’agit du résultat attendu avant les premières
fenêtres critiques.

### Durcissement final

La revue adversariale a fermé les écarts suivants sans nouvel appel
fournisseur :

- le Cockpit n’accepte que des enveloppes authentifiées et liées au même
  `capture_set_sha256`; les inventaires PostgreSQL protégés proviennent du
  replay vérifié et non d’une valeur initiale ;
- les versions de registre, annulations, passages `TBD` et réactivations
  conservent une chaîne de cycle de vie append-only, y compris après reprise
  SQL ;
- le circuit fournisseur compte exactement les appels physiques et interdit
  tout compteur fantôme après ouverture ;
- chaque transport de données est précédé d’un guard R2 immuable de zéro unité
  par fenêtre et tentative, puis un lien append-only
  `pcc1:<guard_sha256>:<receipt_hash>` rattache le reçu durable.
  La reprise réconcilie ce lien si le reçu R2 existe et réutilise notamment la
  fraîcheur `/fixtures` avant d’autoriser le transport profond. Sans reçu
  vérifiable, elle ferme avec `PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED`,
  avant tout preflight, sans second appel ni crédit ;
- l’inventaire R2 est exhaustif sur payloads, reçus et intentions de
  récupération. Le lot historique vérifié précède les intentions et porte donc
  légitimement `recovery_objects=0`; toute nouvelle écriture est récupérable
  sans fournisseur ;
- un reçu durable sans tentative compacte est réconcilié sans dupliquer la
  donnée métier.

Le guard compact
`pcg1:<provider>:<command>:<f|d>:<scope_sha256>:<step_sha256>:<window_sha256>:aN`
reste sous 250 caractères et sa complétion `pcc1` en compte 134. La lignée est
donc compatible avec l’`idempotency_key VARCHAR(250)` PostgreSQL.

La suite de référence antérieure à la revue 12.1 compte 690 tests, dont
124 tests Jalon 12. Ruff, mypy strict
sur 106 sources, Bandit, `pip check`, `compileall`, YAML/JSON, détection de
secrets, migrations et frontend étaient verts sur cette tête. La suite 12.1
doit être rejouée avant toute fusion ; ce paragraphe n’en préjuge pas le
résultat.

### Robin Live et verdict

Le snapshot du run `30314975830` porte
`origin=LIVE_PROSPECTIVE_CAPTURE`, `PROSPECTIVE_GATES_ACCUMULATING`, les neuf
fixtures, les compteurs fournisseur et les preuves R2/Neon. Son SHA-256 est
`f0ff76b0c476ef259eb73143f969a75f3c6904786e1d073ce9874c1cbd776f53`.
Le build 5/5 et les quatre tests frontend sont verts. L’artefact est publié ;
aucun déploiement privé n’est revendiqué.

Verdict pré-fusion :

```text
JALON_12_PARTIAL_CAPTURE_READY
```

Le qualificatif `PARTIAL` décrit seulement l’absence normale de fenêtres
joueur, blessure, lineup, formation et cote dues. Il ne constitue ni un échec
du pipeline ni une validation d’hypothèse. La PR #17 reste brouillon et non
fusionnée.

## Revue temporelle 12.1 — coûts et capacités

La politique Option B consolide les fenêtres proches du kickoff sans
chevauchement : `H-2=[H-3,H-1)` et
`NEAR_KICKOFF=[H-1,kickoff)`. Le périmètre actif représente 49 observations
sémantiques par fixture, contre 59 dans la politique initiale : les 531
fenêtres du pilote restent une preuve historique immuable et inactive, tandis
que la politique révisée planifie 441 fenêtres v2 pour ces neuf fixtures.

Un `physical_capture_id` dérivé relie les reçus provenant d’une même réponse.
Il est fixture-scoped pour API-Football, mais global entre fixtures pour une
réponse The Odds API `/sports/.../odds`. Le ledger sépare planifications,
tentatives, captures physiques, `physical_http_calls`, preuves temporelles par
capture × fixture et évaluations. Les gates dédupliquent dans leur périmètre au
moyen de l’identité physique. Une réponse mutualisée ne peut donc plus gonfler
le nombre d’observations indépendantes.

Le preflight kickoff player/lineup est borné aux seules fixtures dues. Une
version avancée ou retardée ferme la capture, et seul le statut API-Football
exact `NS` est admissible. Le cutoff est relu avant le preflight, avant chaque
transport profond et à la réception. En l’absence de fenêtre due, le contrat exact est
`NO_DUE_WINDOW_SUCCESS`, avec zéro appel fournisseur, zéro crédit Odds, zéro
put de capture R2 et zéro tentative. Une réparation antérieure est publiée
séparément dans `recovery_r2_puts` et ne change pas ce verdict.

La durabilité couvre aussi le budget : chaque unité est journalisée append-only
dans R2 avant transport, puis réconciliée avec PostgreSQL. Les reçus, index
payloads et budgets doivent être à parité dans les deux sens. Un seeding legacy
partiellement présent dans R2 est complété idempotemment ligne par ligne. Les
tables `prospective_player_status`, `prospective_injuries`,
`prospective_lineups`, `prospective_formations` et
`prospective_odds_snapshots` sont ensuite comparées par ensemble exact de
lignes ; tout ajout, manque ou mutation bloque le replay. Les neuf points
d’interruption — guard avec reçu mais sans complétion, guard sans reçu,
intention seule, payload sans reçu, reçu sans PostgreSQL, projection partielle,
timeout après index, replay complet et replay répété — se reconstruisent sans
fournisseur ou échouent explicitement. Un reçu durable résout le premier cas ;
le guard sans preuve reste volontairement fail-closed.

La lignée ajoute un objet R2 et une projection SQL de complétion par guard. Le
coût de métadonnées sans retry est de 71 guards et 71 complétions par fixture,
avec zéro unité fournisseur.

La projection déterministe est publiée dans
`reports/jalon12/season-cost-projection.json`. Le scénario central inclut les
22 appels endpoint et les 8 preflights de fraîcheur par fixture :

| Portée | API-Football | Crédits Odds |
|---|---:|---:|
| pilote, 9 fixtures | 305 | 36 |
| journée Ligue 1 | 368 | 36 |
| mois, 36 fixtures | 1 298 | 144 |
| saison Ligue 1, 306 fixtures | 11 363 | 1 224 |
| cinq ligues, 1 752 fixtures | 59 607 | 7 008 |

Ces projections ne contournent pas les plafonds cumulés du pilote
5 000 / 250 : chaque cohorte reste soumise à l’admission runtime. La saison
Ligue 1 et, a fortiori, les cinq ligues dépassent ces caps ; elles constituent
une projection, pas une autorisation.

La matrice
`docs/prospective-observatory/PROVIDER-CAPABILITY-MATRIX.md` documente les neuf
familles, leurs endpoints réels, la mutualisation des réponses, les vides
légitimes et les limites d’horodatage. Aucun horodatage fournisseur n’est
actuellement mappé dans le reçu canonique ; les timestamps HTTP locaux restent
la preuve d’observation. P0 est Ligue 1 seule et P1 demeure `P1_OFF`.

Ces corrections sont présentes sur la branche de la PR #17, pas encore
fusionnée au moment de cette mise à jour documentaire. Elles ne prouvent ni
l’activation des cron sur `main`, ni un nouveau run fournisseur, ni une
nouvelle capture. Les chiffres du run `30314975830` restent la référence
opérationnelle v1 jusqu’à une validation 12.1 exécutée et archivée.

`PRODUCTION_LOCKED`, `REAL_BETS=false`, `NO_BET_DEFAULT=true`, publication
sociale et mode démo désactivés restent inchangés. Aucune hypothèse, stratégie
ou décision de pari n’est promue.
