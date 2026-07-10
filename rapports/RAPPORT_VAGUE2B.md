# RAPPORT VAGUE 2B — recherche machine, reference AJUSTEE

_Genere le 2026-07-10 08:46_

**Espace** : 7855 combinaisons canoniques · 13420 tests (N>=300) · FDR q=0.1 · seuil rapport |Δaj|>=3 pts · holdout : ['2025-26']
**Reference** : buckets force x tempo x venue (probas de cloture de-viggees) · lignes sans cote exploitable exclues : 0.0%
**Survivants reportables** : 525

> Δ ajuste = ecart aux matchs COMPARABLES (meme force, meme tempo, meme venue).
> Δ brut = l'ancien calcul v1 (vs moyenne de ligue) — affiche pour voir l'artefact.
> Un Δ ajuste ~0 avec un Δ brut enorme = le prix principal savait deja.

| Combo | Marche | N | Obs % | Ref aj. % | Δ ajuste | Δ brut (v1) | p | Blocs |
|---|---|---|---|---|---|---|---|---|
| EQUIPE_CARTONS x adv_EQUIPE_CARTONS x MATCH_A_ENJEU | O45_CARTONS | 466 | 68.2 | 39.2 | +29.0 pts | +12.3 pts | 0.0e+00 | 3/3 |
| DERBY_CHAUD | O45_CARTONS | 314 | 63.1 | 38.3 | +24.7 pts | +18.0 pts | 0.0e+00 | 2/2 |
| SOLIDE_MT1 x adv_EQUIPE_CARTONS x MATCH_A_ENJEU | O45_CARTONS | 322 | 60.9 | 38.1 | +22.7 pts | +10.5 pts | 0.0e+00 | 3/3 |
| SOLIDE_MT1 x DERBY | O45_CARTONS | 324 | 59.6 | 37.7 | +21.8 pts | +18.2 pts | 4.4e-16 | 3/3 |
| REPOS_LONG x DERBY_CHAUD | O45_CARTONS | 413 | 59.8 | 38.3 | +21.5 pts | +15.6 pts | 0.0e+00 | 3/3 |
| FORT_MT2 x DERBY | O45_CARTONS | 427 | 58.1 | 36.8 | +21.3 pts | +18.1 pts | 0.0e+00 | 3/3 |
| DERBY | O45_CARTONS | 488 | 58.0 | 37.4 | +20.6 pts | +17.1 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_EQUIPE_CARTONS | O45_CARTONS | 6452 | 59.6 | 39.2 | +20.4 pts | +5.0 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_EQUIPE_CARTONS x H2H_BTTS | O45_CARTONS | 700 | 60.0 | 39.9 | +20.1 pts | +7.3 pts | 0.0e+00 | 2/2 |
| REPOS_LONG x adv_REPOS_LONG x DERBY_CHAUD | O45_CARTONS | 362 | 58.0 | 38.2 | +19.8 pts | +14.3 pts | 7.1e-15 | 3/3 |
| EQUIPE_CARTONS x MATCH_A_ENJEU | O45_CARTONS | 1222 | 58.3 | 38.6 | +19.8 pts | +8.4 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_LONG x MATCH_A_ENJEU | O45_CARTONS | 729 | 57.9 | 38.3 | +19.6 pts | +8.5 pts | 0.0e+00 | 3/3 |
| FORT_MT2 x adv_EQUIPE_CARTONS x MATCH_A_ENJEU | O45_CARTONS | 341 | 56.6 | 37.1 | +19.5 pts | +7.0 pts | 6.0e-14 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_TRES_LONG x MATCH_A_ENJEU | O45_CARTONS | 415 | 57.6 | 38.2 | +19.4 pts | +7.8 pts | 2.2e-16 | 3/3 |
| ATTAQUE_PROLIFIQUE x DERBY | O45_CARTONS | 448 | 55.8 | 36.5 | +19.3 pts | +16.9 pts | 0.0e+00 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_EQUIPE_CARTONS x MATCH_A_ENJEU | O45_CARTONS | 330 | 55.8 | 36.5 | +19.3 pts | +5.6 pts | 2.2e-13 | 3/3 |
| EQUIPE_CARTONS x FIN_SAISON_FORTE_HISTO | O45_CARTONS | 409 | 57.0 | 37.8 | +19.2 pts | +3.7 pts | 6.7e-16 | 2/2 |
| REPOS_LONG x DERBY | O45_CARTONS | 673 | 55.9 | 37.3 | +18.6 pts | +16.5 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_LUTTE_MAINTIEN x MATCH_A_ENJEU | O45_CARTONS | 513 | 57.7 | 39.8 | +17.9 pts | +7.3 pts | 0.0e+00 | 3/3 |
| FORT_MT1 x DERBY | O45_CARTONS | 342 | 54.4 | 36.8 | +17.6 pts | +15.0 pts | 1.2e-11 | 3/3 |
| REPOS_LONG x adv_REPOS_LONG x DERBY | O45_CARTONS | 600 | 54.7 | 37.2 | +17.5 pts | +15.8 pts | 0.0e+00 | 3/3 |
| REPOS_TRES_LONG x DERBY | O45_CARTONS | 402 | 54.5 | 37.1 | +17.4 pts | +15.4 pts | 4.2e-13 | 3/3 |
| REPOS_LONG x adv_REPOS_TRES_LONG x DERBY | O45_CARTONS | 384 | 54.2 | 37.1 | +17.1 pts | +15.0 pts | 3.1e-12 | 3/3 |
| EQUIPE_CARTONS x adv_EQUIPE_CARTONS x FENETRE_FIN_SAISON | O45_CARTONS | 1115 | 55.2 | 38.3 | +16.9 pts | -0.5 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_FAIBLE_DOMICILE | O45_CARTONS | 1031 | 56.9 | 40.0 | +16.9 pts | +7.8 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_EQUIPE_CARTONS x H2H_UNDER25 | O45_CARTONS | 824 | 58.0 | 41.5 | +16.5 pts | +3.0 pts | 0.0e+00 | 2/2 |
| ATTAQUE_PROLIFIQUE x adv_REPOS_LONG x DERBY | O45_CARTONS | 325 | 52.6 | 36.5 | +16.1 pts | +15.2 pts | 1.4e-09 | 3/3 |
| POST_DEFAITE_LOURDE x adv_EQUIPE_CARTONS | O45_CARTONS | 1265 | 54.9 | 38.8 | +16.0 pts | +6.0 pts | 0.0e+00 | 3/3 |
| SERIE_NULS x EQUIPE_CARTONS | O45_CARTONS | 303 | 54.5 | 39.4 | +15.0 pts | +4.3 pts | 7.2e-08 | 3/3 |
| POST_DEFAITE_LOURDE x EQUIPE_CARTONS | O45_CARTONS | 1314 | 53.1 | 38.6 | +14.6 pts | +4.8 pts | 0.0e+00 | 3/3 |
| FIN_SAISON_FORTE_HISTO x MATCH_A_ENJEU | O45_CARTONS | 360 | 50.8 | 36.3 | +14.5 pts | +9.3 pts | 8.0e-09 | 2/2 |
| EQUIPE_CARTONS x adv_LUTTE_MAINTIEN | O45_CARTONS | 1079 | 53.7 | 39.4 | +14.3 pts | +3.6 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x LUTTE_MAINTIEN | O45_CARTONS | 1352 | 52.7 | 38.5 | +14.2 pts | +2.3 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_TRES_LONG | O45_CARTONS | 5431 | 52.9 | 38.7 | +14.2 pts | +3.1 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x REPOS_TRES_LONG | O45_CARTONS | 5387 | 52.8 | 38.8 | +14.0 pts | +3.0 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x DOMINE_FAIBLES | O45_CARTONS | 1061 | 51.3 | 37.3 | +14.0 pts | -0.0 pts | 0.0e+00 | 3/3 |
| SERIE_VICTOIRES x adv_EQUIPE_CARTONS | O45_CARTONS | 1188 | 49.9 | 36.1 | +13.8 pts | +0.3 pts | 0.0e+00 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_ATTAQUE_PROLIFIQUE x MATCH_A_ENJEU | O45_CARTONS | 596 | 50.3 | 36.5 | +13.8 pts | +12.4 pts | 1.9e-12 | 3/3 |
| ENCAISSE_MT1 x EQUIPE_CARTONS | O45_CARTONS | 2921 | 51.9 | 38.3 | +13.7 pts | +3.5 pts | 0.0e+00 | 3/3 |
| SERIE_SANS_V x adv_EQUIPE_CARTONS | O45_CARTONS | 3099 | 53.0 | 39.4 | +13.6 pts | +3.9 pts | 0.0e+00 | 3/3 |
| SERIE_VICTOIRES x EQUIPE_CARTONS | O45_CARTONS | 707 | 51.3 | 37.7 | +13.6 pts | +1.4 pts | 4.7e-14 | 3/3 |
| ENCAISSE_MT1 x adv_EQUIPE_CARTONS | O45_CARTONS | 2621 | 52.4 | 38.8 | +13.6 pts | +3.6 pts | 0.0e+00 | 3/3 |
| O15_MT1_FREQ x EQUIPE_CARTONS | O45_CARTONS | 1753 | 51.5 | 38.0 | +13.5 pts | +3.4 pts | 0.0e+00 | 3/3 |
| DEFENSE_PASSOIRE x adv_EQUIPE_CARTONS | O45_CARTONS | 2449 | 51.9 | 38.5 | +13.5 pts | +3.6 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_LUTTE_MAINTIEN x FENETRE_FIN_SAISON | O45_CARTONS | 725 | 52.8 | 39.4 | +13.4 pts | +3.2 pts | 9.4e-14 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_TRES_LONG x H2H_UNDER25 | O45_CARTONS | 631 | 54.7 | 41.3 | +13.4 pts | +3.4 pts | 6.0e-12 | 2/2 |
| POST_VICTOIRE_LARGE x EQUIPE_CARTONS | O45_CARTONS | 814 | 51.0 | 37.7 | +13.3 pts | +1.8 pts | 2.7e-15 | 3/3 |
| DEFENSE_PASSOIRE x EQUIPE_CARTONS | O45_CARTONS | 2903 | 51.2 | 38.0 | +13.2 pts | +3.1 pts | 0.0e+00 | 3/3 |
| CRISE_OFFENSIVE x adv_EQUIPE_CARTONS | O45_CARTONS | 1185 | 52.8 | 39.6 | +13.2 pts | +3.9 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x REPOS_LONG | O45_CARTONS | 9836 | 51.8 | 38.7 | +13.1 pts | +2.9 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x FAIBLE_EXTERIEUR | O45_CARTONS | 2487 | 51.2 | 38.2 | +13.1 pts | +2.3 pts | 0.0e+00 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_FORT_MT2 x MATCH_A_ENJEU | O45_CARTONS | 593 | 49.4 | 36.4 | +13.0 pts | +10.9 pts | 3.2e-11 | 3/3 |
| FORT_MT2 x EQUIPE_CARTONS | O45_CARTONS | 2458 | 51.1 | 38.1 | +13.0 pts | +1.5 pts | 0.0e+00 | 3/3 |
| O15_MT1_FREQ x adv_EQUIPE_CARTONS | O45_CARTONS | 1912 | 50.6 | 37.6 | +13.0 pts | +2.2 pts | 0.0e+00 | 3/3 |
| SOLIDE_MT1 x adv_EQUIPE_CARTONS x H2H_UNDER25 | O45_CARTONS | 451 | 54.1 | 41.2 | +12.9 pts | +4.5 pts | 2.4e-08 | 2/2 |
| POST_VICTOIRE_LARGE x adv_EQUIPE_CARTONS | O45_CARTONS | 1266 | 49.3 | 36.5 | +12.8 pts | +0.5 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x STADE_FERME | O45_CARTONS | 840 | 50.2 | 37.4 | +12.8 pts | -0.0 pts | 1.0e-14 | 3/3 |
| REPRISE_FORME x EQUIPE_CARTONS | O45_CARTONS | 691 | 51.4 | 38.6 | +12.8 pts | +3.0 pts | 4.3e-12 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_LONG | O45_CARTONS | 9843 | 51.3 | 38.6 | +12.7 pts | +2.4 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_FAIBLE_VS_TOP | O45_CARTONS | 608 | 51.5 | 38.8 | +12.7 pts | +2.3 pts | 9.6e-11 | 3/3 |
| SERIE_V_LONGUE x adv_EQUIPE_CARTONS | O45_CARTONS | 489 | 47.4 | 34.7 | +12.7 pts | -3.0 pts | 2.4e-09 | 3/3 |
| FORT_MT1 x EQUIPE_CARTONS | O45_CARTONS | 2186 | 50.5 | 37.9 | +12.7 pts | +1.9 pts | 0.0e+00 | 3/3 |
| FORT_MT2 x adv_FORT_MT2 x MATCH_A_ENJEU | O45_CARTONS | 586 | 49.1 | 36.5 | +12.6 pts | +10.7 pts | 1.8e-10 | 3/3 |
| EQUIPE_CARTONS x FAIBLE_DOMICILE | O45_CARTONS | 1292 | 52.3 | 39.8 | +12.5 pts | +3.4 pts | 0.0e+00 | 3/3 |
| ATTAQUE_PROLIFIQUE x EQUIPE_CARTONS | O45_CARTONS | 1864 | 49.8 | 37.3 | +12.5 pts | +0.9 pts | 0.0e+00 | 3/3 |
| SOLIDE_MT1 x adv_EQUIPE_CARTONS | O45_CARTONS | 3587 | 50.7 | 38.2 | +12.5 pts | +1.5 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_DOMINE_FAIBLES | O45_CARTONS | 1543 | 48.7 | 36.3 | +12.4 pts | -2.0 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS | O45_CARTONS | 16132 | 51.0 | 38.7 | +12.3 pts | +2.1 pts | 0.0e+00 | 3/3 |
| CRISE_OFFENSIVE x EQUIPE_CARTONS | O45_CARTONS | 1272 | 51.7 | 39.3 | +12.3 pts | +2.6 pts | 0.0e+00 | 3/3 |
| SOLIDE_MT1 x EQUIPE_CARTONS | O45_CARTONS | 3122 | 51.1 | 38.8 | +12.3 pts | +1.8 pts | 0.0e+00 | 3/3 |
| SERIE_SANS_V x adv_EQUIPE_CARTONS x H2H_BTTS | O45_CARTONS | 324 | 52.5 | 40.2 | +12.3 pts | +5.0 pts | 6.1e-06 | 2/2 |
| EQUIPE_CARTONS x adv_DOMINE_FAIBLES x FENETRE_FIN_SAISON | O45_CARTONS | 346 | 47.1 | 34.9 | +12.2 pts | -4.1 pts | 1.7e-06 | 3/3 |
| ENCAISSE_MT1 x adv_ENCAISSE_MT1 x FENETRE_FIN_SAISON | O45_CARTONS | 406 | 24.6 | 36.8 | -12.2 pts | -12.0 pts | 3.3e-07 | 3/3 |
| EQUIPE_CARTONS x adv_FAIBLE_EXTERIEUR | O45_CARTONS | 2268 | 50.9 | 38.8 | +12.1 pts | +1.5 pts | 0.0e+00 | 3/3 |
| SERIE_SANS_V x EQUIPE_CARTONS | O45_CARTONS | 3612 | 51.0 | 38.9 | +12.1 pts | +2.2 pts | 0.0e+00 | 3/3 |
| U05_MT1_FREQ x adv_EQUIPE_CARTONS | O45_CARTONS | 1485 | 51.4 | 39.5 | +11.8 pts | +2.2 pts | 0.0e+00 | 3/3 |
| FORT_MT1 x adv_EQUIPE_CARTONS | O45_CARTONS | 2681 | 48.7 | 36.9 | +11.8 pts | +0.0 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_FIN_SAISON_FORTE_HISTO | O45_CARTONS | 614 | 47.7 | 36.0 | +11.7 pts | -3.3 pts | 9.5e-10 | 2/2 |
| SCORING_FOU x adv_EQUIPE_CARTONS | O45_CARTONS | 1331 | 48.6 | 36.9 | +11.7 pts | +0.8 pts | 0.0e+00 | 3/3 |
| SCORING_FOU x EQUIPE_CARTONS | O45_CARTONS | 1187 | 49.1 | 37.5 | +11.6 pts | +1.6 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x FAIBLE_VS_TOP | O45_CARTONS | 730 | 49.5 | 37.9 | +11.6 pts | +0.1 pts | 8.0e-11 | 3/3 |
| EQUIPE_CARTONS x adv_STADE_FERME | O45_CARTONS | 964 | 48.2 | 36.8 | +11.5 pts | -1.9 pts | 9.3e-14 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_EQUIPE_CARTONS | O45_CARTONS | 2886 | 47.4 | 36.0 | +11.4 pts | -1.2 pts | 0.0e+00 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_TRES_LONG x H2H_BTTS | O45_CARTONS | 677 | 50.5 | 39.1 | +11.4 pts | +2.3 pts | 9.0e-10 | 2/2 |
| U05_MT1_FREQ x EQUIPE_CARTONS | O45_CARTONS | 1484 | 50.8 | 39.4 | +11.4 pts | +1.7 pts | 0.0e+00 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_REPOS_LONG x DERBY | O15_MT1 | 325 | 47.4 | 36.0 | +11.4 pts | +11.5 pts | 1.6e-05 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU | O45_CARTONS | 515 | 24.9 | 36.2 | -11.3 pts | -11.6 pts | 7.3e-08 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU x FENETRE_FIN_SAISON | O45_CARTONS | 515 | 24.9 | 36.2 | -11.3 pts | -11.6 pts | 7.3e-08 | 3/3 |
| FORT_MT2 x adv_DOMINE_FAIBLES x MATCH_A_ENJEU | O45_CARTONS | 316 | 48.1 | 36.8 | +11.3 pts | +7.5 pts | 3.0e-05 | 3/3 |
| FORT_MT2 x adv_EQUIPE_CARTONS | O45_CARTONS | 3352 | 48.4 | 37.1 | +11.2 pts | -0.5 pts | 0.0e+00 | 3/3 |
| SOLIDE_MT1 x adv_EQUIPE_CARTONS x H2H_BTTS | O45_CARTONS | 439 | 49.9 | 38.7 | +11.2 pts | +2.1 pts | 1.3e-06 | 2/2 |
| EQUIPE_CARTONS x adv_REPOS_TRES_LONG x FENETRE_FIN_SAISON | O45_CARTONS | 709 | 48.9 | 37.8 | +11.1 pts | -0.4 pts | 8.2e-10 | 3/3 |
| POST_VICTOIRE_SURPRISE x adv_EQUIPE_CARTONS | O45_CARTONS | 1414 | 50.4 | 39.4 | +11.0 pts | +2.2 pts | 0.0e+00 | 3/3 |
| POST_VICTOIRE_SURPRISE x EQUIPE_CARTONS | O45_CARTONS | 1591 | 50.0 | 39.1 | +10.9 pts | +2.3 pts | 0.0e+00 | 3/3 |
| FORT_MT2 x adv_EQUIPE_CARTONS x H2H_UNDER25 | O45_CARTONS | 341 | 50.7 | 39.9 | +10.8 pts | +1.5 pts | 3.9e-05 | 2/2 |
| STADE_FERME x adv_DOMINE_FAIBLES | O45_CARTONS | 330 | 47.6 | 36.9 | +10.7 pts | +6.3 pts | 5.0e-05 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_LONG x H2H_UNDER25 | O45_CARTONS | 1152 | 51.8 | 41.3 | +10.5 pts | +2.0 pts | 3.4e-13 | 3/3 |
| REPOS_LONG x SANS_ENJEU | O45_CARTONS | 529 | 25.7 | 36.1 | -10.4 pts | -11.2 pts | 5.3e-07 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_DOMINE_FAIBLES x MATCH_A_ENJEU | O45_CARTONS | 310 | 47.1 | 36.8 | +10.3 pts | +7.8 pts | 1.5e-04 | 3/3 |
| EQUIPE_CARTONS x H2H_UNDER25 | O45_CARTONS | 1908 | 51.5 | 41.2 | +10.2 pts | +1.6 pts | 0.0e+00 | 3/3 |
| STADE_FERME x adv_REPOS_LONG x MATCH_A_ENJEU | O45_CARTONS | 330 | 46.1 | 36.0 | +10.1 pts | +6.3 pts | 1.1e-04 | 3/3 |
| SERIE_VICTOIRES x adv_DOMINE_FAIBLES | O45_CARTONS | 465 | 46.0 | 36.0 | +10.1 pts | +6.1 pts | 5.4e-06 | 3/3 |
| FORT_MT1 x adv_EQUIPE_CARTONS x H2H_BTTS | O45_CARTONS | 392 | 47.7 | 37.6 | +10.1 pts | +0.9 pts | 3.4e-05 | 2/2 |
| SOLIDE_MT1 x adv_EQUIPE_CARTONS x FENETRE_FIN_SAISON | O45_CARTONS | 667 | 47.2 | 37.2 | +10.0 pts | -3.9 pts | 6.8e-08 | 3/3 |
| EQUIPE_CARTONS x adv_FORTERESSE | O45_CARTONS | 386 | 43.8 | 33.8 | +10.0 pts | -8.5 pts | 3.1e-05 | 3/3 |
| DOMINE_FAIBLES x adv_DOMINE_FAIBLES | O45_CARTONS | 680 | 46.2 | 36.3 | +9.9 pts | +6.1 pts | 6.3e-08 | 3/3 |
| FORT_MT2 x adv_DOMINE_FAIBLES x FENETRE_FIN_SAISON | O45_CARTONS | 331 | 45.6 | 35.7 | +9.9 pts | +5.9 pts | 1.5e-04 | 3/3 |
| SOLIDE_MT1 x adv_SOLIDE_MT1 x MATCH_A_ENJEU | O45_CARTONS | 506 | 47.8 | 38.0 | +9.8 pts | +10.2 pts | 5.0e-06 | 3/3 |
| STADE_FERME x MATCH_A_ENJEU | O45_CARTONS | 510 | 45.9 | 36.2 | +9.7 pts | +5.9 pts | 3.9e-06 | 3/3 |
| REPRISE_FORME x adv_EQUIPE_CARTONS | O45_CARTONS | 597 | 48.6 | 38.9 | +9.7 pts | +0.2 pts | 9.7e-07 | 3/3 |
| U15_FREQ x adv_EQUIPE_CARTONS | O45_CARTONS | 944 | 49.4 | 39.8 | +9.5 pts | -0.3 pts | 1.9e-09 | 3/3 |
| SANS_ENJEU x adv_REPOS_LONG | TEAM_O15_SELF | 515 | 44.7 | 35.1 | +9.5 pts | +4.4 pts | 2.6e-06 | 3/3 |
| SANS_ENJEU x adv_REPOS_LONG x FENETRE_FIN_SAISON | TEAM_O15_SELF | 515 | 44.7 | 35.1 | +9.5 pts | +4.4 pts | 2.6e-06 | 3/3 |
| EQUIPE_CARTONS x adv_REPOS_LONG x H2H_BTTS | O45_CARTONS | 1175 | 48.6 | 39.1 | +9.5 pts | +1.3 pts | 1.9e-11 | 3/3 |
| SOLIDE_MT1 x adv_DOMINE_FAIBLES x FENETRE_FIN_SAISON | O35 | 321 | 43.0 | 33.7 | +9.3 pts | +12.7 pts | 3.3e-04 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU | BTTS_Y | 515 | 63.5 | 54.2 | +9.3 pts | +9.7 pts | 2.0e-05 | 3/3 |
| REPOS_LONG x adv_SANS_ENJEU x FENETRE_FIN_SAISON | BTTS_Y | 515 | 63.5 | 54.2 | +9.3 pts | +9.7 pts | 2.0e-05 | 3/3 |
| ENCAISSE_MT1 x adv_EQUIPE_CARTONS x H2H_BTTS | O45_CARTONS | 324 | 49.1 | 39.8 | +9.3 pts | +2.4 pts | 6.0e-04 | 2/2 |
| SANS_ENJEU | O45_CARTONS | 930 | 27.5 | 36.8 | -9.2 pts | -10.6 pts | 4.2e-09 | 3/3 |
| SANS_ENJEU x FENETRE_FIN_SAISON | O45_CARTONS | 930 | 27.5 | 36.8 | -9.2 pts | -10.6 pts | 4.2e-09 | 3/3 |
| SERIE_V_LONGUE x adv_ATTAQUE_PROLIFIQUE | O45_CARTONS | 399 | 44.4 | 35.2 | +9.2 pts | +5.6 pts | 1.1e-04 | 3/3 |
| SERIE_VICTOIRES x adv_SERIE_VICTOIRES | O45_CARTONS | 354 | 45.8 | 36.6 | +9.1 pts | +8.0 pts | 3.3e-04 | 2/3 |
| U15_FREQ x REPOS_COURT | O45_CARTONS | 840 | 30.4 | 39.5 | -9.1 pts | -4.9 pts | 4.9e-08 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_EQUIPE_CARTONS x H2H_BTTS | O45_CARTONS | 471 | 46.3 | 37.2 | +9.1 pts | -1.6 pts | 3.7e-05 | 2/2 |
| POST_VICTOIRE_LARGE x MATCH_A_ENJEU | O45_CARTONS | 612 | 44.9 | 35.8 | +9.1 pts | +8.3 pts | 2.2e-06 | 3/3 |
| SERIE_VICTOIRES x adv_SERIE_VICTOIRES | BTTS_Y | 354 | 63.3 | 54.2 | +9.1 pts | +10.6 pts | 5.6e-04 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_SOLIDE_MT1 x MATCH_A_ENJEU | O45_CARTONS | 498 | 46.2 | 37.1 | +9.1 pts | +8.1 pts | 2.4e-05 | 3/3 |
| SOLIDE_MT1 x adv_FORT_MT2 x MATCH_A_ENJEU | O45_CARTONS | 521 | 46.3 | 37.2 | +9.0 pts | +7.5 pts | 1.7e-05 | 3/3 |
| POST_VICTOIRE_LARGE x adv_REPOS_LONG x MATCH_A_ENJEU | O45_CARTONS | 410 | 44.9 | 35.9 | +9.0 pts | +8.9 pts | 1.2e-04 | 3/3 |
| FORT_MT2 x adv_EQUIPE_CARTONS x FENETRE_FIN_SAISON | O45_CARTONS | 647 | 45.6 | 36.6 | +9.0 pts | -3.9 pts | 1.6e-06 | 3/3 |
| EQUIPE_CARTONS x H2H_BTTS | O45_CARTONS | 1922 | 48.3 | 39.3 | +9.0 pts | +1.0 pts | 4.4e-16 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_FORT_MT1 x MATCH_A_ENJEU | O45_CARTONS | 441 | 45.1 | 36.3 | +8.8 pts | +7.9 pts | 1.1e-04 | 3/3 |
| ATTAQUE_PROLIFIQUE x DERBY | O15_MT1 | 448 | 44.9 | 36.1 | +8.7 pts | +9.2 pts | 1.0e-04 | 3/3 |
| FORT_MT1 x adv_FORT_MT2 x MATCH_A_ENJEU | O45_CARTONS | 467 | 45.4 | 36.7 | +8.7 pts | +7.1 pts | 8.3e-05 | 3/3 |
| EQUIPE_CARTONS x FENETRE_FIN_SAISON | O45_CARTONS | 3069 | 46.6 | 37.9 | +8.7 pts | -3.3 pts | 0.0e+00 | 3/3 |
| REPOS_LONG x SANS_ENJEU | BTTS_Y | 529 | 62.8 | 54.1 | +8.6 pts | +9.1 pts | 6.3e-05 | 3/3 |
| ATTAQUE_PROLIFIQUE x adv_REPOS_LONG x DERBY | U15 | 325 | 13.8 | 22.5 | -8.6 pts | -9.0 pts | 1.7e-04 | 3/3 |
| SERIE_SANS_V x adv_EQUIPE_CARTONS x H2H_UNDER25 | O45_CARTONS | 392 | 50.3 | 41.6 | +8.6 pts | +0.1 pts | 5.1e-04 | 2/2 |
| FORT_MT2 x adv_FORT_MT2 x H2H_BTTS | O35 | 460 | 43.9 | 35.3 | +8.6 pts | +12.0 pts | 8.6e-05 | 2/2 |
| FAIBLE_VS_TOP x FENETRE_FIN_SAISON | O45_CARTONS | 377 | 27.9 | 36.4 | -8.6 pts | -9.3 pts | 5.1e-04 | 3/3 |
| EQUIPE_CARTONS x adv_LUTTE_TITRE | O45_CARTONS | 301 | 43.2 | 34.7 | +8.5 pts | -7.2 pts | 1.8e-03 | 3/3 |
| EQUIPE_CARTONS x adv_FAIBLE_EXTERIEUR x FENETRE_FIN_SAISON | O45_CARTONS | 461 | 46.2 | 37.8 | +8.4 pts | -3.7 pts | 1.7e-04 | 3/3 |
| FORT_MT2 x adv_FIN_SAISON_FORTE_HISTO | O05_MT1 | 492 | 83.3 | 74.9 | +8.4 pts | +11.1 pts | 1.4e-05 | 2/2 |
| U15_FREQ x adv_REPOS_COURT | O45_CARTONS | 866 | 31.1 | 39.5 | -8.4 pts | -4.2 pts | 3.6e-07 | 3/3 |
| SERIE_SANS_V x adv_O15_MT1_FREQ x FENETRE_FIN_SAISON | O45_CARTONS | 303 | 27.7 | 36.1 | -8.4 pts | -9.6 pts | 2.2e-03 | 3/3 |
| FAIBLE_DOMICILE x H2H_BTTS | MT1_SELF | 453 | 36.4 | 28.1 | +8.3 pts | +2.9 pts | 5.8e-05 | 2/2 |
| REPOS_LONG x adv_REPOS_LONG x DERBY_CHAUD | O15_MT1 | 362 | 44.2 | 35.9 | +8.3 pts | +9.2 pts | 9.1e-04 | 3/3 |
| ENCAISSE_MT1 x adv_EQUIPE_CARTONS x FENETRE_FIN_SAISON | O45_CARTONS | 519 | 46.4 | 38.2 | +8.3 pts | -3.1 pts | 9.7e-05 | 3/3 |
| SOLIDE_MT1 x adv_REPOS_TRES_LONG x H2H_UNDER25 | O45_CARTONS | 453 | 49.0 | 40.8 | +8.2 pts | +6.6 pts | 3.4e-04 | 2/2 |
| REPOS_COURT x LUTTE_TITRE | O45_CARTONS | 341 | 27.3 | 35.5 | -8.2 pts | -11.4 pts | 1.4e-03 | 2/3 |