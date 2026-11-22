import type {Plugin} from 'vite';
import type {IncomingMessage,ServerResponse} from 'node:http';
import {permitsLocalPilotRead} from './tipsters-pilot-plugin';
import {readIndependentCatalogue} from './catalogue-independent';

export function tipsterCandidates():Plugin{
 let root=process.cwd();
 const middleware=(req:IncomingMessage,res:ServerResponse,next:()=>void)=>{
  if(req.url?.split('?')[0]!=='/api/tipsters/candidates')return next();
  res.setHeader('Cache-Control','no-store');res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('X-Content-Type-Options','nosniff');
  if(!permitsLocalPilotRead(req)){res.statusCode=403;res.end(JSON.stringify({status:'forbidden',message:'Accès local A9_Mega requis.'}));return;}
  try{res.end(JSON.stringify(readIndependentCatalogue(root)));}
  catch{res.statusCode=503;res.end(JSON.stringify({status:'unavailable',message:'Registre documentaire absent ou invalide. Aucun état de collecte actuel n’est déduit.'}));}
 };
 return {name:'robin-local-tipster-candidates',configResolved(c){root=c.root;},configureServer(s){s.middlewares.use(middleware);},configurePreviewServer(s){s.middlewares.use(middleware);}};
}
