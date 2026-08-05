# Hypothesis Research Cockpit V2 — contrat privé

## Décision

Le prototype autorisé est un **Desk de couverture P0 privé** intégré à `/expert/qualite-donnees`. Il explique pourquoi la recherche reste fermée ; il ne transforme pas une définition E0 en résultat historique.

Verdict de livraison : `HYPOTHESIS_RESEARCH_COCKPIT_V2_READY_FOR_REVIEW`.

État de publication : `NOT_DEPLOYED_BY_DESIGN`. La présence de `cockpit/.openai/hosting.json` conserve le chemin de capacité Sites, mais ce lot n’autorise ni déploiement, ni partage public, ni remplacement d’une version live dont la provenance n’est pas réconciliée.

## Vérité affichée

- définition E0 : fermée et testée ;
- cellules P0 attendues : 480 (`5 × 6 × 16`) ;
- cellules empiriquement fermées : 0 ;
- propriétés `CALENDAR_FATIGUE` prêtes : `0/17` ;
- gates fonctionnels prêts : `0/8` ;
- gates bloqués par source : 2 ;
- trois taux séparés : `UNKNOWN`, rendu « Non mesuré », jamais `0 %` ;
- effets externes : 0 appel fournisseur, 0 écriture R2, 0 achat, 0 crédit cotes.

Le composant échoue fermé si les sources compactes divergent sur les dimensions P0, les familles, les grains, les compteurs, les gates ou le calendrier, si une fermeture empirique n'est pas ventilée, ou si un effet externe est annoncé.

## Architecture de l’information

```text
Espace Expert
└── Données et qualité
    ├── Desk de couverture P0
    │   ├── définition E0 / preuve empirique
    │   ├── compteurs de fermeture
    │   ├── parcours Données → Hypothèse → Stratégie → Matchs
    │   ├── trois taux indépendants
    │   ├── niveaux E0–E4
    │   ├── gates et conditions CALENDAR_FATIGUE
    │   ├── couverture des 16 familles
    │   ├── provenance et effets externes
    │   └── couche de confiance
    └── diagnostics sémantiques historiques — hors preuve P0
```

`p0-coverage-desk.server.ts` compose le contrat, le catalogue de grains et les trois rapports compacts nécessaires. Le client reçoit uniquement un modèle de 16 familles, sans cellule matérialisée, `cell_id`, payload brut, clé R2, endpoint fournisseur, secret ni hash de reçu. Toute fermeture non nulle exige d'abord une ventilation compacte par famille et échoue sinon fermée.

## Parcours conditionnel

| Étape | État actuel | Ouverture |
|---|---|---|
| Données | disponible | ancre vers la grille P0 |
| Hypothèse | conditions seulement | ancre vers les gates ; aucun calcul |
| Stratégie | bloquée | exige contrôles scientifiques validés |
| Matchs | bloquée | exige un ensemble d’appartenance gelé |

Les deux premières étapes sont de vrais liens clavier. Les deux dernières sont des libellés `aria-disabled`, sans URL trompeuse.

## Wireframes

### Bureau

```text
┌────────────────────────────────────────────────────────────┐
│ titre, limite scientifique                    badge bloqué  │
├──────────────────────────┬─────────────────────────────────┤
│ Définition E0 fermée      │ Preuve empirique ouverte       │
├────────────┬──────────────┬──────────────┬─────────────────┤
│ 480        │ 0            │ 0/17         │ 0/8             │
├────────────────────────────────────────────────────────────┤
│ Données → Hypothèse → Stratégie bloquée → Matchs bloqués   │
├───────────────────┬───────────────────┬────────────────────┤
│ taux UNKNOWN      │ taux UNKNOWN      │ taux UNKNOWN       │
├──────────────────────────┬─────────────────────────────────┤
│ niveaux E0–E4             │ gates                           │
├────────────────────────────────────────────────────────────┤
│ table 16 familles                                        ↔ │
├──────────────────────────┬─────────────────────────────────┤
│ provenance                │ couche de confiance             │
└──────────────────────────┴─────────────────────────────────┘
```

### Mobile

Les sections deviennent monocolonnes sous 700 px et les métriques sous 500 px. La table conserve ses colonnes et devient une région horizontale focalisable, plutôt que de masquer des dimensions. La barre mobile reste celle du produit existant.

## Système visuel

- fond éditorial clair, structure bleu nuit ;
- vert Robin réservé à la disponibilité, jamais au gain ;
- violet pour la définition/recherche ;
- orange pour la preuve ouverte et les gates ;
- Georgia pour les titres, Geist pour l’interface, monospace pour les codes ;
- couleur toujours accompagnée d’un texte, d’un symbole ou d’un statut ;
- animation neutralisée avec `prefers-reduced-motion: reduce` ;
- focus visible sur liens et région de table.

Les jetons autoritatifs restent ceux de `cockpit/app/globals.css`; `docs/ux/DESIGN-SYSTEM.md` en fournit la lecture humaine synchronisée.

## Français et anglais

`fr-FR` reste la seule langue publique. Tous les nouveaux textes de présentation du Desk existent avec les mêmes clés dans `fr-FR.ts` et `en-GB.ts`. Le catalogue anglais reste non exposé jusqu’à sa revue linguistique et réglementaire. Les identifiants techniques (`E0`, `UNKNOWN`, noms de gates et classes temporelles) ne sont pas traduits artificiellement.

## Règles d’activation du cockpit complet

Les écrans de classement, fiche hypothèse, courbe pari par pari, analyse annuelle, généalogie, liste de matchs et comparateur ne peuvent être ouverts que si :

1. des cellules réelles sont fermées par le contrat E1/E2 puis E3 ;
2. au moins une famille devient calculable ;
3. le pilote hypergraphe est autorisé et produit des candidats auditables ;
4. les corrections de multiplicité, stabilité et red-team sont closes ;
5. un ensemble d’appartenance prospective est gelé ;
6. une autorisation distincte ouvre la publication.

## Hors périmètre

- aucun ROI, profit, drawdown, cote, classement ou comparateur ;
- aucun backtest ou calcul hypergraphe ;
- aucune donnée fournisseur nouvelle ;
- aucun replay, achat, pari réel, promotion ou publication sociale ;
- aucun déploiement Sites ;
- aucune affirmation de disponibilité P0 empirique.
