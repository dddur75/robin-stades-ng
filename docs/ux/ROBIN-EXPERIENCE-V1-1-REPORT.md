# Robin Experience V1.1 — données dynamiques, UTF-8 et robustesse

## Verdict

`ROBIN_EXPERIENCE_V1_1_DYNAMIC_READY`

La refonte V1 est désormais alimentée par un modèle de présentation typé
construit depuis le snapshot vérifié. Les valeurs live de rencontres,
fenêtres, captures, bankroll, résultats, statuts et fraîcheur ne sont plus
codées en dur dans les composants.

## Pipeline livré

1. `run_prospective_observatory.py gate-report` publie les registres complets
   de fixtures, preuves et fenêtres.
2. `build_cockpit_snapshot.py` valide la source, applique la politique
   temporelle versionnée et produit `cockpit-data.json` avec son SHA-256.
3. `buildPresentationModel(snapshot)` crée un modèle public déterministe,
   testable avec une horloge injectée.
4. `build-presentation-data.ts` génère les projections compactes publique et
   experte avant le build.
5. Les composants consomment uniquement ce contrat.

Le snapshot livré provient du run vérifié `30314975830`. Sa reconstruction a
été faite en lecture seule, sans fournisseur, sans R2 distant et sans base
distante. Les résultats scientifiques et gates n’ont pas été modifiés.

## États dynamiques validés

| Cas | Mutation | Attente vérifiée |
|---|---|---|
| A | snapshot réel | 9 rencontres, 441 fenêtres actives, 18 preuves, 0 observation profonde |
| B | 19e capture, blessure, gate progressant | compteurs, famille et progression mis à jour |
| C | 10e fixture | dixième carte sans changement de code |
| D | coup d’envoi reporté | fenêtres et prochaine capture recalculées |
| E | snapshot de cotes | onglet Cotes alimenté par la fixture canonique |
| F | zéro fixture | états vides explicites, aucun accès positionnel |
| G | décision shadow réglée | bankroll, courbe et résultats dérivés du ledger |

Les captures simultanées sont regroupées et annoncent le nombre de rencontres
concernées. Les fixtures annulées ou tombstonées et les fenêtres legacy,
terminées ou manquées sont exclues des prochaines captures.

## Encodage et contenus

`cleanFrench()` est supprimé. Le rapport dédié
`docs/ux/UTF8-REPORT.md` décrit le contrôle UTF-8 et le comportement des codes
inconnus. Le snapshot actuel a une couverture de traduction de statuts de
`117/117`, soit `100 %`.

## Accessibilité et responsive

La navigation clavier, le lien d’évitement, le focus, le glossaire, la Vue
expert, le menu mobile, les mouvements réduits, les tableaux et le zoom texte
à 200 % sont rejoués. À 390 × 844, les neuf onglets de la fiche match Expert
sont présents et sélectionnables un par un.

La suite produit exactement 18 preuves visuelles : 8 desktop, 7 mobile,
1 tablette avec glossaire, 1 snapshot modifié et 1 état vide.

## Performance

La projection compacte évite d’embarquer le snapshot technique d’environ 1 Mo
dans le client. Les assets non compressés passent de `830 890` octets en V1 à
`545 960` octets en V1.1 :

- JavaScript : `783 519` → `498 611` octets (`−36,4 %`) ;
- CSS : `47 371` → `47 349` octets ;
- total : `−34,3 %`, largement sous le plafond V1 + 3 %.

## Validation

La validation locale compte `748` tests Python, `26` tests frontend et `9`
tests Playwright, tous verts. Elle couvre aussi TypeScript strict sur
l’application, ESLint, Ruff, mypy strict, Bandit, la recherche de secrets,
`pip check`, `compileall`, les formats YAML/JSON, le SSR et l’i18n. La CI
GitHub de la PR #19 et le redéploiement privé Sites complètent les preuves de
livraison consignées dans la PR.

## Invariants et action

La V1.1 ne déclenche aucun appel fournisseur, aucune capture, aucune écriture
R2/PostgreSQL distante, aucune décision, aucune mise et aucune publication
sociale. La PR #19 reste brouillon, ouverte et non fusionnée. L’unique action
utilisateur est de consulter les preuves et le site privé ; toute fusion reste
une décision séparée et explicite.
