# Politique de budget fournisseur

Source machine canonique :
`configs/prospective_observatory_v1.json#provider_budgets`.

## Plafonds adaptatifs cinq ligues

```text
API-Football : run=250, jour=800, ligue/run=80,
               ligue/jour=240, saison=75000
The Odds API : run=20, jour=120, semaine=600,
               ligue/run=4, ligue/jour=24
```

Les caps run/jour/semaine/saison sont lus dans le journal durable avant chaque
admission. Le scope `SCOPE=<competition>` porté par chaque réservation permet
d’isoler les plafonds par ligue. Une ligue ne peut donc consommer la capacité
réservée aux quatre autres.

## Réserves protégées

```text
API_FOOTBALL_PROVIDER_RESERVE=5000
ODDS_API_PROVIDER_RESERVE=4000
ODDS_NEAR_KICKOFF_RESERVE=80
```

La réserve fournisseur reflète la capacité à ne pas consommer. La réserve
proche kickoff protège les fenêtres à forte valeur temporelle. Les valeurs
runtime contrôlent la décision ; le cockpit affiche leur provenance et ne
retombe jamais silencieusement à zéro.

Deux crédits du plafond interne restent non planifiables. Ils absorbent une
dérive d'un appel complet entre l'estimation signée et le header de coût réel ;
toute divergence de coût est comptabilisée puis ferme le circuit.

Le circuit The Odds API s’ouvre après trois échecs consécutifs et reste ouvert
quinze minutes. L’ordre physique des requêtes de cote est :
`NEAR_KICKOFF`, `H-2`, `J-1`, `H-6`, `J-3`, `J-7`. Le profil réduit des quatre
ligues de niveau B ne planifie que les trois premières fenêtres. L’algorithme
de réduction conserve les fenêtres proches et retire les plus lointaines sans
jamais dépasser le budget.

## Préflight obligatoire

Avant tout appel :

1. résoudre les fixtures officielles ;
2. compter les fenêtres réellement dues ;
3. estimer le coût maximum par fournisseur ;
4. lire le ledger cumulatif du pilote ;
5. lire quota restant et réserves ;
6. refuser l’appel si le plafond ou la réserve serait franchi ;
7. autoriser ou bloquer séparément chaque compétition.

Pour The Odds API, le solde externe est rafraîchi par `GET /v4/sports` avant
toute capture de cote. La [documentation officielle V4](https://the-odds-api.com/liveapi/guides/v4/)
décrit ce endpoint comme gratuit et confirme les headers de quota. L’appel `/odds` n’est autorisé qu’après ce
préflight frais ; son coût réel (`x-requests-last`) et son nouveau solde
(`x-requests-remaining`) alimentent ensuite le ledger durable. Un header absent
ferme la capture avec `QUOTA_UNKNOWN`.

L’estimation hashée est persistée avant la tentative. Chaque unité maximale
facturable est ensuite réservée dans le journal append-only R2
`prospective-deep-budget/prospective-provider-budget-v1` immédiatement avant
l’appel physique, puis projetée dans PostgreSQL. Une panne transport, une
réponse invalide ou un échec R2/PG ne peut donc pas rendre la consommation
invisible. Lorsque The Odds API
retourne son coût réel, un éventuel supplément est appendu avant tout traitement
du payload ; un coût inférieur reste compté conservativement sans écriture
négative.

Avant chaque transport de données, le même journal reçoit aussi un guard
append-only de zéro unité pour chaque fenêtre et tentative, avec la raison
`GUARDED_BEFORE_PROVIDER_CALL:<step>`. Ce guard n’augmente ni `used` ni les
crédits consommés ; il ferme l’intervalle que la réservation seule ne peut pas
résoudre entre une réponse fournisseur et la première intention de capture R2.
Après écriture du reçu R2, un mouvement zéro unité
`pcc1:<guard_sha256>:<receipt_hash>` clôt la lignée sans muter le
guard. À la reprise, un reçu durable peut rematérialiser idempotemment cette
complétion. Une preuve de fraîcheur complétée est alors réutilisée sans rappeler
`/fixtures`; le transport profond reste autorisé. Ce n’est que si aucun reçu R2
ne prouve l’issue que le run échoue, avant tout preflight, avec
`PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED` et interdit un second appel ou
crédit.

Le guard porte la clé
`pcg1:<provider>:<command>:<f|d>:<scope_sha256>:<step_sha256>:<window_sha256>:aN`.
Sa longueur maximale mesurée est inférieure à 250 caractères ; `pcc1` mesure
134 caractères. Les écritures restent ainsi compatibles avec
`provider_budget_ledger.idempotency_key VARCHAR(250)` dans PostgreSQL.

Chaque guard possède donc un objet/lignée SQL de complétion correspondant. La
projection sans retry est de 71 guards et 71 complétions par fixture, tous à
zéro unité : ce coût de métadonnées ne modifie pas le quota fournisseur.

Le circuit local est sondé avant cette réservation. Lorsqu’il est déjà ouvert,
la boucle s’arrête avec `CAPTURE_STOPPED_CIRCUIT_OPEN` : aucun transport, aucune
unité et aucune erreur fournisseur fantôme ne sont ajoutés. L’appel physique qui
fait effectivement franchir le seuil reste, lui, compté même s’il échoue.

## Ledger

Le ledger est append-only. Chaque mouvement porte fournisseur, unités réservées
ou facturées, appel physique, timestamp, révision et clé unique d’exécution.
Deux appels physiques répétés, même avec le même `--now`, créent deux mouvements
distincts. L’estimation séparée porte le coût maximum, les fixtures et les
fenêtres. Un replay ne produit aucun débit.

La migration d’un ancien journal PostgreSQL est ligne-par-ligne et idempotente.
Elle complète dans R2 les clés SQL manquantes même si le namespace R2 est déjà
partiellement rempli, puis reprojette R2 vers SQL. L’égalité des clés et de tous
les champs est obligatoire ; un conflit append-only ou une parité partielle
produit `R2_POSTGRESQL_PROVIDER_BUDGET_PARITY_FAILED`.

| Mesure | Interprétation |
|---|---|
| `used` | consommation append-only réelle |
| `remaining_run/day/week/season` | capacité restante dans chaque scope |
| `remaining_competition_day` | capacité protégée de la ligue |
| `provider_remaining` | quota communiqué par le fournisseur |
| `reserve` | plancher externe à conserver |
| `spendable` | minimum des capacités disponibles |

## Refus

`BUDGET_EXHAUSTED`, `RESERVE_PROTECTED`, `QUOTA_UNKNOWN` et
`CIRCUIT_BREAKER_OPEN` sont des sorties normales fail-closed. Elles ne sont pas
contournées par un paramètre manuel non audité.

## Coûts interdits

- aucun abonnement ou achat automatique ;
- aucun backfill historique sur ce budget ;
- aucun appel uniquement destiné à embellir le cockpit ;
- aucun retry en boucle.
