# Origines : machine et propriétaire

| Origine | Sens | Exemple V1 | Autorité |
|---|---|---|---|
| `MACHINE_DISCOVERED` | Règle trouvée par une recherche automatisée préenregistrée | J10-M001 à J10-M700 | La machine propose, elle ne valide pas |
| `OWNER_PROPOSED` | Hypothèse formulée explicitement par David | H11-001 à H11-008 | Le propriétaire propose |
| `MODEL_DISCOVERED` | Signal découvert par un modèle versionné | Aucun en V1 | Le modèle propose, il ne valide pas |
| `LITERATURE_PROPOSED` | Hypothèse issue d'une source publiée et référencée | Aucune en V1 | La source doit être attribuée |

## Règle de séparation

L'origine est obligatoire, immuable et visible dans le registre comme dans le
cockpit. Une découverte machine n'est jamais décrite comme une idée de David.
Une hypothèse de David n'est jamais présentée comme une découverte statistique.
Une explication générée ne change pas l'origine de l'objet qu'elle décrit.

## Périmètre V1

- 700 règles J10 : `MACHINE_DISCOVERED` ;
- 8 hypothèses H11 : `OWNER_PROPOSED` ;
- 0 élément `MODEL_DISCOVERED` promu ;
- 0 élément `LITERATURE_PROPOSED` importé.

Les classements entre origines sont séparés afin de ne pas créer une fausse
comparabilité entre une recherche exhaustive de marché et une proposition
humaine.
