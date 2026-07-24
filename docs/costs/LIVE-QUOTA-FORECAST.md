# Prévision quota et coût — Live Shadow

Date : 2026-07-24  
Fournisseur actif : The Odds API

## Mesure réelle

| Indicateur | Valeur |
|---|---:|
| limite observée dans les en-têtes | 20 000 crédits |
| crédits consommés pendant l’activation | 8 |
| crédits restants | 19 992 |
| coût d’un snapshot `h2h+totals`, région EU | 2 crédits |
| plafond logiciel mensuel | 1 000 crédits |
| réserve incompressible | 4 000 crédits, soit 20 % |

The Odds API facture une requête de cotes selon le nombre de régions multiplié
par le nombre de marchés. Les endpoints sans cote et les réponses vides ne
consomment pas de crédit selon le guide v4 :
<https://the-odds-api.com/liveapi/guides/v4/>.

## Prévision mensuelle

Hypothèse prudente : 40 matchs Ligue 1, 9 fenêtres par match, 2 crédits par
snapshot.

```text
40 × 9 × 2 = 720 crédits / mois
```

Cette enveloppe reste sous le plafond logiciel de 1 000 crédits et très en
dessous de la limite observée. Le système stoppe avant d’entamer la réserve.
Aucun changement de formule ou achat fournisseur n’est requis.

## Stockage et exécution

Deux copies d’état sont conservées : 29 939 octets au total, rétention 30 jours.
À ce volume, le coût marginal attendu est nul dans l’allocation GitHub existante.
GitHub documente 500 Mo d’artefacts inclus sur Free et 1 Go sur Pro ; au-delà,
le stockage est facturé 0,25 USD par Go-mois :
<https://docs.github.com/en/billing/concepts/product-billing/github-actions>.

Les artifacts servent à conserver et partager la sortie entre workflows, ce qui
correspond à l’usage documenté par GitHub :
<https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts>.

Les minutes Actions dépendent de la visibilité et du plan du dépôt. Aucun coût
de minutes nul n’est donc affirmé sans relevé de facturation. Le Jalon 3
n’autorise aucune dépense supplémentaire automatique.
