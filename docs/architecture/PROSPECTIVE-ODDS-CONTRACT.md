# Contrat de collecte prospective des cotes

Statut : `VERIFIED` avec fournisseur mock, `UNVERIFIED` avec données réelles

Chaque snapshot contient :

- fournisseur et identifiant fixture fournisseur ;
- identifiant fixture Robin ;
- coup d'envoi UTC et représentation locale ;
- `observed_at` et `ingested_at` UTC ;
- phase `OPENING`, `INTERMEDIATE` ou `CLOSING` ;
- cotations canoniques ;
- version de schéma ;
- référence à l'observation brute.

## Idempotence

La clé d'une cotation combine fixture, marché, sélection, ligne, période,
bookmaker, instant observé et prix. Un snapshot contenant deux fois la même clé est
refusé. Deux observations identiques peuvent être tracées, mais la contrainte base
empêche deux cotations métier identiques.

## Fréquence

La fréquence est configurable dans `config/runtime.yaml`. Le jalon 1 utilise un
fournisseur mock et n'effectue aucun appel payant.

## Alertes

Le futur pipeline doit signaler :

- événement sans bookmaker ;
- paire de prix incomplète pour dé-vig ;
- observation après coup d'envoi ;
- clôture absente ;
- ligne ou sélection inconnue ;
- dérive de schéma ;
- fraîcheur supérieure au seuil.

## Ce qu'une clé réelle débloquera

Une clé The Odds API permettra de remplacer le mock par des observations réelles,
de mesurer couverture/fraîcheur et de commencer le shadow mode. Elle ne rendra pas
une stratégie valide à elle seule et n'autorise aucun pari réel.
