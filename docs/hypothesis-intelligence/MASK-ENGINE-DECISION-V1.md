# Mask Engine Decision V1

## Décision

Le runtime retenu pour l’univers E3B de 1 756 fixtures est le bitset entier
Python à deux masques (`known`, `true`). Le format durable est indépendant du
runtime : `mask-v1`, little-endian, bitorder little, exactement 220 octets par
composante avant enveloppe et checksum.

Le verdict est `MASK_ENGINE_SELECTED_PROVISIONAL_ENVIRONMENT`. La sélection
est exploitable dans cette campagne, mais ne devient pas un choix universel
avant trois runners frais avec versions et hashes de wheels gelés. Le rapport
[`mask-benchmark-v1.json`](../../reports/hypothesis-masks/mask-benchmark-v1.json)
conserve les mesures NumPy bool, NumPy packbits, Polars, DuckDB, PyArrow et
Python int. PyRoaring reste `SKIPPED_DEPENDENCY_ABSENT` et n’a pas été installé.

## Contrat logique

- `TRUE = known & true` ;
- `FALSE = known & ~true & universe` ;
- `UNKNOWN = ~known & universe` ;
- `true` doit toujours être un sous-ensemble de `known` ;
- une conjonction intersecte séparément tous les `known` et tous les `true` ;
- les bits de queue hors univers valent zéro.

Le stockage temporaire est reproductible mais non durable au sens archive :
`MASK_STORE_DURABILITY_PARTIAL`. Aucun masque lourd n’entre dans Git, aucune
écriture R2 n’est autorisée, et Git conserve seulement générateur, manifeste,
hashes et compteurs.

## Gates

La construction vérifie l’ordre canonique des fixture IDs, la cardinalité
1 756, la byte-identité des enveloppes, le checksum, TRUE/FALSE/UNKNOWN et la
convergence de tous les backends vers le payload packé canonique. Une
intersection entre deux univers différents est interdite sans projection
explicite.
