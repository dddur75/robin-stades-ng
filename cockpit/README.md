# Robin des Stades — Cockpit Shadow

Cockpit opérationnel privé du pipeline prospectif. La vue par défaut est
alimentée par `data/live-proof/jalon3-activation.json` via
`scripts/build_cockpit_snapshot.py`.

## Validation locale

```powershell
.\.venv\Scripts\python.exe scripts/build_cockpit_snapshot.py
pnpm install --frozen-lockfile
pnpm test
pnpm dev
```

Le cockpit distingue contractuellement `LIVE SOURCE`, `LEGACY SOURCE`,
`DEMO DATA` et `NO OUTPUT`. La production financière reste
`PRODUCTION_LOCKED`.
