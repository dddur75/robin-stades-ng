# Dossier fidèle dans le cockpit privé

La sous-page de l’Espace Expert montre le périmètre du pilote Ligue 1, l’état des sources et les visites documentées. Le plan V4 d’octobre sert de référence historique. Un plan indique des créneaux prévus. Les visites, réussites et publications ne deviennent visibles qu’après rattachement d’un journal vérifié à ce plan.

## Mise en œuvre

1. Construire hors ligne une projection du plan V4 et, si disponible, de son journal. Vérifier le registre, l’empreinte du plan, le journal et le lien exact entre les visites et le plan. Exclure les contenus des publications, les extraits, les URL et les diagnostics bruts.
2. Rendre la projection dans `/expert/observatoire-sources`. Afficher les sources, le type d’accès déclaré lors de la préparation et l’état des visites. Distinguer journal absent et zéro documenté. Les chiffres de visites s’appuient sur le plan entier, y compris les créneaux sans reçu.
3. Vérifier un journal réduit, un journal incohérent, l’absence de journal, l’accès au menu et le rendu sur écran étroit. Le pilote maintient les auteurs en observation, selon C5.3 de ses critères.

L’écran reprend la politique privée du cockpit. L’export s’effectue depuis un poste de travail hors ligne. Le site ne lit pas le journal brut et ne déclenche pas le collecteur.

## Générer l’instantané

Depuis la racine du dépôt, avec Robin installé dans l’environnement Python :

```powershell
python cockpit/scripts/build-source-observatory-snapshot.py --output cockpit/app/source-observatory-snapshot.json
```

Cette commande vérifie et reproduit le plan historique V4. Les fichiers de plan et de registre sont comparés aux empreintes des octets Git, y compris sur un checkout Windows dont les fins de ligne sont CRLF. Le journal conserve ses octets exacts.

Pour publier des observations vérifiées dans une prochaine version, fournir ensemble `--journal`, `--journal-receipt` et `--journal-claim-id`. Le reçu JSON contient exactement `schema_version` (`source-observatory-journal-receipt-v1`), `claim_id`, `plan_sha256` et `journal_head`. Dans le graphe de preuves, la revendication référence cet artefact et son SHA-256 dans `hash`, utilise la portée `SOURCE_OBSERVATORY_PILOT_JOURNAL` et indique l’empreinte du plan dans `dataset_lineage_id`. Son statut doit être `VERIFIED`, avec au moins deux relecteurs distincts du registre Council. Un journal dont le reçu appartient à un autre plan, dont la source diffère ou dont un succès arrive après tous les coups d’envoi concernés est refusé.

L’instantané fourni ici contient le plan et les sources historiques. Le test de projection compare ce fichier au résultat régénéré. Le suivi des contributions détaillées et le rapport de recette C1–C6 dépendent des preuves d’un pilote réel.

## Proposition de reprise Ligue 1

La J12 du 27 au 29 novembre 2026 fournit une fenêtre future. Candidat de préparation du **lundi 23 novembre à 20 h 45** au **dimanche 29 novembre à 20 h 44** (heure de Paris), sous réserve de disponibilité du runner, de la conformité des sources et d’accord sur le plan final. Les horaires ci-dessous viennent du [programme officiel de la J12](https://ligue1.com/fr/articles/l1_article_5843-).

| Date | Heure de Paris | UTC | Matchs |
|---|---:|---:|---|
| 27 novembre | 20 h 45 | 19 h 45 | Brest – Paris FC |
| 28 novembre | 17 h 15 | 16 h 15 | Angers – Lens |
| 28 novembre | 20 h 45 | 19 h 45 | PSG – Lorient, Le Mans – Lille, Le Havre – Strasbourg, Nice – Troyes |
| 29 novembre | 15 h 00 | 14 h 00 | Auxerre – Marseille |
| 29 novembre | 17 h 15 | 16 h 15 | Toulouse – Rennes |
| 29 novembre | 20 h 45 | 19 h 45 | Lyon – Monaco |

**Essai hors réseau du dernier créneau.** Avec cinq sources fictives, deux réponses par visite et un départ une minute avant le coup d’envoi, les cinq visites passent à une seconde par réponse. À dix secondes par réponse, deux réussissent et trois se terminent hors délai. À vingt secondes par réponse, une seule réussit. Cette simulation justifie un réglage du dernier créneau selon la charge autorisée avant tout gel.

**À préparer avant autorisation.** Revoir les règles d’accès des sources candidates et les horaires officiels. Figer le registre exact, les visites, les empreintes et le plafond avant la fenêtre. Le projet de cadence reprend une visite toutes les six heures et un créneau une minute avant chaque coup d’envoi distinct. Tester hors réseau ce dernier créneau avec les délais du collecteur. Si la charge séquentielle ne tient pas, construire une proposition corrigée avant le gel. Documenter les sources exclues avant le gel. Après le gel, garder les visites en échec, bloquées ou sans reçu dans le dénominateur. Présenter la recette du pilote au regard de C1–C6 et conserver le verdict `PARTIAL` si un seuil manque.

Le lancement et tout changement de plan nécessitent la décision explicite prévue par `RCV3-20261026-SOURCE-OBSERVATORY-DOSSIER-FIDELE-PLAN-V4` dans le journal Council. Le plan d’octobre et sa répétition à blanc ne font pas office de preuve pour cette nouvelle fenêtre.
