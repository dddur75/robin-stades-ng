# RAPPORT VAGUE 2B — recherche machine, reference AJUSTEE

_Genere le 2026-07-24 12:12_

**Espace** : 7841 combinaisons canoniques · 13152 tests (N>=300) · FDR q=0.1 · seuil rapport |Δaj|>=3 pts · holdout : ['2025-26']
**Reference** : buckets force x tempo x venue (probas de cloture de-viggees) · lignes sans cote exploitable exclues : 0.0%
**Survivants reportables** : 374

> Δ ajuste = ecart aux matchs COMPARABLES (meme force, meme tempo, meme venue).
> Δ brut = l'ancien calcul v1 (vs moyenne de ligue) — affiche pour voir l'artefact.
> Un Δ ajuste ~0 avec un Δ brut enorme = le prix principal savait deja.

| Combo | Marche | N | Obs % | Ref aj. % | Δ ajuste | Δ brut (v1) | p | Blocs |
|---|---|---|---|---|---|---|---|---|
| DERBY_CHAUD | O45_CARTONS | 314 | 63.1 | 38.3 | +24.7 pts | +18.0 pts | 0.0e+00 | 2/2 |
| DERBY | O45_CARTONS | 488 | 58.0 | 37.4 | +20.6 pts | +17.1 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_EQUIPE_CARTONS x H2H_BTTS | O45_CARTONS | 346 | 60.4 | 40.0 | +20.4 pts | +7.5 pts | 6.7e-15 | 2/2 |
| EQUIPE_CARTONS x adv_EQUIPE_CARTONS | O45_CARTONS | 3226 | 59.6 | 39.2 | +20.4 pts | +5.0 pts | 0.0e+00 | 3/3 |
| FORT_MT2 x DERBY | O45_CARTONS | 324 | 57.1 | 37.0 | +20.1 pts | +17.1 pts | 5.4e-14 | 3/3 |
| SOLIDE_MT1 x adv_EQUIPE_CARTONS x MATCH_A_ENJEU | O45_CARTONS | 312 | 58.3 | 38.3 | +20.0 pts | +8.5 pts | 2.4e-13 | 3/3 |
| REPOS_LONG x DERBY | O45_CARTONS | 373 | 56.8 | 37.4 | +19.4 pts | +17.0 pts | 7.5e-15 | 3/3 |
| EQUIPE_CARTONS x FIN_SAISON_FORTE_HISTO | O45_CARTONS | 404 | 56.7 | 37.6 | +19.1 pts | +3.5 pts | 1.1e-15 | 2/2 |
| FORT_MT2 x adv_EQUIPE_CARTONS x MATCH_A_ENJEU | O45_CARTONS | 348 | 55.7 | 36.9 | +18.9 pts | +6.9 pts | 2.1e-13 | 3/3 |
| ATTAQUE_PROLIFIQUE x DERBY | O45_CARTONS | 325 | 55.4 | 36.7 | +18.7 pts | +16.1 pts | 2.2e-12 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_TRES_LONG x MATCH_A_ENJEU | O45_CARTONS | 370 | 55.9 | 37.8 | +18.1 pts | +7.5 pts | 4.6e-13 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_LONG x MATCH_A_ENJEU | O45_CARTONS | 645 | 55.8 | 38.0 | +17.8 pts | +7.8 pts | 0.0e+00 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_EQUIPE_CARTONS x MATCH_A_ENJEU | O45_CARTONS | 331 | 53.8 | 36.3 | +17.5 pts | +4.2 pts | 2.4e-11 | 3/3 |
| REPOS_LONG x adv_REPOS_LONG x DERBY | O45_CARTONS | 300 | 54.7 | 37.3 | +17.4 pts | +15.8 pts | 4.3e-10 | 3/3 |
| EQUIPE_CARTONS x MATCH_A_ENJEU | O45_CARTONS | 1029 | 55.4 | 38.3 | +17.1 pts | +7.0 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_EQUIPE_CARTONS x FENETRE_FIN_SAISON | O45_CARTONS | 561 | 55.3 | 38.3 | +17.0 pts | -0.4 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_EQUIPE_CARTONS x H2H_UNDER25 | O45_CARTONS | 398 | 58.3 | 41.5 | +16.8 pts | +2.7 pts | 7.5e-12 | 2/2 |
| EQUIPE_CARTONS x adv_FAIBLE_DOMICILE | O45_CARTONS | 1031 | 56.9 | 40.2 | +16.8 pts | +7.8 pts | 0.0e+00 | 3/3 |
| POST_DEFAITE_LOURDE x adv_EQUIPE_CARTONS | O45_CARTONS | 1246 | 54.8 | 38.9 | +15.9 pts | +6.0 pts | 0.0e+00 | 3/3 |
| SERIE_NULS x EQUIPE_CARTONS | O45_CARTONS | 302 | 54.3 | 39.2 | +15.2 pts | +4.1 pts | 5.6e-08 | 3/3 |
| EQUIPE_CARTONS x adv_LUTTE_MAINTIEN x MATCH_A_ENJEU | O45_CARTONS | 401 | 54.6 | 39.7 | +15.0 pts | +5.9 pts | 7.5e-10 | 3/3 |
| POST_DEFAITE_LOURDE x EQUIPE_CARTONS | O45_CARTONS | 1295 | 53.1 | 38.6 | +14.5 pts | +4.8 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x DOMINE_FAIBLES | O45_CARTONS | 1065 | 51.6 | 37.2 | +14.4 pts | +0.8 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_TRES_LONG x H2H_UNDER25 | O45_CARTONS | 514 | 55.1 | 41.2 | +13.9 pts | +3.8 pts | 1.3e-10 | 2/2 |
| ENCAISSE_MT1 x EQUIPE_CARTONS | O45_CARTONS | 2813 | 51.9 | 38.2 | +13.7 pts | +3.7 pts | 0.0e+00 | 3/3 |
| SERIE_VICTOIRES x adv_EQUIPE_CARTONS | O45_CARTONS | 1183 | 49.8 | 36.1 | +13.7 pts | +0.2 pts | 0.0e+00 | 3/3 |
| ENCAISSE_MT1 x adv_EQUIPE_CARTONS | O45_CARTONS | 2513 | 52.4 | 38.8 | +13.6 pts | +3.8 pts | 0.0e+00 | 3/3 |
| O15_MT1_FREQ x EQUIPE_CARTONS | O45_CARTONS | 1727 | 51.5 | 38.0 | +13.6 pts | +3.4 pts | 0.0e+00 | 3/3 |
| SERIE_VICTOIRES x EQUIPE_CARTONS | O45_CARTONS | 702 | 51.1 | 37.7 | +13.4 pts | +1.2 pts | 1.4e-13 | 3/3 |
| POST_VICTOIRE_LARGE x EQUIPE_CARTONS | O45_CARTONS | 809 | 51.1 | 37.7 | +13.4 pts | +1.9 pts | 2.7e-15 | 3/3 |
| DEFENSE_PASSOIRE x adv_EQUIPE_CARTONS | O45_CARTONS | 2337 | 51.8 | 38.5 | +13.3 pts | +3.5 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x FAIBLE_EXTERIEUR | O45_CARTONS | 2487 | 51.2 | 38.0 | +13.3 pts | +2.3 pts | 0.0e+00 | 3/3 |
| DEFENSE_PASSOIRE x EQUIPE_CARTONS | O45_CARTONS | 2791 | 51.1 | 37.9 | +13.2 pts | +3.0 pts | 0.0e+00 | 3/3 |
| SERIE_SANS_V x adv_EQUIPE_CARTONS | O45_CARTONS | 2913 | 52.5 | 39.3 | +13.2 pts | +3.7 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_DOMINE_FAIBLES x FENETRE_FIN_SAISON | O45_CARTONS | 344 | 47.4 | 34.2 | +13.2 pts | -3.2 pts | 2.0e-07 | 3/3 |
| O15_MT1_FREQ x adv_EQUIPE_CARTONS | O45_CARTONS | 1886 | 50.6 | 37.5 | +13.1 pts | +2.2 pts | 0.0e+00 | 3/3 |
| FIN_SAISON_FORTE_HISTO x MATCH_A_ENJEU | O45_CARTONS | 342 | 48.8 | 35.9 | +12.9 pts | +7.9 pts | 4.7e-07 | 2/2 |
| REPRISE_FORME x EQUIPE_CARTONS | O45_CARTONS | 687 | 51.4 | 38.5 | +12.9 pts | +3.1 pts | 2.7e-12 | 3/3 |
| POST_VICTOIRE_LARGE x adv_EQUIPE_CARTONS | O45_CARTONS | 1261 | 49.3 | 36.4 | +12.9 pts | +0.6 pts | 0.0e+00 | 3/3 |
| SERIE_V_LONGUE x adv_EQUIPE_CARTONS | O45_CARTONS | 489 | 47.4 | 34.6 | +12.9 pts | -3.0 pts | 1.5e-09 | 3/3 |
| CRISE_OFFENSIVE x adv_EQUIPE_CARTONS | O45_CARTONS | 1160 | 52.4 | 39.6 | +12.8 pts | +3.6 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x STADE_FERME | O45_CARTONS | 840 | 50.2 | 37.4 | +12.8 pts | -0.0 pts | 1.0e-14 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_TRES_LONG | O45_CARTONS | 4655 | 51.3 | 38.5 | +12.8 pts | +2.4 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_LUTTE_MAINTIEN x FENETRE_FIN_SAISON | O45_CARTONS | 660 | 52.0 | 39.2 | +12.7 pts | +2.9 pts | 1.7e-11 | 3/3 |
| SOLIDE_MT1 x adv_EQUIPE_CARTONS x H2H_UNDER25 | O45_CARTONS | 419 | 53.9 | 41.2 | +12.7 pts | +4.0 pts | 1.1e-07 | 2/2 |
| EQUIPE_CARTONS x adv_LUTTE_MAINTIEN | O45_CARTONS | 956 | 52.0 | 39.3 | +12.7 pts | +2.7 pts | 8.9e-16 | 3/3 |
| FORT_MT2 x EQUIPE_CARTONS | O45_CARTONS | 2376 | 50.8 | 38.1 | +12.7 pts | +1.4 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x REPOS_TRES_LONG | O45_CARTONS | 4611 | 51.3 | 38.6 | +12.6 pts | +2.3 pts | 0.0e+00 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_ATTAQUE_PROLIFIQUE x MATCH_A_ENJEU | O45_CARTONS | 316 | 49.1 | 36.4 | +12.6 pts | +11.2 pts | 2.8e-06 | 3/3 |
| EQUIPE_CARTONS x LUTTE_MAINTIEN | O45_CARTONS | 1231 | 50.9 | 38.3 | +12.6 pts | +1.0 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x FAIBLE_DOMICILE | O45_CARTONS | 1292 | 52.3 | 39.8 | +12.5 pts | +3.4 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_STADE_FERME | O45_CARTONS | 964 | 48.2 | 35.8 | +12.4 pts | -1.9 pts | 4.4e-16 | 3/3 |
| FORT_MT1 x EQUIPE_CARTONS | O45_CARTONS | 2131 | 50.3 | 37.9 | +12.3 pts | +1.7 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_DOMINE_FAIBLES | O45_CARTONS | 1534 | 48.0 | 35.7 | +12.3 pts | -2.1 pts | 0.0e+00 | 3/3 |
| SCORING_FOU x adv_EQUIPE_CARTONS | O45_CARTONS | 1316 | 48.9 | 36.7 | +12.2 pts | +1.2 pts | 0.0e+00 | 3/3 |
| ATTAQUE_PROLIFIQUE x EQUIPE_CARTONS | O45_CARTONS | 1808 | 49.4 | 37.3 | +12.1 pts | +0.7 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_FAIBLE_EXTERIEUR | O45_CARTONS | 2268 | 50.9 | 38.8 | +12.1 pts | +1.5 pts | 0.0e+00 | 3/3 |
| SOLIDE_MT1 x adv_EQUIPE_CARTONS | O45_CARTONS | 3461 | 50.2 | 38.1 | +12.1 pts | +1.2 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_FIN_SAISON_FORTE_HISTO | O45_CARTONS | 609 | 47.5 | 35.4 | +12.1 pts | -3.5 pts | 3.1e-10 | 2/2 |
| SCORING_FOU x EQUIPE_CARTONS | O45_CARTONS | 1172 | 49.5 | 37.4 | +12.1 pts | +2.0 pts | 0.0e+00 | 3/3 |
| CRISE_OFFENSIVE x EQUIPE_CARTONS | O45_CARTONS | 1247 | 51.2 | 39.2 | +12.0 pts | +2.3 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x FAIBLE_VS_TOP | O45_CARTONS | 693 | 49.9 | 37.9 | +12.0 pts | +0.7 pts | 5.4e-11 | 3/3 |
| FORT_MT2 x adv_FORT_MT2 x MATCH_A_ENJEU | O45_CARTONS | 307 | 48.5 | 36.6 | +11.9 pts | +9.9 pts | 1.2e-05 | 3/3 |
| SOLIDE_MT1 x EQUIPE_CARTONS | O45_CARTONS | 2996 | 50.6 | 38.7 | +11.8 pts | +1.5 pts | 0.0e+00 | 3/3 |
| SERIE_SANS_V x EQUIPE_CARTONS | O45_CARTONS | 3426 | 50.4 | 38.7 | +11.7 pts | +2.0 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_FAIBLE_VS_TOP | O45_CARTONS | 576 | 50.5 | 38.8 | +11.7 pts | +1.5 pts | 6.3e-09 | 3/3 |
| U05_MT1_FREQ x adv_EQUIPE_CARTONS | O45_CARTONS | 1459 | 51.2 | 39.5 | +11.7 pts | +2.1 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_FORTERESSE | O45_CARTONS | 386 | 43.8 | 32.1 | +11.7 pts | -8.5 pts | 6.6e-07 | 3/3 |
| EQUIPE_CARTONS x REPOS_LONG | O45_CARTONS | 8232 | 50.2 | 38.5 | +11.7 pts | +2.4 pts | 0.0e+00 | 3/3 |
| FORT_MT1 x adv_EQUIPE_CARTONS | O45_CARTONS | 2626 | 48.4 | 36.9 | +11.6 pts | -0.1 pts | 0.0e+00 | 3/3 |
| U05_MT1_FREQ x EQUIPE_CARTONS | O45_CARTONS | 1458 | 50.6 | 39.3 | +11.3 pts | +1.6 pts | 0.0e+00 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_EQUIPE_CARTONS | O45_CARTONS | 2830 | 47.1 | 35.9 | +11.2 pts | -1.4 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_LONG | O45_CARTONS | 8239 | 49.6 | 38.4 | +11.2 pts | +1.9 pts | 0.0e+00 | 3/3 |
| SOLIDE_MT1 x adv_EQUIPE_CARTONS x H2H_BTTS | O45_CARTONS | 416 | 49.8 | 38.7 | +11.1 pts | +1.7 pts | 3.0e-06 | 2/2 |
| FORT_MT2 x adv_EQUIPE_CARTONS | O45_CARTONS | 3270 | 48.0 | 37.1 | +10.9 pts | -0.7 pts | 0.0e+00 | 3/3 |
| STADE_FERME x adv_DOMINE_FAIBLES | O45_CARTONS | 331 | 47.7 | 36.9 | +10.8 pts | +6.8 pts | 4.2e-05 | 3/3 |
| POST_VICTOIRE_SURPRISE x EQUIPE_CARTONS | O45_CARTONS | 1561 | 49.5 | 39.0 | +10.5 pts | +1.9 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS | O45_CARTONS | 12906 | 48.9 | 38.5 | +10.4 pts | +1.4 pts | 0.0e+00 | 3/3 |
| POST_VICTOIRE_SURPRISE x adv_EQUIPE_CARTONS | O45_CARTONS | 1384 | 49.8 | 39.4 | +10.4 pts | +1.7 pts | 1.8e-15 | 3/3 |
| STADE_FERME x adv_REPOS_LONG x MATCH_A_ENJEU | O45_CARTONS | 342 | 46.2 | 35.9 | +10.3 pts | +6.5 pts | 5.8e-05 | 3/3 |
| SERIE_VICTOIRES x adv_DOMINE_FAIBLES | O45_CARTONS | 430 | 46.3 | 36.0 | +10.3 pts | +6.9 pts | 7.5e-06 | 3/3 |
| FORT_MT2 x adv_EQUIPE_CARTONS x H2H_UNDER25 | O45_CARTONS | 324 | 50.0 | 39.9 | +10.1 pts | +0.5 pts | 1.9e-04 | 2/2 |
| EQUIPE_CARTONS x adv_REPOS_TRES_LONG x H2H_BTTS | O45_CARTONS | 580 | 49.0 | 38.9 | +10.1 pts | +1.2 pts | 5.7e-07 | 2/2 |
| REPRISE_FORME x adv_EQUIPE_CARTONS | O45_CARTONS | 593 | 48.6 | 38.7 | +9.8 pts | +0.2 pts | 7.8e-07 | 3/3 |
| SOLIDE_MT1 x adv_REPOS_TRES_LONG x H2H_UNDER25 | O45_CARTONS | 395 | 50.4 | 40.6 | +9.8 pts | +7.6 pts | 7.1e-05 | 2/2 |
| STADE_FERME x MATCH_A_ENJEU | O45_CARTONS | 528 | 45.8 | 36.1 | +9.8 pts | +5.9 pts | 2.4e-06 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_FORT_MT2 x MATCH_A_ENJEU | O45_CARTONS | 490 | 46.1 | 36.4 | +9.7 pts | +7.7 pts | 6.4e-06 | 3/3 |
| DOMINE_FAIBLES x adv_DOMINE_FAIBLES | O45_CARTONS | 362 | 45.9 | 36.1 | +9.7 pts | +7.0 pts | 1.1e-04 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_TRES_LONG x FENETRE_FIN_SAISON | O45_CARTONS | 641 | 47.4 | 37.7 | +9.7 pts | -1.2 pts | 3.3e-07 | 3/3 |
| SOLIDE_MT1 x adv_DOMINE_FAIBLES x FENETRE_FIN_SAISON | O35 | 318 | 44.0 | 34.5 | +9.5 pts | +13.8 pts | 2.8e-04 | 3/3 |
| SERIE_V_LONGUE x adv_ATTAQUE_PROLIFIQUE | O45_CARTONS | 373 | 44.5 | 35.0 | +9.5 pts | +5.6 pts | 1.1e-04 | 3/3 |
| FORT_MT1 x adv_EQUIPE_CARTONS x MATCH_A_ENJEU | MT2_SELF | 301 | 49.8 | 40.4 | +9.5 pts | +17.1 pts | 4.3e-04 | 3/3 |
| SOLIDE_MT1 x adv_EQUIPE_CARTONS x FENETRE_FIN_SAISON | O45_CARTONS | 653 | 46.6 | 37.1 | +9.5 pts | -4.4 pts | 4.6e-07 | 3/3 |
| FORT_MT1 x adv_EQUIPE_CARTONS x H2H_BTTS | O45_CARTONS | 367 | 47.1 | 37.7 | +9.4 pts | +0.2 pts | 1.8e-04 | 2/2 |
| U15_FREQ x adv_EQUIPE_CARTONS | O45_CARTONS | 933 | 49.3 | 39.9 | +9.4 pts | -0.2 pts | 3.5e-09 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU | BTTS_Y | 461 | 63.3 | 54.0 | +9.4 pts | +9.7 pts | 4.9e-05 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU x FENETRE_FIN_SAISON | BTTS_Y | 461 | 63.3 | 54.0 | +9.4 pts | +9.7 pts | 4.9e-05 | 3/3 |
| EQUIPE_CARTONS x adv_LUTTE_TITRE | O45_CARTONS | 309 | 43.0 | 33.7 | +9.3 pts | -7.4 pts | 4.3e-04 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_LONG x H2H_UNDER25 | O45_CARTONS | 910 | 50.5 | 41.2 | +9.3 pts | +1.1 pts | 9.9e-09 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_EQUIPE_CARTONS x H2H_BTTS | O45_CARTONS | 449 | 46.5 | 37.3 | +9.3 pts | -1.4 pts | 4.1e-05 | 2/2 |
| SERIE_SANS_V x adv_EQUIPE_CARTONS x H2H_UNDER25 | O45_CARTONS | 345 | 50.7 | 41.5 | +9.3 pts | +0.0 pts | 4.6e-04 | 2/2 |
| FAIBLE_EXTERIEUR x adv_FAIBLE_VS_TOP | O45_CARTONS | 320 | 47.8 | 38.8 | +9.0 pts | +8.6 pts | 9.6e-04 | 3/3 |
| U15_FREQ x REPOS_COURT | O45_CARTONS | 823 | 30.6 | 39.5 | -8.9 pts | -4.6 pts | 1.4e-07 | 3/3 |
| EQUIPE_CARTONS x H2H_UNDER25 | O45_CARTONS | 1431 | 50.0 | 41.1 | +8.9 pts | +1.0 pts | 6.3e-12 | 3/3 |
| U05_MT1_FREQ x adv_REPOS_LONG x MATCH_A_ENJEU | O45_CARTONS | 331 | 48.0 | 39.2 | +8.9 pts | +9.6 pts | 8.7e-04 | 3/3 |
| SANS_ENJEU x adv_REPOS_LONG | TEAM_O15_SELF | 528 | 43.6 | 34.8 | +8.8 pts | +3.5 pts | 1.1e-05 | 3/3 |
| SANS_ENJEU x adv_REPOS_LONG x FENETRE_FIN_SAISON | TEAM_O15_SELF | 528 | 43.6 | 34.8 | +8.8 pts | +3.5 pts | 1.1e-05 | 3/3 |
| ENCAISSE_MT1 x adv_EQUIPE_CARTONS x FENETRE_FIN_SAISON | O45_CARTONS | 501 | 46.7 | 38.0 | +8.7 pts | -2.7 pts | 5.2e-05 | 3/3 |
| POST_VICTOIRE_LARGE x adv_REPOS_LONG x MATCH_A_ENJEU | O45_CARTONS | 401 | 44.9 | 36.2 | +8.7 pts | +8.7 pts | 2.6e-04 | 3/3 |
| FORT_MT2 x adv_EQUIPE_CARTONS x FENETRE_FIN_SAISON | O45_CARTONS | 627 | 45.1 | 36.5 | +8.7 pts | -4.2 pts | 5.6e-06 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU | O45_CARTONS | 461 | 27.3 | 35.9 | -8.6 pts | -9.4 pts | 1.1e-04 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU x FENETRE_FIN_SAISON | O45_CARTONS | 461 | 27.3 | 35.9 | -8.6 pts | -9.4 pts | 1.1e-04 | 3/3 |
| FORT_MT1 x adv_EQUIPE_CARTONS x MATCH_A_ENJEU | TEAM_O15_SELF | 301 | 55.5 | 46.9 | +8.6 pts | +17.0 pts | 1.5e-03 | 3/3 |
| FAIBLE_VS_TOP x FENETRE_FIN_SAISON | O45_CARTONS | 329 | 27.4 | 35.9 | -8.5 pts | -9.3 pts | 1.2e-03 | 3/3 |
| REPOS_LONG x adv_LUTTE_TITRE x FENETRE_FIN_SAISON | O45_CARTONS | 591 | 25.2 | 33.7 | -8.5 pts | -9.1 pts | 1.0e-05 | 3/3 |
| REPOS_LONG x SANS_ENJEU | BTTS_Y | 472 | 62.5 | 54.1 | +8.4 pts | +8.9 pts | 2.1e-04 | 3/3 |
| EQUIPE_CARTONS x adv_FAIBLE_EXTERIEUR x FENETRE_FIN_SAISON | O45_CARTONS | 461 | 46.2 | 37.8 | +8.4 pts | -3.7 pts | 1.7e-04 | 3/3 |
| FORT_MT2 x adv_FORT_MT2 x MATCH_A_ENJEU | O15_MT1 | 307 | 45.0 | 36.7 | +8.3 pts | +10.0 pts | 2.4e-03 | 3/3 |
| LUTTE_TITRE x adv_LUTTE_MAINTIEN | O45_CARTONS | 472 | 26.1 | 34.3 | -8.2 pts | -11.3 pts | 1.5e-04 | 2/3 |
| LUTTE_TITRE x adv_LUTTE_MAINTIEN x MATCH_A_ENJEU | O45_CARTONS | 472 | 26.1 | 34.3 | -8.2 pts | -11.3 pts | 1.5e-04 | 2/3 |
| FAIBLE_DOMICILE x H2H_BTTS | MT1_SELF | 434 | 36.2 | 28.0 | +8.1 pts | +2.6 pts | 1.2e-04 | 2/2 |
| U15_FREQ x adv_REPOS_COURT | O45_CARTONS | 849 | 31.3 | 39.4 | -8.1 pts | -3.9 pts | 1.1e-06 | 3/3 |
| SOLIDE_MT1 x adv_FORT_MT2 x MATCH_A_ENJEU | O45_CARTONS | 508 | 45.5 | 37.4 | +8.1 pts | +7.0 pts | 1.5e-04 | 2/3 |
| REPRISE_FORME x FENETRE_FIN_SAISON | O45_CARTONS | 517 | 29.0 | 37.1 | -8.1 pts | -9.8 pts | 1.2e-04 | 3/3 |
| FORT_MT2 x adv_FORTERESSE | O45_CARTONS | 352 | 42.9 | 34.8 | +8.1 pts | +2.3 pts | 1.3e-03 | 3/3 |
| POST_VICTOIRE_LARGE x MATCH_A_ENJEU | O45_CARTONS | 591 | 44.2 | 36.1 | +8.1 pts | +7.4 pts | 3.7e-05 | 3/3 |
| FORT_MT2 x adv_FIN_SAISON_FORTE_HISTO | O05_MT1 | 474 | 83.3 | 75.3 | +8.0 pts | +11.1 pts | 4.3e-05 | 2/2 |
| FORT_MT1 x adv_FORT_MT2 x MATCH_A_ENJEU | O45_CARTONS | 455 | 44.8 | 36.8 | +8.0 pts | +6.2 pts | 3.7e-04 | 3/3 |
| CRISE_OFFENSIVE x adv_SCORING_FOU | O35 | 350 | 38.6 | 30.6 | +8.0 pts | +7.9 pts | 9.3e-04 | 3/3 |
| U15_FREQ x EQUIPE_CARTONS | O45_CARTONS | 980 | 47.7 | 39.7 | +7.9 pts | -1.2 pts | 3.1e-07 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_LONG x H2H_BTTS | O45_CARTONS | 971 | 46.9 | 38.9 | +7.9 pts | +0.3 pts | 3.4e-07 | 3/3 |
| FORT_MT2 x adv_DOMINE_FAIBLES x FENETRE_FIN_SAISON | O45_CARTONS | 325 | 43.1 | 35.2 | +7.9 pts | +4.4 pts | 2.7e-03 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU x FENETRE_FIN_SAISON | CS_SELF | 528 | 22.7 | 30.6 | -7.9 pts | -3.8 pts | 5.3e-05 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU | CS_SELF | 528 | 22.7 | 30.6 | -7.9 pts | -3.8 pts | 5.3e-05 | 3/3 |
| REPOS_LONG x SANS_ENJEU | O45_CARTONS | 472 | 27.8 | 35.6 | -7.9 pts | -9.4 pts | 3.3e-04 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_FORT_MT1 x MATCH_A_ENJEU | O45_CARTONS | 372 | 44.4 | 36.5 | +7.8 pts | +7.1 pts | 1.6e-03 | 3/3 |
| SANS_ENJEU | O45_CARTONS | 809 | 28.6 | 36.4 | -7.8 pts | -9.7 pts | 3.2e-06 | 3/3 |
| SANS_ENJEU x FENETRE_FIN_SAISON | O45_CARTONS | 809 | 28.6 | 36.4 | -7.8 pts | -9.7 pts | 3.2e-06 | 3/3 |
| SOLIDE_MT1 x adv_LUTTE_TITRE | O45_CARTONS | 340 | 27.4 | 35.1 | -7.8 pts | -7.6 pts | 2.5e-03 | 2/3 |
| FAIBLE_DOMICILE x adv_REPOS_LONG x FENETRE_FIN_SAISON | O45_CARTONS | 504 | 30.4 | 38.1 | -7.7 pts | -5.8 pts | 3.2e-04 | 3/3 |
| DOMINE_FAIBLES x adv_REPOS_TRES_LONG x FENETRE_FIN_SAISON | TEAM_O15_SELF | 414 | 63.8 | 56.1 | +7.7 pts | +23.3 pts | 7.4e-04 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_SOLIDE_MT1 x FENETRE_FIN_SAISON | O35 | 540 | 40.9 | 33.3 | +7.6 pts | +10.9 pts | 1.2e-04 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU x FENETRE_FIN_SAISON | O35 | 461 | 40.6 | 33.0 | +7.6 pts | +8.1 pts | 4.2e-04 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU | O35 | 461 | 40.6 | 33.0 | +7.6 pts | +8.1 pts | 4.2e-04 | 3/3 |
| FAIBLE_EXTERIEUR x adv_REPOS_LONG x H2H_UNDER25 | O45_CARTONS | 496 | 48.0 | 40.4 | +7.6 pts | +4.5 pts | 5.4e-04 | 2/2 |
| REPOS_COURT x LUTTE_TITRE | O45_CARTONS | 342 | 27.8 | 35.3 | -7.6 pts | -10.8 pts | 3.1e-03 | 2/3 |
| POST_DEFAITE_LOURDE x adv_REPOS_LONG x H2H_BTTS | O05_MT1 | 356 | 78.9 | 71.4 | +7.5 pts | +6.5 pts | 1.6e-03 | 2/2 |
| ATTAQUE_PROLIFIQUE x adv_SOLIDE_MT1 x MATCH_A_ENJEU | O45_CARTONS | 469 | 44.6 | 37.1 | +7.5 pts | +6.5 pts | 7.1e-04 | 3/3 |
| SERIE_VICTOIRES x adv_REPOS_LONG x H2H_BTTS | O45_CARTONS | 382 | 43.7 | 36.2 | +7.5 pts | +4.6 pts | 2.1e-03 | 2/2 |
| ATTAQUE_PROLIFIQUE x adv_FORT_MT2 x H2H_BTTS | O45_CARTONS | 379 | 43.5 | 36.2 | +7.4 pts | +3.4 pts | 2.7e-03 | 2/2 |