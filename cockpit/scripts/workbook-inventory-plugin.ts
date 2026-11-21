import {execFile} from 'node:child_process';
import {resolve} from 'node:path';
import {promisify} from 'node:util';
import type {Plugin} from 'vite';
import type {IncomingMessage,ServerResponse} from 'node:http';
import {permitsLocalPilotRead} from './tipsters-pilot-plugin';
import {gateSourceOperations,readNativeState} from './tipsters-native-state';
import {decorateInventory} from './workbook-inventory-state';

const runFile=promisify(execFile);
export function workbookInventory():Plugin {
 let root=process.cwd();
 const middleware=async(req:IncomingMessage,res:ServerResponse,next:()=>void)=>{
  if(req.url?.split('?')[0]!=='/api/tipsters/workbook')return next();
  res.setHeader('Cache-Control','no-store');res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('X-Content-Type-Options','nosniff');
  if(!permitsLocalPilotRead(req)){res.statusCode=403;res.end(JSON.stringify({status:'forbidden'}));return;}
  const params=new URL(req.url,'http://localhost').searchParams;
  const query={q:params.get('q')??'',sheet:params.get('sheet')??'',platform:params.get('platform')??'',page:Number(params.get('page')??0),limit:Number(params.get('limit')??25),record_id:params.get('id')??''};
  if(query.q.length>120||query.sheet.length>80||query.platform.length>160||query.record_id.length>100||!Number.isInteger(query.page)||query.page<0||query.page>10000||!Number.isInteger(query.limit)||query.limit<1||query.limit>50){res.statusCode=400;res.end(JSON.stringify({status:'invalid_query'}));return;}
  try{
   const repo=resolve(root,'..');const python=process.env.ROBIN_TIPSTERS_PYTHON??resolve(repo,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
   const native=readNativeState(root);
   const options={timeout:12000,maxBuffer:2000000,windowsHide:true,encoding:'utf8' as const,env:{...process.env,PYTHONPATH:resolve(repo,'src')}};
   const inventory=await runFile(python,['-X','utf8','-B',resolve(root,'scripts/read-workbook-inventory.py'),'--directory',process.env.ROBIN_WORKBOOK_INVENTORY_DIRECTORY??resolve(root,'.ci/tipsters-workbook-complete-20261120'),'--query',JSON.stringify(query)],options);
   let data=JSON.parse(inventory.stdout);
   if(data.status!=='ok'){res.statusCode=503;res.end(JSON.stringify(data));return;}
   try{
    const qualified=await runFile(python,['-X','utf8','-B',resolve(root,'scripts/read-tipster-candidates.py'),'--directory',process.env.ROBIN_TIPSTER_CANDIDATES_DIRECTORY??resolve(root,'.ci/tipsters-l1-candidates-20261119')],options);
    const legacy=JSON.parse(qualified.stdout);
    if(legacy.status==='ok'){
     if(legacy.qualification?.status==='ok')gateSourceOperations(legacy,await native);
     data=decorateInventory(data,legacy,new Date().toISOString());
    }else data.qualifiedRegistryState='unavailable';
   }catch{data.qualifiedRegistryState='unavailable';}
   res.end(JSON.stringify(data));
  }catch{res.statusCode=503;res.end(JSON.stringify({status:'unavailable',message:'Index complet indisponible. Le registre Ligue 1 reste séparé.'}));}
 };
 return {name:'robin-complete-workbook',configResolved(c){root=c.root;},configureServer(s){s.middlewares.use(middleware);},configurePreviewServer(s){s.middlewares.use(middleware);}};
}
