# Prompt — Ultra Scientific Review Before Triples

Travaille en raisonnement **Ultra**. Lis `NEXT-MISSION-BRIEF.md` et tous les
rapports Phase C liés par hash. Réalise une revue scientifique indépendante
des 80 propriétés et 120 paires : temporalité, UNKNOWN, folds, baselines,
enfant-parents, multiplicité, contrôles négatifs, concentrations et résultats
extrêmes.

Propose au plus un sous-espace borné de triples, puis gèle sa liste canonique,
son dénominateur de tests, son budget, ses shards, ses checkpoints et ses
critères d’arrêt. **N’exécute aucun triple** si une seule condition du brief
reste ouverte. N’autorise ni prix, ROI, stratégie, pari, déploiement, appel
fournisseur, SQL ni effet R2 sans un nouveau contrat explicite. Le résultat
attendu est une décision `AUTHORIZE_BOUNDED_TRIPLE_REVIEW` ou
`KEEP_TRIPLE_SEARCH_LOCKED`, jamais une promotion automatique.

## En-tête historique conservé pour la chaîne de preuves

```text
MODÈLE = GPT-5.6 Sol
RAISONNEMENT = Très élevé
DURÉE = 20 à 50 heures utiles
r2_read_budget = 10000 GET
r2_write_budget = 0
api_football_budget = 0
sql_read_budget = 0
TRIPLE_SEARCH_LOCKED = true
```

Ces valeurs décrivent le plafond de l’ancien contrat E3, pas une autorisation
pour la prochaine mission : le contrat Phase C courant impose zéro lecture R2.
Ne lancer ni E1A ni une troisième architecture. Conserver
`configs/data/capability-scoped-evidence-ladder-v2.json` comme preuve
historique et ne jamais lancer de triple avant la décision Ultra.

Ne jamais lancer de triple sans autorisation explicite du successeur append-only.
