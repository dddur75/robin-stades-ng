# Hypothèses ancrées par le propriétaire

Les huit hypothèses ont été préenregistrées avant lecture des résultats
profonds. Elles sont des intuitions de domaine, pas des vérités. Un statut
`DATA_GATE_BLOCKED` signifie qu'aucun effet n'a été estimé.

| ID | Hypothèse | Marché prévu | Support min. | Gates bloquants | Statut |
|---|---|---|---:|---|---|
| H11-001 | buteur en forme contre défense centrale amputée | 1X2 équipe, buts équipe, O/U 2,5 ; BTTS si pricé | 80 | player form, absence, starter baseline | `DATA_GATE_BLOCKED` |
| H11-002 | 4-3-3 contre 4-4-2 | 1X2, O/U 2,5 | 120 | lineup, formation | `DATA_GATE_BLOCKED` |
| H11-003 | trois attaquants droitiers contre défense gauchère | 1X2, buts équipe | 100 | lineup, footedness | `DATA_GATE_BLOCKED` |
| H11-004 | gardien titulaire absent | 1X2, O/U 2,5 ; BTTS si pricé | 80 | absence, starter baseline | `DATA_GATE_BLOCKED` |
| H11-005 | deux centraux nouveaux ensemble | 1X2, O/U 2,5 | 100 | lineup, starter baseline | `DATA_GATE_BLOCKED` |
| H11-006 | rupture du onze | 1X2, buts équipe | 120 | lineup, absence | `DATA_GATE_BLOCKED` |
| H11-007 | congestion et tactique inhabituelle | 1X2, buts équipe | 100 | lineup, formation | `DATA_GATE_BLOCKED` |
| H11-008 | matchup structurel | 1X2, O/U 2,5 | 120 | lineup, formation | `DATA_GATE_BLOCKED` |

## Protocoles gelés

### H11-001

Direction attendue : résidu offensif positif. Le buteur doit avoir marqué au
moins deux fois sur ses trois dernières apparitions, avoir des minutes
attendues suffisantes et faire face à deux centraux habituels dont
l'indisponibilité est prouvée avant cutoff. Le marché buteur est
`MARKET_UNAVAILABLE` ; aucune cote 1X2 ne peut lui être substituée.

### H11-002

Test bilatéral en mode `POST_LINEUP`, séparé domicile/extérieur, formation
habituelle/changement. Contrôle négatif : formation décalée d'un match. Le
résultat attendu est une association ajustée, jamais un taux de victoire naïf.

### H11-003

Test bilatéral uniquement si le pied de chaque joueur pertinent est observé.
Contrôle négatif : faux pied fort. Toute valeur inférée rejette l'hypothèse.

### H11-004

Direction attendue : davantage de buts encaissés. Le gardien habituel et son
absence doivent être établis avant match. Contrôle : absence gardien décalée.

### H11-005

Direction attendue : davantage de buts encaissés. La baseline du duo central
utilise uniquement les huit matchs antérieurs. Contrôle : faux duo central.

### H11-006

Direction attendue : résidu équipe négatif. Interaction préenregistrée entre
changements, importance, domicile, repos et marché. Contrôle : lineup
aléatoire.

### H11-007

Direction attendue : résidu équipe négatif lorsque congestion forte et système
inhabituel coïncident. Contrôle : interaction tactique aléatoire.

### H11-008

Test bilatéral de front three/back three et front two/back four, ajusté au
marché. Les proxies de pressing ou de largeur ne sont admis que s'ils sont
réellement disponibles.

## Résultats

| ID | Support | Brut | Ajusté | Marché | q-value | Stabilité | Verdict | Limite |
|---|---:|---|---|---|---|---|---|---|
| H11-001 | 0 | non calculé | non calculé | buteur indisponible ; autres prix non évalués | N/A | non évaluée | `DATA_GATE_BLOCKED` | forme, absence et baseline |
| H11-002 | 0 | non calculé | non calculé | 1X2/O-U non évalués | N/A | non évaluée | `DATA_GATE_BLOCKED` | cutoff lineup/formation |
| H11-003 | 0 | non calculé | non calculé | 1X2/buts non évalués | N/A | non évaluée | `DATA_GATE_BLOCKED` | 0 pied sourcé |
| H11-004 | 0 | non calculé | non calculé | 1X2/O-U/BTTS non évalués | N/A | non évaluée | `DATA_GATE_BLOCKED` | absence gardien non point-in-time |
| H11-005 | 0 | non calculé | non calculé | 1X2/O-U non évalués | N/A | non évaluée | `DATA_GATE_BLOCKED` | duo et baseline non temporels |
| H11-006 | 0 | non calculé | non calculé | 1X2/buts non évalués | N/A | non évaluée | `DATA_GATE_BLOCKED` | lineup et absence |
| H11-007 | 0 | non calculé | non calculé | 1X2/buts non évalués | N/A | non évaluée | `DATA_GATE_BLOCKED` | formation post-match |
| H11-008 | 0 | non calculé | non calculé | 1X2/O-U non évalués | N/A | non évaluée | `DATA_GATE_BLOCKED` | lineup et formation |

Le blocage n'est pas converti en résultat négatif ou positif. Aucun appel
fournisseur n'a été engagé pour fermer artificiellement les gates.

Le préenregistrement décrit ici concerne uniquement H11-001 à H11-008. Il ne
qualifie pas le test principal correctif 11A, défini ultérieurement par
`1.0.0-amendment-1`. Le run `30282406035` confirme les huit hypothèses bloquées
et 0 appel fournisseur.
