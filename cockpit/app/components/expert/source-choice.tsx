export type SourceChoice = {
 market?:string;
 sourceMarketLabel?:string;
 sourceBetType?:string;
 sourceFields?:Record<string,unknown>;
 sourceWalkTruncated?:boolean;
};

export function choiceHeading(choice:SourceChoice):string {
 if(choice.sourceBetType==='native_contest_score')return 'Score prévu dans le concours :';
 if(choice.market==='source_native_opaque')return 'Choix publié (marché source non interprété) :';
 return choice.market==='source_native'?'Choix publié (Win) :':'score prévu';
}

export function OpaqueChoiceDetails({choice}:{choice:SourceChoice}) {
 if(choice.market!=='source_native_opaque')return null;
 const handicap=choice.sourceFields?.hcap;
 return <>
  {choice.sourceWalkTruncated&&<p>Capture partielle : les variantes hors du parcours restent inconnues.</p>}
  <p style={{overflowWrap:'anywhere'}}>Marché source : {choice.sourceMarketLabel??'non renseigné'} · type source : {choice.sourceBetType??'non renseigné'} · handicap source : {typeof handicap==='string'||typeof handicap==='number'?String(handicap):'non renseigné'}.</p>
  <p>Valeurs conservées telles que publiées, sans interprétation du marché. Règlement et évaluation de performance désactivés. Le type source ne constitue pas un résultat gagné.</p>
 </>;
}
