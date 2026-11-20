type Assessment={platform:string;label:string;reason:string;requiredAccess:string;ownerAction:string;contestAssessments?:Record<string,Assessment>};
type InventoryRow={recordId:string;candidateId?:string;sheet:string;row:number;platform:string;sourceUrl?:string|null;collectionEnabled:boolean;qualifiedRecordId?:string;qualification?:unknown;platformAssessment?:Assessment};
type InventoryPage={records:InventoryRow[];qualifiedRegistryState?:string;qualifiedCount?:number;readAt?:string;personalAccessState?:string};
type Legacy={status:string;candidates?:{id:string;origin:{sheet:string;row:number};collectionEnabled:boolean;qualification?:unknown}[];qualification?:{status:string;qualifiedCount?:number;platforms?:Assessment[];personalOverlayState?:string;personalCollectionState?:string;compatibleAccessState?:string;familyCollectionState?:string;familyNativeWinState?:string;familyOpaqueState?:string}};
export function decorateInventory(page:InventoryPage,legacy:Legacy,readAt:string):InventoryPage{
 const valid=legacy.status==='ok'&&legacy.qualification?.status==='ok';
 const byId=new Map((legacy.candidates??[]).map(r=>[r.id,r]));
 const result:InventoryPage={...page,readAt,qualifiedRegistryState:valid?'ok':'unavailable'};
 result.personalAccessState=[legacy.qualification?.personalOverlayState,legacy.qualification?.personalCollectionState,legacy.qualification?.compatibleAccessState,legacy.qualification?.familyCollectionState,legacy.qualification?.familyNativeWinState,legacy.qualification?.familyOpaqueState].includes('unavailable')?'unavailable':legacy.qualification?.personalOverlayState;
 delete result.qualifiedCount;
 if(valid)result.qualifiedCount=legacy.qualification?.qualifiedCount;
 result.records=page.records.map(r=>{
  const proposed=byId.get(r.candidateId??'');
  const prior=proposed&&proposed.origin.sheet===r.sheet&&proposed.origin.row===r.row?proposed:undefined;
  const row={...r,collectionEnabled:false};delete row.qualification;delete row.qualifiedRecordId;delete row.platformAssessment;
  if(prior)row.qualifiedRecordId=prior.id;
  if(valid){
   if(prior){row.collectionEnabled=prior.collectionEnabled;row.qualification=prior.qualification;}
   row.platformAssessment=legacy.qualification?.platforms?.find(p=>p.platform===r.platform);
   if(r.platform==='Kicktipp'&&r.sourceUrl&&row.platformAssessment?.contestAssessments){
    try{
     const url=new URL(r.sourceUrl);
     if(['www.kicktipp.fr','www.kicktipp.de'].includes(url.hostname)){
      const contest=url.pathname.split('/').filter(Boolean)[0];
      row.platformAssessment=row.platformAssessment.contestAssessments[contest]??row.platformAssessment;
     }
    }catch{/* An invalid documentary URL keeps the generic unknown assessment. */}
   }
  }
  return row;
 });return result;
}
