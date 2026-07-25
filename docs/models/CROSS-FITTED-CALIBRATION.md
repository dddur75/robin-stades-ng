# Calibration cross-fit temporelle

Méthodes candidates : `NONE`, `TEMPERATURE_SCALING`, `SIGMOID`, `ISOTONIC`.
Pour chaque fold saison, le calibrateur est ajusté uniquement sur les
prédictions de folds strictement antérieurs. Le score du fold courant ne
participe jamais à son propre ajustement.

Le choix final utilise les prédictions OOF de Discovery/Validation. Le
calibrateur est ensuite ajusté une fois sur ce corpus et appliqué à
2024–2025. L’audit expose toujours
`evaluation_labels_used_for_selection=0`.
