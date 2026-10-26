/** Requires the running Django and Vite services. Uses an isolated anonymous workspace. */
import {chromium} from '@playwright/test';
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
const context=await browser.newContext({baseURL:process.env.PRISM_TEST_URL||'http://127.0.0.1:5173',viewport:{width:1440,height:1000}});
const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
const prefix=`Workspace acceptance ${Date.now()}`;const title=`${prefix} · Zeta`;const alphaTitle=`${prefix} · Alpha`;
const ensure=(value,message)=>{if(!value)throw Error(message);};
let headers={},datasetId,originalId,alphaId;
const checked=[];
async function request(url,method='GET',data){const response=await page.request.fetch(url,{method,headers,...(data?{data}:{})});ensure(response.ok(),`${method} ${url}: ${response.status()} ${await response.text()}`);return response.status()===204?null:response.json();}
function card(name){return page.locator('.managed-dashboard-card').filter({has:page.getByRole('heading',{name,exact:true})});}
async function action(name,button){await card(name).getByRole('button',{name:`Dashboard actions for ${name}`,exact:true}).click();await card(name).getByRole('button',{name:button,exact:true}).click();}
try{
 await page.goto('/create/');await page.getByRole('heading',{name:'My dashboards',exact:true}).waitFor();
 const csrf=(await context.cookies()).find(c=>c.name==='csrftoken')?.value;ensure(csrf,'CSRF cookie missing');headers={'X-CSRFToken':decodeURIComponent(csrf)};
 const imported=await page.request.post('/api/imports/',{headers,multipart:{file:{name:'workspace-test.csv',mimeType:'text/csv',buffer:Buffer.from('Region,Revenue\nNorth,20\nSouth,3\n')}}});ensure(imported.ok(),await imported.text());const staged=await imported.json();
 const dataset=await request('/api/datasets/','POST',{import_id:staged.id,table_key:staged.tables[0].key,name:`${prefix} · Dataset`});datasetId=dataset.id;
 const widgets=[{id:'actual-bar',type:'bar',title:'Revenue by Region',dataset_id:dataset.id,x:'Region',y:'Revenue',aggregation:'sum',layout:{x:0,y:0,w:8,h:4}},{id:'actual-kpi',type:'kpi',title:'Revenue total',dataset_id:dataset.id,y:'Revenue',aggregation:'sum',layout:{x:8,y:0,w:4,h:2}},{id:'actual-text',type:'text',title:'Review context',text:'Actual imported CSV.',layout:{x:8,y:2,w:4,h:2}}];
 const config={widgets,theme:{mode:'light',background:'#eef3e7',surface:'#ffffff',accent:'#3f6b4b',text:'#263732'},grid:{columns:12,gap:16,rowHeight:70,padding:24}};
 const original=await request('/api/dashboards/','POST',{title,config});originalId=original.id;
 await page.reload();await card(title).waitFor();
 ensure(await card(title).locator('.saved-widget-position').count()===3,'Thumbnail did not show actual widget count');
 ensure(await card(title).locator('.mini-layout').count()===0,'Saved dashboard used illustrative template charts');
 const position=await card(title).locator('[data-widget-id="actual-kpi"]').evaluate(el=>({x:parseFloat(el.style.left),y:parseFloat(el.style.top),width:parseFloat(el.style.width),height:parseFloat(el.style.height)}));
 ensure(Math.abs(position.x-66.6667)<.01&&position.y===0&&Math.abs(position.width-33.3333)<.01&&position.height===50,'Thumbnail did not preserve actual widget layout');
 ensure(await card(title).locator('a button').count()===0,'Dashboard actions were nested inside navigation links');checked.push('actual saved grid thumbnail, widget titles/types, no fabricated chart data');
 await action(title,'Duplicate dashboard');const copiedTitle=title+' (copy)';await card(copiedTitle).waitFor();
 ensure(page.url().endsWith('/create/'),'Duplicate action unexpectedly navigated');
 const workspace=await request('/api/workspace/');const copy=workspace.dashboards.find(d=>d.title===copiedTitle);ensure(copy&&copy.id!==original.id&&!copy.published_slug,'Duplicate was not an independent private draft');ensure(JSON.stringify(copy.config)===JSON.stringify(config),'Duplicate changed the dashboard configuration');checked.push('private dashboard duplication and list refetch');
 await action(copiedTitle,'Delete dashboard');const dialog=page.getByRole('dialog',{name:'Delete dashboard?',exact:true});await dialog.waitFor();
 ensure(await page.getByRole('button',{name:'Cancel',exact:true}).evaluate(el=>document.activeElement===el),'Confirmation did not focus the safe action');
 await page.getByRole('button',{name:'Cancel',exact:true}).click();ensure(await card(copiedTitle).count()===1,'Cancel deleted the dashboard');
 await action(copiedTitle,'Delete dashboard');await page.getByRole('dialog',{name:'Delete dashboard?',exact:true}).getByRole('button',{name:'Delete',exact:true}).click();await card(copiedTitle).waitFor({state:'detached'});
 ensure((await page.request.get(`/api/dashboards/${copy.id}/`)).status()===404,'Delete did not persist');checked.push('confirmed deletion, cancel protection, focus behavior');
 await page.getByLabel('Search your dashboards',{exact:true}).fill('no-such-dashboard-6723');await page.getByRole('heading',{name:'No dashboards match your search.',exact:true}).waitFor();await page.getByRole('button',{name:'Clear search',exact:true}).click();await card(title).waitFor();
 await page.screenshot({path:'test-results/workspace-managed.png',fullPage:true});checked.push('dashboard search empty state and reset');
 await page.goto('/datasets/');await page.getByLabel('Search datasets',{exact:true}).fill('no-such-dataset-6723');await page.getByRole('heading',{name:'No datasets match your search.',exact:true}).waitFor();await page.getByRole('button',{name:'Clear search',exact:true}).click();await page.getByRole('link').filter({has:page.getByText(`${prefix} · Dataset`,{exact:true})}).waitFor();checked.push('dataset search empty state and reset');
 const alpha=await request('/api/dashboards/','POST',{title:alphaTitle,config});alphaId=alpha.id;
 const published=await request(`/api/dashboards/${original.id}/publish/`,'POST',{});await request(`/api/dashboards/${alpha.id}/publish/`,'POST',{});
 await page.goto('/dashboards/');await page.getByLabel('Search published dashboards',{exact:true}).fill(prefix);await page.getByLabel('Sort published dashboards',{exact:true}).selectOption('name');
 await page.waitForFunction(expected=>{const titles=[...document.querySelectorAll('.dashboard-card h3')].map(el=>el.textContent);return titles.length===2&&titles[0]===expected;},alphaTitle);
 ensure(await page.locator('.saved-widget-position').count()===6,'Published thumbnails did not reflect saved configs');checked.push('published gallery A-Z sorting and actual saved layout thumbnails');
 await page.getByLabel('Search published dashboards',{exact:true}).fill('no-such-publication-6723');await page.getByRole('heading',{name:'No dashboards match your search.',exact:true}).waitFor();await page.getByRole('button',{name:'Clear search',exact:true}).click();checked.push('public gallery search reset');
 await page.goto('/create/');await card(title).waitFor();await action(title,'Delete dashboard');await page.getByRole('dialog',{name:'Delete dashboard?',exact:true}).getByText(/remove its published URL/).waitFor();await page.getByRole('dialog',{name:'Delete dashboard?',exact:true}).getByRole('button',{name:'Delete',exact:true}).click();await card(title).waitFor({state:'detached'});
 ensure((await page.request.get(`/api/published/${published.slug}/`)).status()===404,'Deleting a published dashboard left public endpoint accessible');originalId=null;checked.push('published dashboard deletion removes its public URL');
 ensure(!errors.length,'Browser errors: '+errors.join('; '));console.log(JSON.stringify({status:'passed',checks:checked,browserErrors:errors}));
}finally{
 for(const id of [originalId,alphaId])if(id)await page.request.delete(`/api/dashboards/${id}/`,{headers}).catch(()=>{});
 if(datasetId)await page.request.delete(`/api/datasets/${datasetId}/`,{headers}).catch(()=>{});
 await context.close();await browser.close();
}
