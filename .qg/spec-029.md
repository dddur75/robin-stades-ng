# 029-robin-stades-ng — « détail absolu » : toute la donnée API-Football

**Projet :** Robin des Stades NG
**Construit :** Codex · **Relit :** Claude (boucle horaire) · **Fusionne :** la boucle (ordre de David du 2026-10-17)
**Statut :** En construction

## Ce que veut David (ses mots, 2026-10-18 à 11 h 45)

« avant tout, il faut aller chercher la totalité des données partout...
Grande ligues, petite ligue, détail absolue de la totalité des datas »

## Périmètre (phases, une PR de ≤ 400 lignes de code par phase, mêmes règles que la 028)

Réutiliser le circuit existant : workflow 71, collecteur `historical_deep`,
réservations R2 atomiques, reçus publics, un appel par match et par famille,
marqueur durable par (fixture, famille), reprise sans rappel.

- **Phase A — statistiques du top 5.** `/fixtures/statistics` des 7 228 matchs
  de la mission 027 (Premier League, LaLiga, Serie A, Bundesliga 2020-2024,
  liste figée, empreinte `4e471c16b27b3ce5deaa8602795eb687f4e812975265d720c5697d4ce6bd288c`).
  ≈ 7 228 appels.
- **Phase B — événements.** `/fixtures/events` (buts avec minute et buteur,
  cartons, remplacements, VAR) de TOUS les matchs déjà rapprochés : 60 437 de
  la 028 + 7 228 de la 027 + ~2 450 de Ligue 1 déjà en archive. ≈ 70 100 appels.
  Au passage, stocker UNE fois les payloads complets `/fixtures?league&season`
  des 33 petites ligues 2019-2024 (~200 appels) : arbitre, stade, horaire exact
  n'existent pas dans nos archives pour ces ligues.
- **Phase C — joueurs.** `/fixtures/players` (stats individuelles par match :
  minutes, note, tirs, passes, duels) des mêmes matchs. ≈ 70 100 appels.
- **Phase D — extension 2015-2019.** Calendriers (`/fixtures?league&season`)
  puis lineups + statistics + events + players pour E0, D1, I1, SP1
  (saisons 2015 à 2018) et F1 (2015 à 2018), selon disponibilité réelle du
  fournisseur (le reçu dit ce qui n'existe pas). ≈ 36 500 appels.
- **Phase E — hebdomadaire 2026-27.** Chaque semaine, statistics + events des
  matchs JOUÉS de la semaine des 5 ligues suivies (~100 appels/semaine), par le
  déclenchement planifié existant du workflow 71. Jamais la saison 2025.

## Plafonds (durs, écrits dans le code, testés aux bornes)

- 240 000 appels au total pour la mission (compteur durable R2).
- 130 000 appels par jour UTC, PARTAGÉS avec tout autre usage du workflow 71.
- Réserve de 5 000 sur le quota restant du fournisseur, `/status` selon le
  budget existant (49/jour, 925 au total, réutilisation ≥ 110 min).
- **Saison 2025 (holdout 2025-26) : aucun appel, aucune lecture, aucune ligne.**

## Définition de « terminé »

- [ ] Reçus publics par phase : appels, matchs complets, manquants côté
      fournisseur, empreintes des listes, quota restant.
- [ ] ≥ 90 % des matchs ciblés avec événements complets, ≥ 85 % avec stats
      joueurs (les petites ligues anciennes sont trouées : le reçu le chiffre).
- [ ] Parquet append-only sur historical-data, mêmes conventions que la 028.
- [ ] Phase E : deux reçus hebdomadaires consécutifs sous 150 appels.

## Hors périmètre

Crédits The Odds API (liste C), paris, saison 2025-26, toute écriture Neon,
tout nouveau workflow, `prospective-deep-scheduler.yml`, robin-core.
