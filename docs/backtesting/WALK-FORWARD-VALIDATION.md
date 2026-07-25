# Validation walk-forward

Pour la saison S, le fit ne voit que les saisons strictement antérieures à S.
Les folds 2021–2023 alimentent la sélection cross-fit; 2024–2025 est évalué
après gel et étiqueté `EXPOSED_HISTORICAL_OOS`. 2026–2027 est réservé au
prospectif.

Chaque sortie conserve ses saisons de fit. Un cache n’est valide que si les
hashes datasets, le protocole, la graine et le commit sont identiques.
