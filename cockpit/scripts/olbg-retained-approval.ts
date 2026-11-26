import type {OLBGRetainedApproval} from './olbg-retained-approved';

/** Preparation metadata only. Activation requires a fresh application grant. */
export const OLBG_RETAINED_APPROVAL_PLAN:OLBGRetainedApproval=Object.freeze({
 envelopeSHA256:'5829368df2d2a1d569047e6ade3bd31254dea2b8bd953c0b42043a2c4fb72a05',
 envelopeBytes:16208,
 receiptSHA256:'c0f9d2f45c8ff3048019fbc96141ac942129dfa359e7a59175952aec40f1916e',
 claimId:'DATA.SOURCE_OBSERVATORY.OLBG.THREE.UEFA.SCHEDULED.PREMATCH.20261124',
 count:3,fixtureCount:3,inputCount:17,
 sourceObservedAtUTC:'2026-11-24T14:09:43.639793+00:00',
 calendarObservedAtUTC:'2026-11-24T14:41:31.976Z',
 parserSHA256:'275f6c296dca7c3ff342e705b131b68b053ae10d09ee56d4fe7b163304d9a8a8',
 builderSHA256:'d6e1b1691fba712fd578eea81e6f6d4793e5a5054f31281af33fdb57acbb1882',
 pendingSHA256:'3985cda1cfa064f27d4f7af3fd44a1e7e5be6433f5e30011f7c3d9a2fd63fe11',
 calendarSHA256:'dc9181bf657f1b72d64c4ce143dc0daff611856aa7fa6a395fadc857fc8f9ee1',
 responseSHA256:'6b8a39fae7eb242ab19ca16ad063209374e78728399ff49ccba48cbc28f1e4e2',
 sourceClaims:Object.freeze([
  'DATA.SOURCE_OBSERVATORY.OLBG.PENDING.REAL.NATIVE.RESULT.20261124',
  'DATA.SOURCE_OBSERVATORY.UEFA.24NOV.PRIMARY.CALENDAR.20261124',
  'ENG.SOURCE_OBSERVATORY.UEFA.DERIVED.SOURCE.CONTEXT.ADOPTION.20261124'
 ]),
 publicBaseSHA256:'ae54e8e74500795fbcfe759cbabdcfe42a006f0855c00e5ba9dd7a92ba528aec'
});
export const OLBG_RETAINED_APPROVAL:OLBGRetainedApproval|null=OLBG_RETAINED_APPROVAL_PLAN;
