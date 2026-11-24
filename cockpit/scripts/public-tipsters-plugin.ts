import {applyLocalOLBGPublic} from './olbg-retained-approved';
import {OLBG_RETAINED_APPROVAL} from './olbg-retained-approval';
import type {Plugin} from 'vite';
import type {IncomingMessage,ServerResponse} from 'node:http';
import {permitsLocalPilotRead} from './tipsters-pilot-plugin';
import {readReviewedPublicSnapshot,type SnapshotApproval} from './reviewed-public-snapshot';

export const REVIEWED_PUBLIC_SNAPSHOT:SnapshotApproval={
  "relativePath": ".ci/public-tipsters-approved/ae54e8e74500795fbcfe759cbabdcfe42a006f0855c00e5ba9dd7a92ba528aec/snapshot.json",
  "sha256": "ae54e8e74500795fbcfe759cbabdcfe42a006f0855c00e5ba9dd7a92ba528aec",
  "claimId": "DATA.SOURCE_OBSERVATORY.OLBG.ONE.NEW.APP.ADMISSION.20261122",
  "choices": 480,
  "pseudonyms": 80,
  "fixtures": 20,
  "maximumBytes": 2000000,
  "idsSHA256": "feb57da85e4af5fc371c96f4963474f936a0d480e2f424451bc17eb019a2bca5",
  "immutableSHA256": "a3f858e511ad0def5f51c5438c78243f23ea45002767c627a5ff2f4683bd621e",
  "historicalAnnotation":{"authorIdSHA256":"0ce928a9e21d664eb026859dcb38680e1accb8b5fc765a82d6d3f571190bd3dd","claimId":"ENG.SOURCE_OBSERVATORY.OLBG.ONE.PROGRAMME.AUTHOR.NAMESPACE.FIX.RESULT.20261123","fixtureIdSHA256":"8bb92dfef7a87b676c923aacc47792af1e2ba5d90d34710bfb0c71d9c731399f","relativePath":".ci/historical-programme/cebc219e5255c7af9bb7a884ad9ceb2bf3c4aefb045d7b8c08ffc765ec1f24ff/sidecar.json","sidecarSHA256":"cebc219e5255c7af9bb7a884ad9ceb2bf3c4aefb045d7b8c08ffc765ec1f24ff","sourceTipIdSHA256":"151d8ec252997233eba1b4526872cdaa39d225594c0dd10e1311d58ec5338083","targetIdSHA256":"08341bf449a10e5b10028f15d1c86c9615a77116df650668447f9d4208d22eae","targetRowSHA256":"614ecc93696b4e23646419f9e5f94c7ac3d64e5cba99a95c63471a3f1142fac0","versionsSHA256":"ed13aa2629235c58ca6adcd77f25a2c71dd2c42d6302cd25fd4142e657c14967"}
};

export function publicTipsters(approval:SnapshotApproval=REVIEWED_PUBLIC_SNAPSHOT):Plugin{
 let root=process.cwd();
 const middleware=(request:IncomingMessage,response:ServerResponse,next:()=>void)=>{
  if(request.url?.split('?')[0]!=='/api/tipsters/public')return next();
  response.setHeader('Cache-Control','no-store');
  response.setHeader('Content-Type','application/json; charset=utf-8');
  response.setHeader('X-Content-Type-Options','nosniff');
  if(!permitsLocalPilotRead(request)){response.statusCode=403;response.end(JSON.stringify({status:'forbidden',message:'Accès local A9_Mega requis.'}));return;}
  try{
   const base=readReviewedPublicSnapshot(root,approval);
   const facts=applyLocalOLBGPublic(base,root,OLBG_RETAINED_APPROVAL,approval.sha256);
   response.end(JSON.stringify(facts));
  }catch{
   response.statusCode=503;
   response.end(JSON.stringify({status:'unavailable',message:'Historique validé indisponible. Aucun compteur partiel affiché.'}));
  }
 };
 return {name:'robin-local-public-tipsters',configResolved(config){root=config.root;},
  configureServer(server){server.middlewares.use(middleware);},configurePreviewServer(server){server.middlewares.use(middleware);}};
}
