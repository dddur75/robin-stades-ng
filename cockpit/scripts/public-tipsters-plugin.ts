import type {Plugin} from 'vite';
import type {IncomingMessage,ServerResponse} from 'node:http';
import {permitsLocalPilotRead} from './tipsters-pilot-plugin';
import {applyAcceptedForums,applyReviewedForumBatches,type ForumBatchApproval} from './forums-accepted';
import {readReviewedPublicSnapshot,type SnapshotApproval} from './reviewed-public-snapshot';

export const REVIEWED_PUBLIC_SNAPSHOT:SnapshotApproval={
  "relativePath": ".ci/public-tipsters-approved/9efe723236e37b6817175a6583e08471c8acd54a3405c6dfc3d5d98f3e857b66/snapshot.json",
  "sha256": "9efe723236e37b6817175a6583e08471c8acd54a3405c6dfc3d5d98f3e857b66",
  "claimId": "DATA.SOURCE_OBSERVATORY.APP479.PREMATCH.METADATA.AUDIT.20261122",
  "choices": 479,
  "pseudonyms": 80,
  "fixtures": 20,
  "maximumBytes": 2000000,
  "idsSHA256": "3b8181238405d6d70e1faaa55a6361ad9c07d95f88273f532a3e0e5d57434526",
  "immutableSHA256": "3bf004690cb4303d1497d35db9a1a7b51d1cbd4edcab137cad919e9368939f5a"
};

// Only exact independently reviewed admission descriptors may be added here.
const REVIEWED_EXTRA_FORUM_BATCHES: readonly ForumBatchApproval[] = [
  {
    "relativePath": ".ci/forums-approved/6cdc9e683826bb9596f404c45a3097bf19a14731adb1c982d0381b7d6d189de4/envelope.json",
    "envelopeSHA256": "6cdc9e683826bb9596f404c45a3097bf19a14731adb1c982d0381b7d6d189de4",
    "missionId": "SCO_PERSONAL_CURRENT_E1_R1_20261122",
    "claimId": "DATA.SOURCE_OBSERVATORY.SCO1919.CURRENT.PREMATCH.ADMISSION.20261122",
    "decisionSHA256": "b13d15e68b90ed37709575263cbb744c50a262c163f5ab8294ee18b5dcc0c950",
    "sourceIds": [
      "SRC_038"
    ],
    "newNativeChoiceIds": [],
    "maximumRows": 12,
    "plan": "ae56f4ef577b6edcfae5044b0341a0897f1217b5c50dddfa06e3908304034b3e",
    "manifest": "653e55b8719e8cb9a74b7115515d31b8c9f78f6246d40e280bfe71df00a6605b",
    "grant": "c2c8ce5759027a22071d96f731a13f356dbe3a41a60ddee75c4f0a80a9d24d9a",
    "parserSha256": "f799ed679e422961aa766af12e2ec2920d04d7bab609883aa2813baa4dd0a914",
    "calendarSha256": "7e61eebf7dd920011fb18558212d67cb70f242c0da3e335c4a036fc4fb806977"
  },
  {
    "relativePath": ".ci/forums-approved/42f66143ab769597c0276749e9af3856626e54ee5a85c55accefeecc9c1cbe9b/envelope.json",
    "envelopeSHA256": "42f66143ab769597c0276749e9af3856626e54ee5a85c55accefeecc9c1cbe9b",
    "missionId": "LEGRUPPETTO_PERSONAL_CURRENT_E1_R1_20261122",
    "claimId": "DATA.SOURCE_OBSERVATORY.LEGRUPPETTO.CURRENT.PREMATCH.ADMISSION.20261122",
    "decisionSHA256": "86e0fc8e7cacb7ccb454b5641d4852de503c0d1530dc617aa9ac55b7c4a6b869",
    "sourceIds": [
      "SRC_058"
    ],
    "newNativeChoiceIds": [],
    "maximumRows": 30,
    "plan": "b71614dfc97f1b1b3d8d33f5addb04d4f045e9f3a17033779ab6741b8a015bcd",
    "manifest": "7103025237eb0719a88ac5d24636ca3113aad9207ec50c7ab8e8f1565f27d67e",
    "grant": "73954d1651bd7bbb8a03626517c38dda2f3824af76fb9139327fb70fe5821d8b",
    "parserSha256": "f799ed679e422961aa766af12e2ec2920d04d7bab609883aa2813baa4dd0a914",
    "calendarSha256": "7e61eebf7dd920011fb18558212d67cb70f242c0da3e335c4a036fc4fb806977"
  }
];


export function publicTipsters(approval:SnapshotApproval=REVIEWED_PUBLIC_SNAPSHOT):Plugin{
 let root=process.cwd();
 const middleware=(request:IncomingMessage,response:ServerResponse,next:()=>void)=>{
  if(request.url?.split('?')[0]!=='/api/tipsters/public')return next();
  response.setHeader('Cache-Control','no-store');
  response.setHeader('Content-Type','application/json; charset=utf-8');
  response.setHeader('X-Content-Type-Options','nosniff');
  if(!permitsLocalPilotRead(request)){response.statusCode=403;response.end(JSON.stringify({status:'forbidden',message:'Accès local A9_Mega requis.'}));return;}
  try{
   const facts=readReviewedPublicSnapshot(root,approval);
   const prefix=applyAcceptedForums(facts,root,'31c4363a8db90eb18fc0a73722af941a98bb39de4d0fd252f7f2077938b83c04');
   response.end(JSON.stringify(applyReviewedForumBatches(prefix,root,REVIEWED_EXTRA_FORUM_BATCHES)));
  }catch{
   response.statusCode=503;
   response.end(JSON.stringify({status:'unavailable',message:'Historique validé indisponible. Aucun compteur partiel affiché.'}));
  }
 };
 return {name:'robin-local-public-tipsters',configResolved(config){root=config.root;},
  configureServer(server){server.middlewares.use(middleware);},configurePreviewServer(server){server.middlewares.use(middleware);}};
}
