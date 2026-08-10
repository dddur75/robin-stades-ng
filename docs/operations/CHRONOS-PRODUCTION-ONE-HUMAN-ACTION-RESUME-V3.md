# Chronos Production — reprise à une action humaine V3

Verdict de fallback prévu: `CHRONOS_PRODUCTION_BOOTSTRAP_OFFLINE_READY`.

Le code, les workflows manual-only, les tests PostgreSQL 16, la simulation de
replay et le runbook peuvent être livrés sans secret. Si le bootstrap s’arrête
par absence d’un secret obligatoire, l’unique action humaine autorisée est:

> Installer ou remplacer, dans l’Environment GitHub
> `chronos-control-plane-production`, les secrets manquants parmi
> `NEON_API_KEY` et `NEON_BOOTSTRAP_DATABASE_URL`, directement dans l’interface
> GitHub ou par stdin sécurisé — ne jamais coller leur valeur dans une
> conversation, un ticket, un log ou un fichier Git.

Après cette action unique, reprendre au mode `PREFLIGHT`; ne jamais reprendre
directement à `MIGRATE`.
