# Plan d’internationalisation

## État V1

- `fr-FR` : catalogue complet, actif et seule langue publique.
- `en-GB` : catalogue structurel avec exactement les mêmes clés, non annoncé et non sélectionnable.
- Fuseau public : `Europe/Paris`.
- Fuseau expert : UTC disponible près des preuves.

## Architecture

```text
app/i18n/
├── fr-FR.ts
├── en-GB.ts
├── index.ts
├── status-translations.ts
└── glossary.ts
```

Les composants utilisent `t("domaine.intention")`. Les formats de nombres, pourcentages, dates, durées, octets et unités sont centralisés. `app/lib/presentation.ts` adapte le snapshot technique sans changer sa source.

Le Desk P0 utilise le domaine `coverage.*` dans les deux catalogues. Ses identifiants scientifiques (`E0`, `UNKNOWN`, gates et classes temporelles) restent des codes techniques ; tous ses textes de présentation, limites, parcours et questions de confiance ont une variante `en-GB` non publique.

## Convention de clés

- clé sémantique, indépendante de la position : `results.empty.title` ;
- domaine fonctionnel en premier : `home`, `matches`, `observatory`, `method` ;
- aucune clé construite à partir d’un texte visible ;
- variables explicitement nommées ;
- textes de statut séparés du catalogue général, car ils transportent une gravité et une action.

## Contrôles CI

`tests/i18n.test.mjs` et `tests/rendered-html.test.mjs` vérifient :

- parité exacte des clés `fr-FR` / `en-GB` ;
- existence de chaque clé statique appelée ;
- accents, apostrophes et pluriels ;
- absence des anciens titres anglais sur les routes publiques ;
- absence de statut brut en Vue essentielle ;
- dates, nombres et fuseau français ;
- catalogue anglais non exposé ;
- fallback sûr ;
- préservation des invariants et des valeurs scientifiques.

La CI exécute ces tests via `pnpm test`. Les tests visuels ajoutent les traductions longues à 390 px.

## Conditions de publication de l’anglais

La langue anglaise ne pourra être exposée qu’après :

1. couverture de 100 % des clés ;
2. revue humaine du ton et des termes football ;
3. catalogue de statuts entièrement revu ;
4. formats `en-GB` et fuseau explicitement définis ;
5. captures visuelles dédiées ;
6. tests d’absence de fallback français dans les routes anglaises.

## Ajout d’un texte

1. Ajouter d’abord une clé sémantique au catalogue français.
2. Ajouter la même clé au catalogue anglais préparatoire.
3. Utiliser la clé dans le composant.
4. Ajouter ou étendre le test lorsque le texte porte un invariant, un état ou une distinction scientifique.
5. Ne pas exposer le code technique comme solution temporaire.

## Limites intentionnelles

Les noms propres, `Robin Live`, `NO BET`, `Log Loss`, `R2`, `PostgreSQL`, `API`, `CSV` et `SHA-256` ne sont pas traduits artificiellement. Ils sont définis dans le glossaire. Les exports Expert peuvent inclure un champ technique explicitement nommé ; leurs en-têtes visibles restent français.
