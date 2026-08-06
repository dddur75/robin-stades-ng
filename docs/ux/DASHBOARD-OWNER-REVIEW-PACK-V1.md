# Dashboard Owner Review Pack V1

Document de revue pour David. Il inventorie l'expérience actuelle sans demander de
réponse pendant la mission, sans refonte et sans déploiement.

## A. Navigation

### Routes présentes

Le code `cockpit/app/**/page.tsx` expose 22 routes :

```text
/
/robin-live
/matchs
/matchs/[id]
/matchs/historique/[canonicalMatchId]
/hypotheses
/hypotheses/familles
/hypotheses/familles/[family]
/hypotheses/arbres
/hypotheses/arbres/[treeId]
/hypotheses/classements
/hypotheses/observations
/hypotheses/longue-traine
/hypotheses/[hypothesisId]
/hypotheses/[hypothesisId]/matchs
/observatoire
/laboratoire
/resultats
/methode
/apprentissage
/expert
/expert/qualite-donnees
```

La navigation publique contient Accueil, Matchs, Hypothèses, Observatoire, Résultats et
Méthode. Le menu Expert ajoute Expert, Apprentissage, Laboratoire et cinq ancres internes
(`cockpit/app/components/navigation/experience-shell-client.tsx`).

Constats à arbitrer :

- `/` et `/robin-live` rendent le même écran ; une route canonique est à choisir.
- `/hypotheses` et `/laboratoire` se chevauchent sur familles, découvertes et observation.
- `/expert/qualite-donnees` est difficile à trouver et n'apparaît pas dans le menu Expert.
- Laboratoire est rangé sous Expert alors que son contenu participe au parcours public.
- La barre mobile porte sept destinations très compactes ; la documentation en décrit six.
- La sous-navigation Hypothèses ne matérialise pas clairement la route active.

## B. Dashboard général

Le premier écran combine état du système, rencontres, recherche et résultats. La hiérarchie
est utile, mais le nombre de cartes, badges et statuts impose une lecture experte.

Les données sont des projections JSON embarquées au build, notamment
`cockpit/app/cockpit-presentation.json` et `cockpit/app/hypothesis-universe-data.json`.
Elles ne sont pas relues depuis une source distante à chaque requête. Le libellé
« À jour au moment du snapshot » est donc exact ; il faut vérifier que David comprend
immédiatement cette fraîcheur.

Inventaire concret du snapshot embarqué, daté du `2026-07-29T13:01:53Z` :

- 116 rencontres, 3 117 fenêtres actives et 450 preuves physiques ;
- 0 observation profonde, 0 décision et 0 snapshot de cotes ;
- bankroll fictive initiale et courante de 1 000 unités ;
- 700 découvertes machine, 8 hypothèses de David et 3 contrats prospectifs gelés ;
- 0 observation prospective réelle.

À distinguer visuellement :

- données observées et gelées ;
- contenu explicatif statique ;
- valeurs simulées, dont la bankroll initiale de 1 000 unités ;
- données encore absentes ;
- état scientifique d'une capacité et état opérationnel du système.

Les états vides et erreurs spécialisées sont généralement honnêtes. En revanche, aucun
`error.tsx`, `loading.tsx` ou `not-found.tsx` de marque n'est présent au niveau global.

Le Desk P0 est une vue historique E0/PR26 : il affirme encore qu'E1 à E4 n'ont pas été
exécutés et représente toutes les familles comme globalement bloquées. Il ne projette ni
la preuve E1A acquise ni les statuts Capability V2. Son blocage global ne doit donc pas être
interprété comme le nouvel état scientifique. La revue propriétaire doit décider plus tard
comment afficher les gates par capacité, sans refonte dans cette mission. Les badges `READY`
de l'Observatoire décrivent par ailleurs un état opérationnel fournisseur, pas une readiness
scientifique `READY_STRICT` ou `READY_RECONSTRUCTED`.

## C. Hypothèses

Le parcours couvre univers, familles, arbres, classements, observations, longue traîne,
fiche, occurrences et matchs associés. Les tags, filtres, mesures de support, taux de
réussite, ROI, courbes et résultats annuels existent dans les vues historiques.

Points de revue :

- clarifier les deux taxonomies appelées « familles » ;
- rendre la généalogie d'une hypothèse compréhensible avant les détails techniques ;
- distinguer découverte machine, hypothèse de David et contrat prospectif ;
- vérifier que filtres et tags réduisent réellement la charge cognitive ;
- rendre la navigation fiche → occurrences → matchs réversible et prévisible ;
- séparer statut scientifique, popularité, support statistique et performance économique.

## D. Stratégies

Le dashboard doit éviter d'assimiler une hypothèse à une stratégie pariante. La revue doit
confirmer quatre niveaux distincts : propriété observée, hypothèse, règle de décision et
stratégie avec prix admissible.

À vérifier écran par écran : marchés et cotes utilisés, bankroll fictive, ROI, drawdown,
stabilité temporelle, support minimal et folds. Les résultats historiques ou simulés ne
doivent jamais ressembler à une promotion de pari réel.

## E. Matchs

La fiche prospective `/matchs/[id]` affiche les équipes, le coup d'envoi, la couverture,
les captures attendues et les cotes lorsqu'elles existent. La fiche historique
`/matchs/historique/[canonicalMatchId]` affiche le score final, les preuves et les relations
vers les hypothèses. Quatre onglets prospectifs rendent actuellement toujours un état vide :
Joueurs, Absences, Composition et Tactique
(`cockpit/app/components/matches/match-detail.tsx`).

La revue doit décider s'il faut : conserver ces promesses visibles, les masquer tant que la
donnée manque, ou les regrouper sous un état « données à venir ». Le bloc « Hypothèses
concernées » n'est pas encore relié au match : il affiche les quatre premières hypothèses
globales et peut induire en erreur. Chaque carte match reprend également le nombre global
d'hypothèses. Aucun chemin vers un pari réel ne doit être ajouté.

Les onglets utilisent `role="tab"` et `aria-selected`, mais le conteneur et les panneaux
doivent être revus pour `tablist`, `aria-controls` et les identifiants associés.

## F. Graphiques existants et lacunes

Le cockpit implémente déjà six visualisations historiques :

- courbe de bankroll ;
- périodes et folds temporels ;
- distribution des cotes ;
- résultats par saison ;
- concentration par équipe ;
- séries gagnantes et perdantes.

Les lacunes à prioriser, sans les construire dans cette mission, sont surtout la comparaison
hypothèse/référence, l'incertitude autour du support et la représentation des dépendances,
puis ultérieurement d'un hypergraphe validé.

Chaque graphique devra préciser population, période, grain, dénominateur, statut des
`UNKNOWN` et caractère observé ou reconstruit.

## G. Langage

Termes restant à expliquer ou traduire selon le niveau : `ROI`, `NO BET`, `Log Loss`,
`ledger`, `Gate`, `R2`, `PostgreSQL`, `cutoff`, `hash`, support et drawdown.

Le niveau essentiel doit employer des phrases courtes et orientées décision. Le niveau
analyse peut exposer les dénominateurs et limites. Le niveau expert conserve provenance,
hashes, grains, temporalité et contrats.

## H. Design et accessibilité

Le risque principal est la densité : de nombreux textes se situent entre `.47rem` et
`.68rem`, y compris dans l'univers Hypothèses. La barre mobile descend à `.52rem`.

À contrôler : hiérarchie des titres, longueur des cartes, respiration, largeur des tableaux,
contraste des statuts, palette pour daltonisme, focus visible, navigation clavier, zoom 200 %,
réduction des mouvements et couleurs forcées.

Les fondations utiles existent : langue française, skip-link, fermeture du glossaire par
Échap et gestion du focus. Une validation humaine NVDA + Edge et smartphone reste requise.

## I. Checklist David

1. Choisir entre `/` et `/robin-live` comme accueil canonique.
2. Valider les six destinations publiques et la septième entrée mobile Expert.
3. Décider si Laboratoire appartient au parcours public ou au menu Expert.
4. Arbitrer le chevauchement `/hypotheses`–`/laboratoire`.
5. Donner deux noms distincts aux taxonomies de 28 et 5 familles.
6. Confirmer la visibilité et le contrôle d'accès de `/expert/qualite-donnees`.
7. Ajouter ou refuser une entrée directe « Données et qualité » dans le menu Expert.
8. Décider du sort des quatre onglets match systématiquement vides.
9. Vérifier la sémantique ARIA complète des onglets match.
10. Ajouter un état actif perceptible à la sous-navigation Hypothèses.
11. Classer chaque terme technique par niveau essentiel, analyse ou expert.
12. Confirmer que ROI, taux de réussite et bankroll sont identifiés comme historiques ou simulés.
13. Vérifier la compréhension immédiate de la date et de la fraîcheur du snapshot.
14. Revoir les textes inférieurs à `.75rem`, en priorité `.47rem` et `.52rem`.
15. Tester le Desk P0 et ses tableaux à 390 px, 1 440 px et zoom 200 %, en le présentant comme une vue historique E0/PR26.
16. Conserver les états vides qui n'inventent ni zéro ni disponibilité.
17. Conserver les erreurs spécialisées avec action « Réessayer ».
18. Décider de composants globaux `error`, `loading` et `not-found` de marque.
19. Tester clavier, NVDA + Edge, réduction des mouvements et couleurs forcées.
20. Valider la hiérarchie finale Accueil → Matchs → Hypothèses → Observatoire → Résultats.
21. Vérifier la séparation hypothèse, règle, stratégie, marché et cote.
22. Auditer les six graphiques existants et prioriser seulement leurs lacunes.
23. Vérifier pour chaque graphique grain, période, dénominateur et traitement d'UNKNOWN.
24. Confirmer que la Vue Expert réduit, plutôt qu'augmente, la confusion des débutants.
25. Noter les décisions propriétaire avant toute refonte ou publication.
26. Décider comment exposer plus tard les gates par capacité sans reprendre le blocage global historique du Desk P0.
27. Distinguer les badges opérationnels `READY` de toute readiness scientifique qualifiée.
28. Masquer le bloc « Hypothèses concernées » tant qu'il n'est pas relié au match, ou définir son contrat d'association.

## Limites de cette revue

Revue fondée sur le code, les routes et les projections embarquées. Aucun Playwright global,
aucune modification TSX/CSS, aucune publication et aucun déploiement n'ont été exécutés.
