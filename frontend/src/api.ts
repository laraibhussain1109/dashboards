export class ApiError extends Error {status:number;details:any;constructor(message:string,status:number,details?:any){super(message);this.status=status;this.details=details;}}
function csrf(){return document.cookie.split('; ').find(v=>v.startsWith('csrftoken='))?.split('=').slice(1).join('=')||'';}
export async function api<T=any>(path:string,options:RequestInit={}):Promise<T>{
 const headers=new Headers(options.headers);if(options.body&&!(options.body instanceof FormData))headers.set('Content-Type','application/json');
 if(options.method&&!['GET','HEAD'].includes(options.method.toUpperCase()))headers.set('X-CSRFToken',decodeURIComponent(csrf()));
 const response=await fetch(path,{...options,headers,credentials:'same-origin'});
 const contentType=response.headers.get('content-type')||'';
 const data=contentType.includes('application/json')?await response.json():null;
 if(!response.ok)throw new ApiError(data?.error||`Request failed (${response.status}). Please try again.`,response.status,data?.details);
 return data as T;
}
export async function upload(file:File,onProgress:(progress:number)=>void):Promise<any>{
 return new Promise((resolve,reject)=>{const req=new XMLHttpRequest();req.open('POST','/api/imports/');req.setRequestHeader('X-CSRFToken',decodeURIComponent(csrf()));req.upload.onprogress=e=>{if(e.lengthComputable)onProgress(Math.round(e.loaded/e.total*100));};req.onerror=()=>reject(new Error('Upload connection interrupted. Try again.'));req.onload=()=>{let data:any;try{data=JSON.parse(req.responseText);}catch{reject(new Error('The upload service returned an unexpected response.'));return;}if(req.status>=200&&req.status<300)resolve(data);else reject(new ApiError(data.error||'Upload failed.',req.status,data.details));};const form=new FormData();form.append('file',file);req.send(form);});
}
export function message(error:unknown){return error instanceof Error?error.message:'Something went wrong. Please try again.';}
export function number(value:any){return new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(Number(value)||0);}
export function date(value?:string){return value?new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'Not published';}
