export const ROSTER_CAMPAIGN_ID = 'ROBIN-OLBG-ROSTER42-E2V2-20261120';
const authors = new Set([13000,46601,55960,62103,79569,119481,141750,154645,192737,197017,203797,229856,231310,246295,253741,254608,269051,375469,377758,378852,383717,411789,458096,460418,506193,507269,511157,530492,544617,590816,591729,594504,595998,602760,633943,642599,643087,644907,648478,658159,668600,669101].map(String));
export function isRosterAuthor(campaignId:string|undefined,authorUrl:string|undefined):boolean{
 const match=/^https:\/\/www\.olbg\.com\/tipsters\/tips\/([0-9]+)$/.exec(authorUrl??'');
 return campaignId===ROSTER_CAMPAIGN_ID&&Boolean(match&&authors.has(match[1]));
}
