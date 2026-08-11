# Chronos Neon Project Identity Pagination V1

Project identity has two explicit, non-fallback paths.

- With `NEON_PROJECT_ID`, the preflight validates `^[a-z0-9-]{1,60}$`,
  retrieves that project directly, enumerates its branches with the
  branch-specific `pagination.next` contract, and requires exactly one active,
  enabled, non-pooled `read_write` endpoint whose host equals the already
  validated DSN target. The global `/projects` inventory is not called.
- Without `NEON_PROJECT_ID`, the preflight enumerates `/projects` completely
  with the official `pagination.cursor` contract before inspecting any
  endpoint inventory. A non-empty `unavailable_project_ids`, malformed or
  cyclic cursor, repeated page, duplicate project ID, or insufficient remaining
  GET budget fails closed. Only an exact, globally unique endpoint-host match
  is accepted.

The official project page maximum is 400. The implementation keeps the global
25-GET ceiling and reserves the complete remaining proof before each targeted
GET: at most 3 project pages, 18 project endpoint inventories, 1 project-detail
read, and 3 branch pages. Cursors are passed back unchanged through URL
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
