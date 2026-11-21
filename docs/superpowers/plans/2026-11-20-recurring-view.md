# Recurring collection view implementation plan

> **For agentic workers:** Use superpowers:executing-plans. C0 is the sole writer; C1 and C2 review read-only.

**Goal:** Show the actual Forums, SRO and OLBG campaigns on the recurring collection page, independently of the historical Forecast campaign.

**Architecture / spec:** Reuse the existing read-only public snapshot and PublicTipsters compact view. Add a pure campaign presentation policy: historical successes never imply current scheduling; only a fresh, enabled Ready/Running native task, within the mission window and without a stop condition, can attest scheduling. Show the native next run only when future and before expiry. Keep Forecast routes and attribution unchanged in an explicitly labelled historical section, without a second page heading.

**Tech stack:** Existing React, TypeScript, Node tests and Playwright. No dependency changes.

## Global constraints

- No source GET, new campaign, task execution/change, frozen collector mutation or budget expansion.
- Preserve all source facts, provenance, unknown publication times and disabled performance evaluation.
- A failed API cannot hide the other campaign's evidence. Stale native state cannot assert an active schedule.
- Preserve the old Forecast `?view=tipsters` route and its author links.
- Local read-only verification only; existing PR #133 push authority, no merge or deployment.

## Review focus

- Ready without enabled/fresh verification is unknown, not scheduled.
- Expired or halted packages override an apparently healthy Windows task.
- Zero validated slots remain zero even after a request reservation.
- Public data stays visible if the independent Forecast API fails, and vice versa.
- Suspension, clock skew and a refresh error do not preserve an active scheduling label.

## Task 1: Truthful campaign status and page integration

- [ ] Write and run failing pure policy tests and a browser regression showing the missing public campaigns on the recurring page.
- [ ] Add `cockpit/app/lib/tipsters-campaign.ts` for the pure status/next-run policy and a small status component with a local freshness clock.
- [ ] Integrate that status into the three existing PublicTipsters campaign cards, preserving budgets and source choices.
- [ ] Mount PublicTipsters independently on `collecte-recurrente/page.tsx`; make TipstersPilot optionally embedded and identify its Forecast history explicitly.
- [ ] Run targeted policy, existing recurring/public browser tests, typing and relevant lint. Verify actual A9 read-only state and unchanged source campaign counters in a new private receipt directory.
- [ ] Obtain independent C1/C2 review, append metadata proof/claim and council decision, run mandatory graph and portability/security gates, publish one non-force commit to PR #133 and follow its exact-head CI to completion.
