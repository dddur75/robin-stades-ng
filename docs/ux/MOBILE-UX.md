# Expérience mobile

## Cibles vérifiées

`360 × 800`, `390 × 844`, `430 × 932`, `768 × 1024`, `1440 × 900`, `1920 × 1080`.

## Comportement

- Le rail desktop disparaît sous 1 040 px.
- Une barre inférieure donne accès à Accueil, Matchs, Observatoire, Laboratoire, Résultats et Expert.
- L’en-tête conserve le logo, le glossaire et le sélecteur de vue.
- Les métriques, matchs, hypothèses, garanties et sections s’empilent.
- Les onglets de fiche restent dans un défilement horizontal local contrôlé.
- La matrice de couverture devient une liste verticale par rencontre.
- Les tableaux Expert sont contenus et proposent une lecture par cartes ou un scroll local.
- Les graphiques occupent toute la largeur et gardent leur résumé textuel.

## Corrections issues des tests

1. Le texte visuel du bouton Glossaire était masqué à 390 px et son nom accessible disparaissait. Un `aria-label` explicite a été ajouté.
2. Le logo mobile a reçu le nom complet « Robin des Stades ».
3. La frise à six étapes du Laboratoire produisait un débordement de page à 390 px. La carte et la grille ont reçu des bornes de largeur ; le défilement reste dans la frise.
4. Le lien d’évitement cible maintenant un élément `main` focalisable.
5. Le terrain décoratif de l’accueil peut être recadré visuellement, mais ne crée aucun défilement horizontal du document.

## Navigation et toucher

La barre inférieure est fixe, séparée du contenu par une bordure et un fond opaque. Le contenu reçoit un espace inférieur suffisant. Les actions ont un état de focus visible et une hauteur adaptée au toucher. Le glossaire fonctionne par bouton, donc sans dépendre du survol.

## Textes longs

Les libellés français ne sont pas tronqués par ellipsis dans les cartes importantes. Les statuts peuvent passer sur plusieurs lignes. Les titres de matchs et d’hypothèses utilisent `overflow-wrap` lorsque nécessaire. Les identifiants Expert sont bornés ou scrollables.

## Tableaux et matrices

La matrice de l’Observatoire utilise une vraie table sur desktop et des groupes verticaux sur mobile. Les tableaux Expert restent volontairement derrière la Vue expert ; leur conteneur est horizontalement scrollable, avec colonnes masquables pour réduire la densité.

## Validation

Les six tailles ont été contrôlées dans le navigateur. Le scénario Playwright à 390 px parcourt sept routes et vérifie `scrollWidth <= clientWidth` après hydratation. La tablette vérifie l’Observatoire et le drawer du glossaire.
