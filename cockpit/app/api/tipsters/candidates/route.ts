export function GET() {
 return Response.json({status:'unavailable',message:'Ouvrez Robin sur A9_Mega pour consulter le registre local des candidats.'},{status:503,headers:{'Cache-Control':'no-store'}});
}
