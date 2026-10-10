let sessionToken='';
let stateCache:unknown;
let stateEtag='';
export async function api<T=any>(path:string,method='GET',body?:unknown):Promise<T>{
 const r=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-Outreach-Token':sessionToken,...(path==='/state'&&stateEtag?{'If-None-Match':stateEtag}:{})},body:body===undefined?undefined:JSON.stringify(body)});
 if(r.status===304&&path==='/state'&&stateCache)return stateCache as T;
 const data=await r.json();if(path==='/bootstrap'){sessionToken=data.token;stateCache=undefined;stateEtag='';}if(!r.ok)throw new Error(data.detail||'Request failed');if(path==='/state'&&r.ok){stateCache=data;stateEtag=r.headers.get('ETag')||'';}return data;
}
