# Chronos Neon Project Identity Pagination V1

> The cursor contract and fail-closed limits in this document remain active.
> The no-variable discovery ordering was superseded by
> `CHRONOS-NEON-POSITIVE-PROJECT-OWNERSHIP-WITNESS-V1.md`: endpoint inventories
> are now inspected for every project on the current page before a continuation
> cursor is requested. The configured-project path is unchanged.

Project identity has two explicit, non-fallback paths.

- With `NEON_PROJECT_ID`, the preflight validates `^[a-z0-9-]{1,60}$`,
  retrieves that project directly, enumerates its branches with the
  branch-specific `pagination.next` contract, and requires exactly one active,
  enabled, non-pooled `read_write` endpoint whose host equals the already
  validated DSN target. The global `/projects` inventory is not called.
- Without `NEON_PROJECT_ID`, use the superseding positive-ownership contract.
  Global inventory completeness is no longer claimed or required after a
  complete project-scoped positive witness. If no candidate is found on the
  current page, the same bounded `pagination.cursor` guard applies unchanged.

The official project page maximum is 400. The implementation keeps the global
25-GET ceiling and reserves the complete remaining proof before each targeted
GET. The superseding witness reserves 6 GETs (endpoint detail, project detail,
up to 3 branch pages, and branch-endpoint confirmation), leaving at most 16
candidate endpoint inventories across 3 project pages. Cursors are passed back unchanged through URL
encoding, retained only as SHA-256 fingerprints for audit, and never written to
the sanitized report. Project and branch pagination use separate parsers.

`search` is not used as identity proof: Neon documents it as a partial project
name-or-ID filter. A discovery inventory is complete only when continuation is
absent and `unavailable_project_ids` is a valid empty list.

The workflow remains manual-only. It performs no secret or variable update,
has no mutating Neon method, issues no SQL write, and never runs migration
`0014`. A read-only observation is authorized only after exact-head PR CI,
merge-commit integration, green and quiescent `main`, and a uniqueness check
showing no prior V4 dispatch on the new main SHA.
