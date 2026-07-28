# Audit UX avant Robin Experience V1

Date de référence : 28 juillet 2026
Source auditée : `main` à `c512c7bc20f9272cd1b91cc3acf8605500541185`
Périmètre : Cockpit Live V2, Robin Live, snapshot prospectif Jalon 12 et 24 vues historiques.

## Conclusion

L’interface réunissait une information scientifique précieuse, mais la présentait comme un inventaire technique : environ 24 destinations au même niveau, un composant principal de 2 771 lignes, des intitulés français et anglais mêlés, des codes internes presque bruts et des tableaux pensés d’abord pour un grand écran. La distinction entre recherche historique, observation prospective, simulation shadow et résultat réglé n’était pas assez visible. Un visiteur devait comprendre la structure technique avant de comprendre l’état du projet.

Les éléments à préserver étaient solides : métriques datées, provenance, hashes, états de collecte, couverture, coûts, modèles, résultats négatifs, bankroll fictive et protections NO BET. La refonte devait donc changer la présentation, pas la science.

## Inventaire des écrans

| Écran antérieur | Objectif et public | Complexité / informations | Défauts constatés | Décision V1 |
|---|---|---|---|---|
| Robin Live | Porte d’entrée visiteur et opérateur | Très élevée ; état, métriques, alertes, captures | Mélange synthèse/exploitation, jargon précoce, faible rythme mobile | Devient l’Accueil public, limité à la situation, aux matchs, aux captures, aux hypothèses, aux résultats, à la méthode et aux garanties |
| Command Center | Synthèse opérateur | Élevée ; workflows, incidents, volumes | Doublon de Robin Live, titre anglais, priorités techniques avant le sens | Fusion dans Accueil ; détails déplacés vers Expert > Système |
| Coverage Explorer | Analyste | Élevée ; familles, couverture, manques | Matrice large, statuts bruts, lecture mobile fragile | Fusion dans Observatoire avec matrice verticale mobile |
| Odds Explorer | Passionné et analyste | Élevée ; snapshots, marchés, bookmakers, marge | Isolé du contexte match, termes non expliqués | Fusion dans Matchs > fiche > Cotes |
| Match Center | Passionné | Moyenne ; rencontres et état | Carte insuffisante, navigation plate | Devient Matchs et fiche à neuf onglets |
| Shadow Performance | Analyste | Élevée ; bankroll, ROI, décisions | Historique/prospectif/shadow insuffisamment séparés ; 0 % ambigu | Devient Résultats, quatre familles étanches, « Non applicable » sans observation |
| Pipeline & Qualité | Opérateur | Très élevée ; pipeline, erreurs, couverture | Mélange état opérationnel et qualité analytique | Vue publique résumée dans Observatoire ; détail Expert > Données et qualité |
| Data Explorer | Analyste | Très élevée ; tables et données brutes | Colonnes nombreuses, mobile faible, codes visibles | Expert > Données et qualité, tableau riche filtrable/exportable |
| Deep Data Command Center | Opérateur | Très élevée ; captures profondes et gates | Titre anglais, densité, doublons avec pipeline | Expert > Système ; progression simple dans Observatoire |
| Backfill Monitor | Opérateur | Élevée ; tâches historiques | Hors du parcours public, statut brut | Expert > Système, sous « Rattrapage historique » |
| Dataset Readiness | Analyste | Élevée ; complétude des jeux | Ressemble à Coverage Explorer, jargon | Expert > Données et qualité ; synthèse publique via couverture |
| Player Explorer | Passionné et analyste | Élevée ; joueurs, états, provenance | Déconnecté du match ; données absentes peu expliquées | Matchs > fiche > Joueurs avec états vides honnêtes |
| Lineup Explorer | Passionné et analyste | Élevée ; compositions et formations | Composition/formation séparées du calendrier de publication | Matchs > fiche > Composition et Tactique |
| Feature Lab | Analyste | Très élevée ; variables, couverture, tests | N’explique pas la question football | Expert > Modèles ; mécanisme simplifié dans Laboratoire |
| Model Lab | Analyste | Très élevée ; baselines et scores | Métriques sans pédagogie immédiate | Expert > Modèles avec glossaire et résumé textuel |
| Scientific Model Arena | Analyste | Très élevée ; comparaisons | Titre anglais, surcharge, doublon Model Lab | Fusion dans Expert > Modèles |
| Matchup Lab | Passionné et analyste | Élevée ; confrontations et hypothèses | Présentation technique, progression difficile à lire | Devient Laboratoire, sous forme d’histoires football |
| External Validation | Analyste | Très élevée ; multi-ligues, intervalles | Trop spécialisée pour la navigation principale | Expert > Modèles |
| Market & Storage Control Center | Opérateur | Très élevée ; fournisseurs, R2, SQL, stockage | Plusieurs domaines dans un seul écran, risque de confusion publique | Fournisseurs/coûts dans Expert > Coûts ; stockage dans Expert > Système |
| Strategy Lab | Analyste | Très élevée ; règles et campagnes | Recouvre Feature Lab et Backtest Explorer | Laboratoire pour la question ; Expert > Simulations pour la preuve |
| Backtest Explorer | Analyste | Très élevée ; campagnes et résultats | Historique susceptible d’être lu comme prospectif | Expert > Simulations historiques ; résultats publiables étiquetés dans Résultats |
| Historical Data Quality | Analyste | Très élevée ; qualité et temporalité | Séparé artificiellement des datasets | Fusion dans Expert > Données et qualité |
| Observatoire prospectif | Visiteur, analyste, opérateur | Très élevée ; fixtures, fenêtres, captures, gates | Valeur forte mais codes internes, hiérarchie faible | Devient Observatoire visuel public ; détails et preuves en Expert |
| Cockpit analytique exhaustif | Analyste et opérateur | Extrême ; tous les blocs précédents | Une seule surface, texte dense, faible progressive disclosure | Devient l’Espace Expert repliable |

## Audit transversal

### Langue et rédaction

- Intitulés majeurs en anglais, phrases françaises autour de codes internes, unités anglo-saxonnes et dates non uniformes.
- Codes tels que `BLOCKED_BY_COVERAGE` utilisés comme message, sans explication ni action.
- Absence d’un catalogue central : mêmes notions reformulées différemment.
- Empty states parfois réduits à zéro, tiret ou cellule vide.

### Hiérarchie et doublons

- Couverture répartie entre Coverage Explorer, Dataset Readiness, Pipeline & Qualité et Historical Data Quality.
- Modèles répartis entre Feature Lab, Model Lab, Model Arena, External Validation et Strategy Lab.
- Opérations réparties entre Command Center, Deep Data Center, Backfill Monitor et Market & Storage.
- Match, joueurs, composition et cotes séparés alors qu’ils répondent au même parcours.

### Graphiques et tableaux

- Les chiffres existaient mais sans toujours séparer valeur observée, cible et non-applicabilité.
- Les visualisations expertes manquaient souvent de résumé textuel.
- Les tableaux étaient utiles pour l’analyste, mais dominaient des pages destinées à d’autres publics.
- Colonnes techniques et identifiants n’étaient pas assez protégés par un mode explicite.

### Mobile et accessibilité

- Navigation latérale et matrice horizontale difficiles à exploiter à 360–430 px.
- Cibles tactiles et textes longs français non testés systématiquement.
- Focus, lien d’évitement, réduction des mouvements et résumé des graphiques non uniformes.
- Tooltips pensés pour le survol, sans garantie équivalente au toucher.

## Éléments supprimés, déplacés ou fusionnés

Aucune donnée utile n’est supprimée. Les suppressions concernent les doublons de navigation, les titres anglais, les répétitions et les surfaces sans explication. Les détails techniques sont déplacés sous Expert ; les informations football sont replacées dans la fiche match ; les preuves scientifiques restent consultables, mais après la synthèse.

## Risques contrôlés

- La couche de présentation ne modifie pas `cockpit-data.json`.
- Les valeurs inconnues reçoivent un libellé public neutre ; leur code ne fuit pas en vue essentielle.
- Les métriques non calculables restent « Non applicable ».
- Les résultats historiques, prospectifs, shadow et réglés demeurent séparés.
