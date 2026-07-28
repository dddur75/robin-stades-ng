# Rapport UTF-8 — Robin Experience V1.1

## Résultat

Les sources, catalogues français, tests et documents de la V1.1 sont encodés
en UTF-8. Aucun caractère français n’est réparé à l’exécution.

- `cleanFrench()` et sa table de remplacements ont été supprimés ;
- le modèle de présentation ne réalise aucune correction d’encodage ;
- la Vue expert annonce `0` correction d’encodage ;
- la suite refuse les signatures usuelles de mojibake dans les fichiers
  publics ;
- les libellés anglais restent cantonnés aux codes techniques visibles en Vue
  expert ;
- la description de la PR #19 est écrite depuis un fichier UTF-8.

## Contrôles

`cockpit/tests/i18n.test.mjs` parcourt les composants, bibliothèques,
catalogues et tests publics. Il détecte notamment les séquences `Ã`, `Â`, `â€`,
`ï¿½` et le caractère de remplacement Unicode.

Les assertions SSR vérifient les accents dans le HTML produit. La régression
visuelle contrôle les titres français sur toutes les routes publiques, les
états vides et les deux niveaux de détail.

## Politique

La donnée incorrectement encodée doit être corrigée à sa source ou rejetée par
la validation du snapshot. Elle ne doit pas être masquée par une fonction de
nettoyage dans le navigateur.
