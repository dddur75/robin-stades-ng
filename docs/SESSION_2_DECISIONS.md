# SESSION 2 — Registre d'hypothèses Track A
**Robin des Stades NG — Comité des 30 — 2026-07-06**
**Objet :** transformer les 97 stratégies du catalogue en espace d'hypothèses propre, composable et pré-enregistré.
**Seuils de vote (delta 10) :** noyau protocolaire ≥ 90 % · features ≥ 75 %.

---

## Présents (30)
Domaine : archétype Bloom, archétype Benham, 3 quants trading sportif, 2 modélisateurs xG, 2 market makers, 1 trader syndicat asiatique.
Technique : architecte GitHub Actions, ingénieur data, expert ML, expert API/cotes, QA-recetteur, installateur, pro GitHub, expert scraping.
Statistique : statisticien FDR, spécialiste inférence causale, expert backtest walk-forward.
Wildcards : von Neumann, de Vinci, Musk, Altman, Zuckerberg, 1 psychologue du sport, 1 ancien arbitre pro, 1 journaliste data, 1 daily-fantasy shark, 1 actuaire.

---

## Décisions adoptées

**D1 — Grammaire atomique composable (noyau) — 97 %**
Toute stratégie est décomposée en atomes `self / adv / match`, chacun avec définition mécanique, source et tier. Les combinaisons se testent par produit d'atomes. *Proposeur : architecte + archétype Bloom.*

**D2 — Fenêtres temporelles (feature) — 83 %**
L5 = 5 derniers matchs de championnat. Tendances = L5 vs matchs 6-10. Les matchs de coupe n'entrent pas dans les fenêtres de forme en v1 (bruit de rotation), sauf atomes POST_EUROPE. *Proposeur : quant CLV.*

**D3 — Définition "joueur clé" (noyau) — 91 %**
Clé = top-3 minutes jouées à son poste sur la saison glissante OU top-3 valeur marchande de l'effectif OU ≥ 40 % des buts (pour un buteur). Définition figée avant tout backtest Tier B. *Proposeur : ingénieur data.*

**D4 — Moteur d'enjeu mathématique (noyau) — 94 %**
Les états SANS_ENJEU, LUTTE_*, RELEGUE_MATH, MONTEE_ASSUREE, etc. sont **calculés** depuis le classement point-in-time et les matchs restants (formules dans le registre). Aucune appréciation manuelle. *Proposeur : statisticien FDR.*

**D5 — Météo : seuils et source (feature) — 78 %**
Open-Meteo archive + coordonnées GPS des stades. Extrême = T ≤ 0 °C ou ≥ 32 °C, vent ≥ 40 km/h, pluie ≥ 8 mm/3 h à l'heure du coup d'envoi. Tier Bm, vague 2 au plus tôt. *Proposeur : wildcard Musk.*

**D6 — Parking pelouse & pression médiatique (noyau) — 96 %**
Aucune source propre et datée pour l'état des pelouses ni pour la "pression médiatique". S020, S034, S098, S099 → PARKING. Réouverture possible si une source vérifiable apparaît. *Proposeur : QA-recetteur.*

**D7 — Rejet des stratégies live (noyau) — 100 %**
S055, S086, S088 violent les règles opératoires de David (pas de live, verrou J-1). REJET définitif pour l'exécution. L'ancien arbitre note qu'elles restent convertibles en variantes pré-match — déjà couvertes par ENCAISSE_MT1 / FORT_MT2.

**D8 — Atome ARBITRE_SEVERE (feature) — 81 %**
La colonne Referee de football-data permet un profil cartons par arbitre sur 2 saisons. Croisé avec DERBY_CHAUD → HC-10. Wildcard adopté. *Proposeur : von Neumann, appuyé par l'ancien arbitre pro.*

**D9 — Paires contradictoires testées en duel (noyau) — 92 %**
Le catalogue affirme A et non-A sur quatre thèmes (relégué démobilisé S079 vs relégué libéré S081 ; post-Europe positif S035 vs négatif S036 ; coach neuf S004 vs S009 ; revanche S024 vs traumatisme S044). Preuve que ce sont des hypothèses, pas des connaissances. Les deux branches sont backtestées, la donnée cherche la condition qui sépare les régimes. *Proposeur : statisticien FDR.*

**D10 — Séquence homme → machine (noyau) — 95 %**
Vague 1 = hypothèses pré-enregistrées ci-dessus (mono-atomes Tier A/A* + 13 composées P1). Vague 2 = exploration combinatoire **automatique** de l'espace des atomes (profondeur ≤ 3, FDR Benjamini-Hochberg q = 0.10, N ≥ 300 out-of-sample, holdout 2025-26 scellé). La grammaire atomique EST l'espace de recherche de la machine — la question "le comité ou l'application ?" est donc résolue : le comité fabrique l'espace, l'application y chasse. *Proposeur : archétype Benham.*

**D11 — Statuts et honnêteté (noyau) — 100 %**
Les justifications ROI du catalogue source sont réputées fictives. Toute entrée du registre porte le statut NON-TESTÉ / TESTABLE / ATTENTE_DATA / PARKING / REJET. Aucun chiffre de ROI ne figure dans le registre tant que le backtest n'a pas parlé.

---

## Propositions rejetées

**R1 — Passer directement au modèle ML (gradient boosting) — 58 % (< 75 %)**
L'expert ML proposait de sauter les règles et d'entraîner un modèle sur toutes les features. Rejeté : Track B reste en v2, après que l'infrastructure de validation a fait ses preuves sur des règles interprétables (delta 8). Le comité note que les atomes serviront de features au futur modèle — rien n'est perdu.

**R2 — Étendre immédiatement aux ligues sud-américaines et asiatiques — 41 %**
Wildcard scope-creep classique. Rejeté : tiering delta 3 inchangé. Réexamen après premiers signaux validés.

---

## Sortie de session
- `registre_hypotheses_v1.yaml` : 70 atomes · 97 stratégies mappées (dont 12 fusions, 4 parking, 3 rejets live) · 25 hypothèses composées (13 P1, 9 P2, 3 P3) · cadre vague 2 machine.
- Prochaine étape : **Sprint 1 (3-5 j)** — pipeline football-data + Understat + moteur d'enjeu + backtest vague 1 (Tier A/A*), rapport lift + CLV avec intervalles de confiance et N par hypothèse.
