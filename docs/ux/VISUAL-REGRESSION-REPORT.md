# Rapport de régression visuelle

## Couverture automatisée

Configuration : `cockpit/playwright.config.ts`
Scénarios : `cockpit/tests/visual-regression.spec.ts`

La suite produit des PNG pleine page hors Git dans `.ci/visual-regression/captures` :

- Accueil essentiel ;
- Accueil Expert ;
- Matchs ;
- fiche Marseille – Strasbourg ;
- Observatoire ;
- Laboratoire ;
- Résultats vides ;
- Méthode ;
- chaque page publique à 390 × 844 ;
- Observatoire + glossaire à 768 × 1024 ;
- toutes les pages publiques à 1440 × 900 ;
- parcours clavier.

Résultat local final : **5 tests réussis, 0 échec**.

## Contrôles par scénario

- langue `fr-FR` et titre principal attendu ;
- hydratation client terminée ;
- absence de débordement horizontal du document ;
- navigation mobile visible ;
- état vide « Aucun pari simulé pour le moment » ;
- valeur « Non applicable » ;
- Vue expert réellement active ;
- glossaire visible et nommé ;
- lien d’évitement et focus visible.

## Artefact GitHub

Le job `visual-regression` de `.github/workflows/ci.yml` installe Chromium, exécute la suite et publie toujours :

```text
robin-experience-visual-${{ github.run_id }}
```

Rétention : 30 jours. Les captures ne sont pas ajoutées au dépôt.

## Contrôle navigateur manuel

Le navigateur intégré a parcouru `/robin-live`, `/matchs`, une fiche match, `/observatoire`, `/laboratoire`, `/resultats`, `/methode` et `/expert`. Il a vérifié les six tailles cibles, la recherche « Marseille », les cotes observées, la persistance de la Vue expert, le glossaire et les erreurs console. Un serveur de développement propre n’a produit aucune erreur ni alerte console.

Les preuves locales de travail sont enregistrées hors Git dans :

```text
C:\Users\ddura\.codex\visualizations\2026\07\28\019fa7c6-2519-7881-a031-10748a621cfd\robin-experience-v1
```

## Incidents trouvés

| Test | Défaut | Correction |
|---|---|---|
| accessibilité 390 px | bouton Glossaire sans nom | `aria-label` explicite |
| mobile Laboratoire | frise de 420 px élargissant la page | largeur bornée, scroll interne |
| clavier | cible `main` non focalisable | `tabIndex="-1"` |
| automatisation | clic lancé avant hydratation | marqueur de disponibilité client |

## Performance des captures

La suite complète s’exécute localement en environ 15 secondes, avec un seul worker pour limiter les variations. `prefers-reduced-motion` est activé afin de stabiliser les images.
