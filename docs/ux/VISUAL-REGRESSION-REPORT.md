# Rapport de régression visuelle

## Couverture automatisée

Configuration : `cockpit/playwright.config.ts`
Scénarios : `cockpit/tests/visual-regression.spec.ts`

La suite produit exactement 18 PNG pleine page hors Git dans
`.ci/visual-regression/captures` :

- 8 desktop : Accueil essentiel, Accueil Expert, Matchs, fiche match,
  Observatoire, Laboratoire, Résultats et Méthode ;
- 7 mobile à 390 × 844 : les mêmes routes publiques hors Accueil Expert ;
- 1 tablette à 768 × 1024 : Observatoire avec glossaire ;
- 1 Accueil avec snapshot modifié ;
- 1 état vide mobile sans fixture.

Résultat local final : **9 tests réussis, 0 échec, 18 captures**.

La passe V1.2 du 28 juillet 2026 utilise les 18 identités vérifiées du snapshot.
Les vues prioritaires Accueil, Matchs, fiche match et Observatoire ont été
inspectées à 1440 px et 390 px. Aucun fallback `Équipe <id>` n’est visible.
`Stade Brestois 29` et `Paris Saint Germain` reviennent à la ligne sans
débordement ni association erronée.

## Contrôles par scénario

- langue `fr-FR` et titre principal attendu ;
- hydratation client terminée ;
- absence de débordement horizontal du document ;
- navigation mobile visible ;
- état vide « Aucun pari simulé pour le moment » ;
- valeur « Non applicable » ;
- Vue expert réellement active ;
- neuf onglets de fiche match Expert sélectionnables sur smartphone ;
- zoom texte à 200 % utilisable ;
- snapshots modifié et vide clairement identifiés comme preuves synthétiques ;
- glossaire visible et nommé ;
- lien d’évitement et focus visible.

## Artefact GitHub

Le job `visual-regression` de `.github/workflows/ci.yml` installe Chromium, exécute la suite et publie toujours :

```text
robin-experience-visual-${{ github.run_id }}
```

Rétention : 30 jours. Les captures ne sont pas ajoutées au dépôt.

## Contrôle navigateur manuel

Le navigateur intégré a parcouru l’Accueil, l’Observatoire et une fiche match à
1440 px puis à 390 px. Il a vérifié la bascule Expert, les neuf onglets de la
fiche un par un, la matrice mobile et les erreurs console. Un serveur de
développement propre n’a produit aucune erreur ni alerte console.

Les preuves locales de travail sont enregistrées hors Git dans :

```text
.ci/visual-regression/captures/ pendant la validation locale ; les preuves
durables sont publiées par la CI dans l’artefact visuel de chaque run.
```

## Incidents trouvés

| Test | Défaut | Correction |
|---|---|---|
| accessibilité 390 px | bouton Glossaire sans nom | `aria-label` explicite |
| mobile Laboratoire | frise de 420 px élargissant la page | largeur bornée, scroll interne |
| clavier | cible `main` non focalisable | `tabIndex="-1"` |
| automatisation | clic lancé avant hydratation | marqueur de disponibilité client |
| V1.1 dynamique | états modifié et vide absents des preuves | deux scénarios synthétiques isolés ajoutés |
| V1.2 identités | IDs fournisseur affichés comme noms | noms issus du snapshot vérifié, fallback public non numérique |
| performance | snapshot technique chargé côté client | projections publique et experte compactes au build |

## Performance des captures

La suite V1.2 complète s’exécute localement en 17 secondes, avec un seul worker
pour limiter les variations. `prefers-reduced-motion` est activé afin de
stabiliser les images.
