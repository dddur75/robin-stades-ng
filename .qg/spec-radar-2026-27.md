# Radar de prix 2026-27 — mission papier

Source : demande de David dans ce chat, 20 octobre 2026 ; cadrage validé avec
une opportunité unique par (match, issue, book), au premier horizon de
franchissement **de chaque seuil**. Branche depuis main, une seule PR.

## Critères d'acceptation

- Réutiliser `src/robin/clv.py`, inchangé : fair normalisé du dernier triplet
  Pinnacle complet pré-match ; EV = prix FR × fair − 1.
- Compteurs EV>0, EV≥2%, EV≥5%, par semaine ISO de coup d'envoi UTC, book,
  bande de probabilité et premier horizon ; détail de chaque horizon séparé.
- EV moyenne et gain attendu brut de 10 € à chaque premier franchissement,
  sans jamais placer de pari ; dédupliquer aussi les imports manuels.
- Audit honnête des boosts dans les sources accessibles, chiffres et limites ;
  2–3 sources légitimes avec coûts, sans souscription ni aspiration automatique.
- CSV manuel : date UTC horodatée, book, match canonique, issue 1/N/2,
  cote_boostee, mise_max ; fair de clôture cohérent, prix strictement pré-match.
- Rapports `reports/radar/2026-27/SEMAINE-AAAA-WW.md` et cumul `RADAR.md` ;
  script `scripts/radar_hebdo.py` et nouveau workflow lundi matin + dispatch.
- Suivi quatre semaines ; borne de calcul 16/11 inclus, décision 17/11/2026.
- Tests connus : EV, déduplication par seuil, boost manuel, exclusion post-kickoff,
  reconstruction via le CLV, reproductibilité des exports.
- Premier rapport depuis les observations du 03/10 sur le stock déjà collecté,
  tableau des sources dans la PR ; pas de simulation dans les chiffres réels.

## Garde-fous et périmètre

Aucun pari, achat, nouvel abonnement, appel fournisseur, écriture Neon, opération
R2, modification de secrets, ni fusion. Pas de collecte directe ni de scraping.
L'unique nouveau workflow lit des artefacts GitHub et publie un artefact de rapport.
Intouchés : src/robin/clv.py, toute collecte et ses tests, tous les workflows et
configurations **existants**, matrice d'activation, budgets/verrous, données sources,
robin-core. Seuls le ledger append-only et une claim nouvelle complètent les preuves.
Codex est le rédacteur unique ; aucune revue indépendante n'est revendiquée.

## Résumé de livraison

- Fait : radar reproductible, CSV manuel, 32 tests ciblés verts, nouveau cron borné.
- Fait : premier cumul 74 EV+, 37 à ≥2%, 19 à ≥5%, compte unique par seuil.
- Fait : 3 141 lignes horizon réutilisées, 2 691 EV calculables ; fair/temps contrôlés.
- Fait : 0 boost manuel, labels non observables dans les exports, 3 sources proposées.
- Limite : accès Azure des archives refusé ; absence de boosts fournisseur non prouvée.
- Limite : couverture R2 non établie ; une exclusion de match héritée du CLV.
- Reste : revue indépendante, fusion, quatre runs puis décision du 17/11 ; aucune fusion ici.
