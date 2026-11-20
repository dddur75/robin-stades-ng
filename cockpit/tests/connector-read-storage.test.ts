import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {connectorDirectory} from '../scripts/tipsters-connectors-plugin';

test('historical connector read path cannot become the POST control path',()=>{
 const root=resolve('synthetic-publication/cockpit');
 const env={ROBIN_CONNECTORS_READ_DIRECTORY:resolve('synthetic-runtime/receipts')};
 assert.equal(connectorDirectory(root,false,env),env.ROBIN_CONNECTORS_READ_DIRECTORY);
 assert.equal(connectorDirectory(root,true,env),resolve(root,'.ci/tipsters-connectors'));
});
