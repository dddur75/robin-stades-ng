# Runbook

## Environnement local

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Référence CI : Python 3.12.

## Contrôles avant un run

1. vérifier `git status --short --branch` ;
2. vérifier que le mode reste simulation ;
3. vérifier la présence des fichiers de configuration ;
4. exécuter `python -m pytest -q` ;
5. ne jamais ouvrir le holdout depuis un run automatisé.

## Collecte historique

```powershell
.\.venv\Scripts\python.exe agents\agent_collecte.py
```

Après le run, contrôler volume, plages de dates, doublons de `match_id`, valeurs
manquantes et schéma avant d'accepter les données.

## Archive prospective

Le secret `ODDS_API_KEY` est stocké dans GitHub Actions. Ne jamais l'écrire dans
un fichier ou un log.

Un workflow vert sans fichier `odds_*.parquet` signifie seulement que le processus
n'a pas levé d'erreur. Il ne prouve pas qu'un snapshot a été capturé.

## Tests

```powershell
.\.venv\Scripts\python.exe -m compileall -q agents moteur tests
.\.venv\Scripts\python.exe -m pytest -q
```

## Incident

En cas d'échec :

1. conserver les artefacts et logs ;
2. ne pas masquer l'erreur par `|| true` ;
3. identifier le dernier run fiable ;
4. reprendre depuis l'étape idempotente précédente ;
5. documenter cause, impact, correction et preuve dans le registre d'incidents
   dès que celui-ci est disponible.
