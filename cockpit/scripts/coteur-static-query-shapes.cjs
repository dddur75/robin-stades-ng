let ts;try{

const fsPinned=require('node:fs'),cryptoPinned=require('node:crypto'),ModulePinned=require('node:module');
const tsPath=require.resolve('typescript',{paths:[require('node:path').resolve(__dirname,'..')]});const tsRaw=fsPinned.readFileSync(tsPath);
if(cryptoPinned.createHash('sha256').update(tsRaw).digest('hex')!=="3ae902c92cc44dace175c0e69e13a4b0899f6983c6121d76b9ab8dd5795e7675")throw Error('DEPENDENCY_PIN');
const tsModule=new ModulePinned(tsPath,module);tsModule.filename=tsPath;tsModule.paths=ModulePinned._nodeModulePaths(require('node:path').dirname(tsPath));
tsModule._compile(tsRaw.toString('utf8'),tsPath);ts=tsModule.exports;

}catch(e){if(require.main===module){console.log(JSON.stringify({schemaVersion:'coteur-static-query-error-v1',status:'UNPROVEN',reason:'DEPENDENCY_UNPROVEN',sourceReady:false}));process.exit(1);}throw Error('DEPENDENCY_UNPROVEN');}
function project(text,testLimits){
 const limits={maxNodes:200000,maxDepth:100};
 if(testLimits!==undefined){
  if(testLimits===null||typeof testLimits!=='object'||Array.isArray(testLimits)||Object.keys(testLimits).some(k=>!Object.hasOwn(limits,k)))throw Error('TEST_LIMIT_CONTRACT');
  for(const[k,v]of Object.entries(testLimits)){if(!Number.isSafeInteger(v)||v<1||v>limits[k])throw Error('TEST_LIMIT_CONTRACT');limits[k]=v;}
 }
 if(typeof text!=='string'||Buffer.byteLength(text)>2000000)throw Error('INPUT_BOUND');
 const ast=ts.createSourceFile('asset.js',text,ts.ScriptTarget.ESNext,true,ts.ScriptKind.JS);
 if(ast.parseDiagnostics.length)throw Error('UNSUPPORTED_SYNTAX');
 const candidates=[],prefixes=[],prefixSeen=new Set();let nodes=0;
 const omissions={candidates:0,prefixes:0,pieces:0,query:0};
 const forbidden=/admin|delete|remove|logout|login|auth|secret|token|password|subscription|purchase|cart|payment/i;
 function pieces(root){
  const out=[],stack=[{node:root,depth:0}];let visits=0;
  while(stack.length){
   const x=stack.pop();if(++visits>200000||x.depth>100)return null;
   if(x.segment){if(out.length>=16)return null;out.push(x.segment);continue;}
   const n=x.node;
   if(ts.isStringLiteralLike(n)){if(out.length>=16)return null;out.push({literal:n.text});}
   else if(ts.isBinaryExpression(n)&&n.operatorToken.kind===ts.SyntaxKind.PlusToken){
    if(out.length+stack.length+2>16)return null;stack.push({node:n.right,depth:x.depth+1},{node:n.left,depth:x.depth+1});
   }else if(ts.isTemplateExpression(n)){
    if(out.length+stack.length+1+2*n.templateSpans.length>16)return null;
    for(let i=n.templateSpans.length-1;i>=0;i--)stack.push({segment:{literal:n.templateSpans[i].literal.text},depth:x.depth+1},{segment:{dynamic:true},depth:x.depth+1});
    stack.push({segment:{literal:n.head.text},depth:x.depth+1});
   }else{if(out.length>=16)return null;out.push({dynamic:true});}
  }return out;
 }
 function shape(parts){
  let query=false,inValue=false,key='',path='';const pathSegments=[],keys=[];
  for(const part of parts){
   if(part.dynamic){if(!query)pathSegments.push({pathdynamic:true});else if(!inValue)return null;continue;}
   let pathPart='';
   for(const ch of part.literal){
    if(/[\x00-\x20#@\\]/.test(ch))return null;
    if(!query){if(ch==='?'){query=true;continue;}pathPart+=ch;path+=ch;}
    else if(ch==='?')return null;
    else if(!inValue){
     if(ch==='='){
      if(!/^[A-Za-z_][A-Za-z0-9_]{0,39}$/.test(key)||/auth|token|key|password|secret|session|sid/i.test(key)||keys.includes(key)||keys.length>=12)return null;
      keys.push(key);key='';inValue=true;
     }else if(ch==='&')return null;else{key+=ch;if(key.length>40)return null;}
    }else if(ch==='&'){inValue=false;key='';}
   }
   if(pathPart)pathSegments.push({literal:pathPart});
  }
  if(query&&!inValue)return null;
  if(!pathSegments.length||!('literal'in pathSegments[0]))return null;
  if(!/^(?:https:\/\/www\.coteur\.com)?\//.test(pathSegments[0].literal)||path.startsWith('//')||path.includes('%')||path.length>200||forbidden.test(path))return null;
  if(path.startsWith('https://')){
   if(!pathSegments[0].literal.startsWith('https://www.coteur.com/'))return null;
   pathSegments[0]={literal:pathSegments[0].literal.slice('https://www.coteur.com'.length)};path=path.slice('https://www.coteur.com'.length);
  }
  if(path.startsWith('//'))return null;
  return {pathSegments,literalQueryKeysObserved:keys,queryValuesElided:true,runtimeQueryContractEstablished:false,bindingEstablished:false,contractEstablished:false};
 }
 function inspect(n){
  let url,methodEvidence;
  if(ts.isIdentifier(n.expression)&&n.expression.text==='fetch'){
   const o=n.arguments[1];if(!o||!ts.isObjectLiteralExpression(o))return;
   let count=0,method;
   for(const p of o.properties){if(!ts.isPropertyAssignment(p)||!(ts.isIdentifier(p.name)||ts.isStringLiteralLike(p.name)))return;if(p.name.text==='method'){count++;method=p.initializer;}}
   if(count!==1||!ts.isStringLiteralLike(method)||method.text!=='GET')return;url=n.arguments[0];methodEvidence='explicit_fetch_option';
  }else if(ts.isPropertyAccessExpression(n.expression)){
   const name=n.expression.name.text.toLowerCase();
   if(name==='get'){url=n.arguments[0];methodEvidence='unresolved_get_wrapper';}
   else if(name==='open'&&n.arguments[0]&&ts.isStringLiteralLike(n.arguments[0])&&n.arguments[0].text==='GET'){url=n.arguments[1];methodEvidence='unresolved_open_wrapper';}
  }
  if(!url)return;const p=pieces(url);if(p===null){omissions.pieces++;return;}
  const s=shape(p);if(s===null){omissions.query++;return;}
  if(!/prono|pick|tipster/i.test(s.pathSegments.filter(x=>'literal'in x).map(x=>x.literal).join('')))return;
  const value={method:'GET',methodEvidence,sourceOffset:n.getStart(ast),...s};
  if(candidates.length<8)candidates.push(value);else omissions.candidates++;
 }
 const pending=[{node:ast,depth:0}];let maximumDepthObserved=0;
 function bounded(reason,boundKind,currentDepth){
  const prefixWitnesses=prefixes.filter(p=>!/[\x00-\x20\x7f-\x9f\s]/u.test(p.path)).slice(0,4);
  while(Buffer.byteLength(JSON.stringify(prefixWitnesses))>4096)prefixWitnesses.pop();
  return {schemaVersion:'coteur-static-query-bound-v2',status:'UNPROVEN',reason,boundKind,projectionComplete:false,observed:{visitedNodes:nodes,maximumDepthObserved,currentDepth,pendingNodes:pending.length,nodeLimit:limits.maxNodes,depthLimit:limits.maxDepth},prefixWitnesses,omissions,sourceReady:false,sourceChoices:0,sourceAPICalls:0,executedJavaScript:false,ASTConstructionMemoryBoundProven:false};
 }
 while(pending.length){
  const {node:n,depth}=pending.pop();maximumDepthObserved=Math.max(maximumDepthObserved,depth);
  if(nodes>=limits.maxNodes)return bounded('AST_NODE_BOUND','NODE_VISITS',depth);
  if(depth>limits.maxDepth)return bounded('AST_DEPTH_BOUND','DEPTH',depth);
  nodes++;
  if(ts.isCallExpression(n))inspect(n);
  if(ts.isStringLiteralLike(n)&&/^(?:https:\/\/www\.coteur\.com)?\/(?:api|tipster|prono)/.test(n.text)){
   const s=shape([{literal:n.text}]);
   if(s===null)omissions.query++;
   else if(s.pathSegments.every(x=>'literal'in x)){
    const path=s.pathSegments.map(x=>x.literal).join('');
    if(!prefixSeen.has(path)){prefixSeen.add(path);if(prefixes.length<32)prefixes.push({path,sourceOffset:n.getStart(ast),queryValuesElided:true,contractEstablished:false});else omissions.prefixes++;}
   }
  }
  const children=[];let queueExceeded=false;
  ts.forEachChild(n,child=>{if(pending.length+children.length>=limits.maxNodes){queueExceeded=true;return true;}children.push(child);});
  if(queueExceeded)return bounded('AST_NODE_BOUND','WORK_QUEUE',depth);
  for(let i=children.length-1;i>=0;i--)pending.push({node:children[i],depth:depth+1});
 }
 const complete=Object.values(omissions).every(x=>x===0);
 return {schemaVersion:'coteur-static-query-shapes-v1',status:complete?'STATIC_AST_CANDIDATES_ONLY':'STATIC_AST_PARTIAL',projectionComplete:complete,omissions,candidates,prefixes,sourceReady:false,sourceChoices:0,sourceAPICalls:0,executedJavaScript:false};
}
module.exports={project};
if(require.main===module){
 try{const fs=require('node:fs'),raw=Buffer.alloc(2000001);let size=0;while(size<raw.length){const n=fs.readSync(0,raw,size,raw.length-size,null);if(n===0)break;size+=n;}if(size>2000000)throw Error('INPUT_BOUND');const value=project(new TextDecoder('utf-8',{fatal:true}).decode(raw.subarray(0,size)));const output=JSON.stringify(value);if(Buffer.byteLength(output)>32768)throw Error('OUTPUT_BOUND');console.log(output);if(value.schemaVersion==='coteur-static-query-bound-v2')process.exitCode=1;}
 catch(e){const allowed=new Set(['INPUT_BOUND','UNSUPPORTED_SYNTAX','AST_BOUND','OUTPUT_BOUND','DEPENDENCY_PIN','TEST_LIMIT_CONTRACT']);const reason=allowed.has(e.message)?e.message:'LOCAL_UNPROVEN';console.log(JSON.stringify({schemaVersion:'coteur-static-query-error-v1',status:'UNPROVEN',reason,sourceReady:false}));process.exitCode=1;}
}
