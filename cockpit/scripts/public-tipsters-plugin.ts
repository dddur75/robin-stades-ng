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
  "immutableSHA256": "a3f858e511ad0def5f51c5438c78243f23ea45002767c627a5ff2f4683bd621e"
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
   const facts=readReviewedPublicSnapshot(root,approval);
   response.end(JSON.stringify(facts));
  }catch{
   response.statusCode=503;
   response.end(JSON.stringify({status:'unavailable',message:'Historique validé indisponible. Aucun compteur partiel affiché.'}));
  }
 };
 return {name:'robin-local-public-tipsters',configResolved(config){root=config.root;},
  configureServer(server){server.middlewares.use(middleware);},configurePreviewServer(server){server.middlewares.use(middleware);}};
}
