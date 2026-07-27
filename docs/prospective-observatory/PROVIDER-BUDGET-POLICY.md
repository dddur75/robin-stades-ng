# Politique de budget fournisseur

Source machine canonique :
`configs/prospective_observatory_v1.json#provider_budgets`.

## Plafonds du pilote

```text
MAX_API_FOOTBALL_CALLS_TOTAL=5000
MAX_ODDS_API_CREDITS_TOTAL=250
ODDS_API_INTERNAL_SAFETY_RESERVE=2
```

Ces plafonds sont cumulés sur l’ensemble du pilote initial Jalon 12, pas par
workflow ni par run.

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

## Préflight obligatoire

Avant tout appel :

1. résoudre les fixtures officielles ;
2. compter les fenêtres réellement dues ;
3. estimer le coût maximum par fournisseur ;
4. lire le ledger cumulatif du pilote ;
5. lire quota restant et réserves ;
6. refuser l’appel si le plafond ou la réserve serait franchi ;
7. conserver la Ligue 1 et réduire P1 si nécessaire.

Pour The Odds API, le solde externe est rafraîchi par `GET /v4/sports` avant
toute capture de cote. La [documentation officielle V4](https://the-odds-api.com/liveapi/guides/v4/)
décrit ce endpoint comme gratuit et confirme les headers de quota. L’appel `/odds` n’est autorisé qu’après ce
préflight frais ; son coût réel (`x-requests-last`) et son nouveau solde
(`x-requests-remaining`) alimentent ensuite le ledger durable. Un header absent
ferme la capture avec `QUOTA_UNKNOWN`.

L’estimation hashée est persistée avant la tentative. Le mouvement réellement
consommé et le solde fournisseur sont appendus après la réponse ; une panne
transport est comptée de manière conservatrice.

## Ledger

Le ledger est append-only. Chaque mouvement porte fournisseur, unités
réellement consommées, fenêtre et numéro de tentative, timestamp, révision et
clé d’idempotence. L’estimation séparée porte le coût maximum, les fixtures et
les fenêtres. Un replay ne produit aucun débit.

| Mesure | Interprétation |
|---|---|
| `used` | consommation cumulée réelle |
| `remaining` | plafond du pilote moins `used` |
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
- aucune extension de ligue tant que P0 n’est pas vert ;
- aucun appel uniquement destiné à embellir le cockpit ;
- aucun retry en boucle.
