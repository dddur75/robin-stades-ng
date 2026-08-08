# Mask Engine Decision V1

## Décision

Pour l’univers E3B de 1 756 fixtures, le runtime retenu est le bitset entier
Python à deux masques (`known`, `true`). Le format durable est indépendant du
runtime : `mask-v1`, little-endian, bitorder little, exactement 220 octets par
composante avant enveloppe et checksum.

Le verdict est `MASK_ENGINE_SELECTED_PROVISIONAL_ENVIRONMENT`. La sélection
est admissible pour cette campagne, mais ne devient pas universelle avant
trois runners frais et le gel des versions et hashes de wheels. Le benchmark
local utilise 30 échantillons calibrés à 250 ms par opération. Python-int
mesure 146 ns en intersection (p95 151 ns), contre 917 ns pour NumPy packbits,
1 102 ns pour NumPy bool, 9 936 ns pour Polars, 11 118 ns pour PyArrow et
404 079 ns pour DuckDB. PyRoaring est `SKIPPED_DEPENDENCY_ABSENT` et n’a pas
été installé.

La mémoire native mesurée est de 41 600 octets pour les 80 bitsets Python,
35 200 pour NumPy packbits et 280 960 pour NumPy bool. L’overhead moteur
retenu/peak RSS de Polars, PyArrow et DuckDB reste `UNKNOWN` dans ce run
partagé ; cette limite justifie aussi le verdict provisoire. Tous convergent
vers 35 200 octets sérialisés pour les 80 masques atomiques.

## Contrat logique et Golden

- `TRUE = known & true` ;
- `FALSE = known & ~true & universe` ;
- `UNKNOWN = ~known & universe` ;
- `true` est toujours un sous-ensemble de `known` ;
- une conjonction intersecte séparément tous les `known` et tous les `true` ;
- les bits hors univers valent zéro.

Le Golden Pack de 14 fixtures et quatre cas a été réellement exécuté. Il
force TRUE/FALSE/UNKNOWN et les frontières 0/7/8/13 ; exact UNKNOWN,
sous-ensemble et sérialisation byte-identique sont verts. Les six backends
installés passent aussi les AND/OR réels du corpus 1 756, pas un simple drapeau
déclaratif.

## Durabilité

Le stockage GitHub Artifact prévu est reproductible mais non archivistique :
`MASK_STORE_DURABILITY_PARTIAL`. Aucun payload `.mask` n’entre dans Git et
aucune écriture R2 n’est autorisée. Git conserve le générateur, les seuils
gelés par ligue, `definition_hash`, `tag_snapshot_hash`, `mask_id`, checksums,
manifeste et rapport compact.
