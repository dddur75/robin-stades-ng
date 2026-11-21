import assert from 'node:assert/strict';
import {test} from 'node:test';
import {isSroReobservation} from '../app/components/expert/public-tipsters';

test('the first accepted SRO observation does not become a reobservation badge',()=>{
 const first={observedAt:'2026-11-21T19:30:10Z',firstSeenAt:'2026-11-21T19:30:10Z'};
 assert.equal(isSroReobservation(first,{lastSeenAt:first.observedAt}),false);
 assert.equal(isSroReobservation(first,{lastSeenAt:'2026-11-21T19:30:11Z'}),true);
 assert.equal(isSroReobservation(first,undefined),false);
});

test('reobservation comparison uses timestamps and preserves the earliest known observation',()=>{
 const first={observedAt:'2026-11-21T19:30:10Z',firstSeenAt:'2026-11-20T18:00:00Z'};
 assert.equal(isSroReobservation(first,{lastSeenAt:first.observedAt}),true);
 assert.equal(isSroReobservation({observedAt:first.observedAt},{lastSeenAt:'2026-11-21T20:30:10+01:00'}),false);
 assert.equal(isSroReobservation(first,{lastSeenAt:'invalid'}),false);
 assert.equal(isSroReobservation({observedAt:'invalid'},{lastSeenAt:first.observedAt}),false);
 assert.equal(isSroReobservation(first,{lastSeenAt:'2026-11-19T10:00:00Z'}),false);
});

