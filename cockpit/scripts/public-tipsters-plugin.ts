import type {Plugin} from 'vite';
import type {IncomingMessage,ServerResponse} from 'node:http';
import {permitsLocalPilotRead} from './tipsters-pilot-plugin';
import {applyAcceptedForums,applyReviewedForumBatches,type ForumBatchApproval} from './forums-accepted';
import {applyReviewedSROHistoricalUpdates,type Approval as SROHistoricalApproval} from './sro-historical-updates';
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

const REVIEWED_SRO_HISTORICAL:SROHistoricalApproval={
  "allowedNativeChoiceIds": [
    "0262567f335b10b3dbbaef75a74ea5444dbde6090cbf66f42607481a11bdbf07",
    "07764a3d1163259b963c619b4fa0c7e7e3b5ae3fddb21e9be39d3d65a4792ba9",
    "118669633a9f115a1f465dcf58b8ead2a580dcc2feaa3e77fc2a68412804cb7a",
    "16ef49c256fe7c71bd2250efa802a738fdcdc387760c00b78f280f71d32080c3",
    "190cf831f0511e76f5f2421b9a4e11cb3c111c9f2f484164404c86868b521362",
    "1b4126229f8b5591710fd2d5d55ad909cfd5c9988159c4c83ac4c38e1ac6b35b",
    "1b70ccf37eb71c9f81e9f079cb4fb5997fb47c9abdec2d777623dc9adffc33b4",
    "1fd6cb6d1d8dec8108182fabd91ae763a6834359dcc3440057da1e9bfe15783f",
    "219962a9c6849df34705d8be0f9c501d3803d6e42c3e009ce87c99dec1014566",
    "27a22359300c42f4be93d88168431d87e96f84e14a72d27c0086a213f8884abe",
    "282c62c831cd7b82ecd07932828d4181a96b262f586492816440298b8d5bd70f",
    "2b625a29a7356d169aa31dabd2dbd2a1cf30e824e656237b598fe4a736fe8283",
    "35769e347aee9e0575f246f0e4ed7db6c757442c2a56c5931e897ea476060516",
    "365c0c3b07f4a204ddc92028915e0bbe72fc5c6089385dcf5b4dda9d02c85a9c",
    "3e827893312988a2f844f977ee30df56f04b1f956f1b3d4ae6a8d743636d5a61",
    "42d8e65ccd9987132c3daf329e510d7f79136f7310ad070529b9d5b4e6bc7344",
    "4ca2130fa1e9b78c82a9ecc0af16d67025a5782d732d56b6a207fb833a7ef531",
    "4edc454529aef5fe9f402ada307fae27438b8a2e4db3d8c4f2fbdb8e8a499283",
    "4f87528553565be8ea5f7a4c1d4a628d07e8e7177335b1b76335ee22baf7f5a7",
    "5d48a0a398205f9191da406f4c25817cafdb0fbf8978fb3ff2a3024e7fdf777d",
    "5fea19b04c718d08bb50f418e4d896d96ff5740afd7b8b2b9aaf67fd5fd0b332",
    "60dd62364a37e99a496f6e1a979b862758f28902bd8ee6546ab31550fbe04adb",
    "677e70937b8deed7bc03753deb3070898b427d9be684ce31986f95d02354a2cd",
    "6de5891c46c27c054a9fa64cadfee0420205fac3ff3f1b7b25131d247dacac5a",
    "701fdb1bce2bc61ba1f0bde6963698671635bd14f7119aa91f133f9a4932d475",
    "7a010ff04c5b77131a15a2a2285996bba7b957e12198d3f0539a8b99d9c95705",
    "805e4c304e749c24340c9f9626368bae66e0529370a72bd6c859238598654d78",
    "84a25f3c3e1b517a028e54da8a18c1d24f07b2ff558df95e93a356e6f585ce96",
    "8c500621b02040e4245fb1bfe45fe41da3139395c7eff70394c36bd46db4ff05",
    "8c5d53cc10e4ca117657bd200b3836c42b1f9ba3acab9fafed7cc7d3111e83be",
    "93cc9ba063c9c016fec0b0cd2cc3dc19c02d24b1507ffe212ddc84c3ab842ed7",
    "9462da04c745f2ad8f36019ece901648b29e39baf7c05ef27fed85af6f4c28f5",
    "98ac3ad8ad28fabc645f543a3c1adfaef0a54dcd1c10ed71b9c1f46693f37a03",
    "9bc7f41055685a30caa7c74ea6fd4a1f3fb4048913b8968541b0568eea7bf482",
    "a0059526ae01573a401638eb37aebae237ceda20ac32ba7ad0c9b6b9df8dda5c",
    "a09901612c8d4ab66c9b360d9fdd5ac8421a90dbae6460a3ddd3f25544a47741",
    "a1bf64a1ac8a7011ab5c09e8c7433dab905f993b2e6d1b63c7422c210dc3f97a",
    "a540ad5ac68a05d4fcb36c0aa9a8cf5f40058b21a75a12c48259ef8631b2edda",
    "a8d42a144adc25c431d8a43cdab19cc39a0b1363894a9eb87419223632950f3d",
    "b69540e6b66b0ddf7b27a18bccde2d2535d55810c32d30d27d106140a56bea21",
    "b799b5c8845f75b2050130dc6e56e4ffcb296210781b99bd3091551be911154e",
    "b83c6d5388072b6580b827a2ddb383b1e71b3f5f602797dc77c8a534bfe6d787",
    "bb7b858a6841ce0969e54b4b42430ce7a0a7ac33aa3ce83cb9724f6ec9158270",
    "bb834f679de03d9212b90d57cf163b4e88fdc7d9413fa0231d54a2153306d64f",
    "bbec1de4d652b8376a05c4e4fd76b85dbab239b771393f08e2aadfcfbd9a519a",
    "ca01c8fe320073acd13a5963aff67138b5cbc7cdbec4a2aa4391b1e97f8948aa",
    "cba4a0d4fb16cf0ceab882026ea36bc8f7efb5fb7d9e6ce5ea5bab6c0c348083",
    "cdd4194196ccf31714f41f191f0d3d2891f0d72c4f7e3e5d248188c51fd50c79",
    "d00429c89c890ba4d02fb9ae8f36ff3d658a492cbc5cf0f21f119e278bf7e7e0",
    "d3d0b4ac2f6d5abf3cfd29b5d9ecc81cd5da72890d63d370e47871c5cb7c8267",
    "dab31c209aed311df3202fa4d093434523362894e76f5124c4dfe08f54e5332a",
    "e7081507fa60e43be046a52e6feeed7c13ce3013620072ec948e81026c510ad1",
    "e940408533afabeef4f743a7caef4d1e785bc589ab166cdfd645c764e19ae984",
    "ebb552d1375b11f8640852126e53a09f1047d55ebe3ed55ca22b80e8f17e78bb",
    "f55fd9c441611353052c2d529db9a8d077a45c1f0ab0afcb4b8fc4431bc0245f"
  ],
  "candidateSHA256": "bb36494ae56699a7f2ae928f32d4d4b4156df6240f56e13446d94dd4cee0737a",
  "choices": 479,
  "claimId": "DATA.SOURCE_OBSERVATORY.SRO.HISTORICAL.CANARY.R2.APP.ADMISSION.20261122",
  "decisionSHA256": "ae50622f72b8a85aaf28fd94f00b5a5cc82c379d64b4348e402c4c36f3b1c6b1",
  "fixtures": 20,
  "immutablePicksSHA256": "013fd47e6e93cda3d0253ec3aca32a78ba90cf8bbe63f9e20aa7f5ce384b322c",
  "maximumBytes": 65536,
  "maximumUpdates": 55,
  "parentClaimId": "DATA.SOURCE_OBSERVATORY.SRO.CANARY.R2.REOBSERVED.20261121",
  "pseudonyms": 80,
  "receiptSHA256": "f3357934cb67f682278ae69cc4e94fa9820738e7244a44911d28efbca291e707",
  "relativePath": ".ci/sro-historical-approved/430f19bce1363880ec62abd8cd4b7b4cde461fa71e60ddcb336bfd2dfd5f969a/updates.json",
  "sourceObservedAt": "2026-11-21T18:18:42.376705+00:00",
  "sourceResponseSHA256": "08fd337db3294edb2111da858a8c537d3bed243755ee22a5cac7a73ef4bdec6c",
  "wrapperSHA256": "430f19bce1363880ec62abd8cd4b7b4cde461fa71e60ddcb336bfd2dfd5f969a"
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
,
{
  "relativePath": ".ci/forums-approved/9d6997135b213fa492dadaec786e5423a2b584cd86bd89d1c78f7cc9795a534d/envelope.json",
  "envelopeSHA256": "9d6997135b213fa492dadaec786e5423a2b584cd86bd89d1c78f7cc9795a534d",
  "missionId": "LEGRUPPETTO_RECURRING_R2_TWO_SLOTS_20261122",
  "claimId": "DATA.SOURCE_OBSERVATORY.LEGRUPPETTO.RECURRING.R2.SLOT0.APP.ADMISSION.20261122",
  "decisionSHA256": "3803ba4a362804082f8db9b6cef282ec9918415c28274c0ba624c1505866de11",
  "sourceIds": [
    "SRC_058"
  ],
  "newNativeChoiceIds": [],
  "maximumRows": 30,
  "plan": "87a07786314afe89742cca7a41b6027a9adee38b0e83b5d855711fb2d04dd540",
  "manifest": "3b20e6a2149716d279db8bb1de23a50584a80fd2316894e6b43f389177d72db3",
  "grant": "b443c7030c1d95345e2506264d7276cfaf753c9fe7a3c0295cffbb16818acb49",
  "parserSha256": "f799ed679e422961aa766af12e2ec2920d04d7bab609883aa2813baa4dd0a914",
  "calendarSha256": "7e61eebf7dd920011fb18558212d67cb70f242c0da3e335c4a036fc4fb806977"
}
,
{
  "relativePath": ".ci/forums-approved/c156d84b519aa9c96e10c210a834a6bd99e114749381fa5a24e1158c57768a90/envelope.json",
  "envelopeSHA256": "c156d84b519aa9c96e10c210a834a6bd99e114749381fa5a24e1158c57768a90",
  "missionId": "LEGRUPPETTO_RECURRING_R2_TWO_SLOTS_20261122",
  "claimId": "DATA.SOURCE_OBSERVATORY.LEGRUPPETTO.RECURRING.R2.SLOT1.APP.ADMISSION.20261122",
  "decisionSHA256": "ae50622f72b8a85aaf28fd94f00b5a5cc82c379d64b4348e402c4c36f3b1c6b1",
  "sourceIds": [
    "SRC_058"
  ],
  "newNativeChoiceIds": [],
  "maximumRows": 20,
  "plan": "87a07786314afe89742cca7a41b6027a9adee38b0e83b5d855711fb2d04dd540",
  "manifest": "3b20e6a2149716d279db8bb1de23a50584a80fd2316894e6b43f389177d72db3",
  "grant": "b443c7030c1d95345e2506264d7276cfaf753c9fe7a3c0295cffbb16818acb49",
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
   const historical=applyReviewedSROHistoricalUpdates(facts,root,REVIEWED_SRO_HISTORICAL);
   const prefix=applyAcceptedForums(historical,root,'31c4363a8db90eb18fc0a73722af941a98bb39de4d0fd252f7f2077938b83c04');
   response.end(JSON.stringify(applyReviewedForumBatches(prefix,root,REVIEWED_EXTRA_FORUM_BATCHES)));
  }catch{
   response.statusCode=503;
   response.end(JSON.stringify({status:'unavailable',message:'Historique validé indisponible. Aucun compteur partiel affiché.'}));
  }
 };
 return {name:'robin-local-public-tipsters',configResolved(config){root=config.root;},
  configureServer(server){server.middlewares.use(middleware);},configurePreviewServer(server){server.middlewares.use(middleware);}};
}
