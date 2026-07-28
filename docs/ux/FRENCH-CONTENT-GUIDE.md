# Guide éditorial français

## Voix Robin

Robin parle de manière calme, précise et accessible. Il décrit ce qui existe, ce qui manque et ce qui arrivera ensuite. Il ne promet ni gain ni certitude. Une phrase courte donne le sens ; une phrase complémentaire peut donner la limite.

À privilégier :

- « Robin attend encore suffisamment de données pré-match. »
- « Cette donnée sera recherchée plus près du match. »
- « Capture effectuée, aucune information publiée. »
- « Non applicable » lorsqu’aucun dénominateur n’existe.

À éviter :

- une traduction mécanique des underscores ;
- « succès » pour une performance financière non établie ;
- « opportunité », « pick », « jackpot », « sûr » ou « rentable » ;
- un zéro lorsque la métrique n’existe pas ;
- une cellule vide sans explication.

## Règles de présentation

- Locale publique : `fr-FR`.
- Fuseau public : `Europe/Paris`.
- UTC : Vue expert uniquement.
- Date : `31 juillet 2026 à 20 h 45`.
- Nombre : `1 000`.
- Décimale : `985,5`.
- Pourcentage : `12,4 %`.
- Durée : `3 min 24 s`.
- Volume : `985,5 Mo`.
- Coût réel : euros ; bankroll : unités fictives.
- Tiret de rencontre : demi-cadratin, par exemple `Marseille – Strasbourg`.
- Apostrophe typographique et accents conservés.

## Hiérarchie d’un message d’état

1. Libellé court : « Données encore insuffisantes ».
2. Explication : « Les observations nécessaires n’existent pas encore en quantité suffisante. »
3. Action, si utile : « Attendre les prochaines captures. »
4. Code original : uniquement en Vue expert.

## États vides

Chaque état vide comporte un titre, une cause et, lorsque pertinent, la prochaine étape.

| Situation | Titre | Explication |
|---|---|---|
| Aucun candidat | Aucun candidat pour le moment | Robin attend assez de données pré-match avant d’autoriser un test prospectif. |
| Composition absente | La composition officielle n’a pas encore été publiée | Elle sera affichée seulement après observation vérifiée. |
| Réponse vide | Capture effectuée, aucune information publiée | La source a répondu, mais aucune information n’était disponible à cet instant. |
| Fenêtre future | Pas encore nécessaire | Cette donnée sera recherchée plus près du match. |
| Résultat absent | Aucun pari simulé pour le moment | Aucune hypothèse n’a encore franchi les critères prospectifs. |

## Termes autorisés en anglais

Allowlist publique limitée : `Robin Live`, `NO BET`, `Log Loss`, `R2`, `PostgreSQL`, `API`, `CSV`, `SHA-256`.

`Pattern`, `Backtest`, `Shadow`, `Point-in-time`, `Cutoff`, `Gate` et `Replay` peuvent apparaître comme termes de glossaire ou en Expert, mais reçoivent toujours un nom grand public français.

## Pluriels et variables

Les messages chiffrés sont produits par des clés sémantiques et des variables, jamais par concaténation d’un libellé anglais. Les formes visibles évitent les formulations fragiles : « 1 rencontre suivie », « 9 rencontres suivies », « aucune observation », « 18 preuves physiques ».

## Noms propres et abréviations

Les équipes, compétitions, fournisseurs, identifiants de modèles et formats standards ne sont pas traduits. Leur rôle est expliqué à proximité. Les codes de marché ou de workflow ne sont jamais utilisés comme titre public.

## Garanties récurrentes

Les formulations suivantes doivent rester stables :

- « Aucun pari réel »
- « Aucune promesse de gain »
- « Pertes et absences publiées »
- « Preuves datées avant match »
- « Robin préfère attendre plutôt que d’inventer une certitude. »
