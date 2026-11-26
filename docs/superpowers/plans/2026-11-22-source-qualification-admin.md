# Source qualification admin implementation

> **For agentic workers:** use the existing execution and verification workflows. C0 is the only PUBLIC/runtime writer. Reviewers are read-only.

**Goal:** Make recent source controls inspectable in Robin’s admin with measured counts and honest unknowns.
**Architecture:** Shared strict snapshot contract, bounded local read-only Vite middleware, hosted503 route, client table and private sanitized snapshot.
**Tech stack:** TypeScript, Node fs/http, React19, Vite/Vinext, existing node:test/tsx and Playwright.
**Spec:** docs/superpowers/specs/2026-11-22-source-qualification-admin.md

- [x] Write meaningful failing contract/API tests.
- [x] Implement strict snapshot validation and bounded file reader/middleware, no provider calls.
- [x] Add dated panel to existing admin and hosted503 route.
- [x] Produce sanitized snapshot from individually verified claims, preserving nulls and source dates.
- [x] Run targeted tests, typing/lint/build/JS budget, independent C3/C4 review.
- [x] Copy only reviewed code and sanitized snapshot to runtime; recetter actual browser; record claim and decisions.
- [ ] Prepare exact reviewed diff for any later publication; no merge/deploy.
