import {test,expect,type Page} from '@playwright/test';
import path from 'node:path';

const fixture=path.resolve('tests/fixtures/revenue.xlsx');
async function saved(page:Page){await page.getByRole('button',{name:'Save',exact:true}).click();await expect(page.getByText('All changes saved',{exact:true})).toBeVisible();}
async function document(page:Page,id:string){const response=await page.request.get(`/api/dashboards/${id}/`);expect(response.ok()).toBeTruthy();return response.json();}
function namedWidget(page:Page,title:string){return page.locator('.canvas-widget').filter({has:page.getByRole('heading',{name:title,exact:true})});}

// Every test owns a fresh anonymous browser workspace. Clean only that test's
// objects so reruns never pollute the public gallery or touch another workspace.
test.afterEach(async({page})=>{
 const response=await page.request.get('/api/workspace/');if(!response.ok())return;
 const workspace=await response.json();const token=(await page.context().cookies()).find(cookie=>cookie.name==='csrftoken')?.value;
 if(!token)return;const headers={'X-CSRFToken':token};
 for(const dashboard of workspace.dashboards)await page.request.delete(`/api/dashboards/${dashboard.id}/`,{headers});
 for(const dataset of workspace.datasets)await page.request.delete(`/api/datasets/${dataset.id}/`,{headers});
});

test('real workbook → customized persistent editor → filtered, versioned public dashboard',async({page,browser})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await test.step('import a selected worksheet and inspect genuine records',async()=>{
  await page.goto('/');await expect(page.getByRole('heading',{name:'A little data. A lot of possibility.'})).toBeVisible();
  await page.screenshot({path:'/tmp/prism-home.png',fullPage:true});
  await page.getByRole('link',{name:'Upload your first dataset',exact:true}).click();
  await page.getByLabel('Upload dataset file').setInputFiles(fixture);
  await expect(page.getByRole('heading',{name:'Make sure it looks right.'})).toBeVisible();
  await expect(page.getByLabel('Worksheet / table').locator('option')).toHaveCount(2);
  await page.getByLabel('Worksheet / table').selectOption({label:'Revenue · 4 rows'});
  await expect(page.getByRole('cell',{name:'North',exact:true}).first()).toBeVisible();
  await page.getByLabel('Dataset name',{exact:true}).fill('Browser acceptance · Revenue');
  await page.getByRole('button',{name:'Import dataset',exact:true}).click();
  await expect(page).toHaveURL(/\/datasets\/[\w-]+\/$/);
  await expect(page.getByRole('heading',{name:'Browser acceptance · Revenue',exact:true})).toBeVisible();
  await expect(page.getByRole('cell',{name:'400',exact:true}).first()).toBeVisible();
  await page.getByRole('button',{name:/Field insights/}).click();
  await expect(page.getByLabel('Type of Revenue')).toHaveValue('currency');
  await expect(page.getByLabel('Type of Date')).toHaveValue('date');
  await page.getByRole('button',{name:/Recommended charts/}).click();
  await expect(page.locator('.recommendation-card').first()).toBeVisible();
  await page.locator('.recommendation-card').first().click();
  await expect(page.getByRole('dialog',{name:'Chart preview'})).toBeVisible();
  await expect(page.getByRole('dialog').getByText(/Calculating from your dataset/)).toHaveCount(0);
  await page.getByRole('button',{name:'Close preview',exact:true}).click();
 });
 const datasetId=page.url().match(/\/datasets\/([^/]+)/)![1];
 await test.step('select from five distinct templates and the blank canvas',async()=>{
  await page.getByRole('link',{name:/Generate dashboard/}).click();
  await expect(page.locator('.template-card')).toHaveCount(6);
  await page.getByRole('textbox',{name:'Dashboard name',exact:true}).fill('Browser Revenue Review');
  await page.locator('.template-card').filter({has:page.getByRole('heading',{name:'Executive Command Center',exact:true})}).getByRole('button',{name:'Use this template'}).click();
  await expect(page).toHaveURL(/\/builder\/[\w-]+\/$/);
  await expect(page.getByLabel('Dashboard title',{exact:true})).toHaveValue('Browser Revenue Review');
  await expect(page.locator('.widget-kpi')).not.toHaveCount(0);
  await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
 });
 const dashboardId=page.url().match(/\/builder\/([^/]+)/)![1];
 let movedWidgetId='',movedLayout:any;
 await test.step('drag, resize, recolor and persist a real visualization',async()=>{
  const before=await document(page,dashboardId);const spec=before.config.widgets.find((w:any)=>w.type==='bar'||w.type==='horizontal_bar');expect(spec).toBeTruthy();movedWidgetId=spec.id;
  const widget=namedWidget(page,spec.title).and(page.locator(`.widget-${spec.type}`));await widget.scrollIntoViewIfNeeded();
  const handle=widget.getByLabel(`Move ${spec.title}`,{exact:true});const box=await handle.boundingBox();expect(box).toBeTruthy();
  await page.mouse.move(box!.x+box!.width/2,box!.y+box!.height/2);await page.mouse.down();await page.mouse.move(box!.x+box!.width/2+90,box!.y+box!.height/2+90,{steps:14});await page.mouse.up();
  await saved(page);const dragged=await document(page,dashboardId);const draggedSpec=dragged.config.widgets.find((w:any)=>w.id===spec.id);expect(draggedSpec.layout).not.toEqual(spec.layout);
  await widget.scrollIntoViewIfNeeded();const resize=widget.locator('.react-resizable-handle-se');const resizeBox=await resize.boundingBox();expect(resizeBox).toBeTruthy();
  await page.mouse.move(resizeBox!.x+resizeBox!.width/2,resizeBox!.y+resizeBox!.height/2);await page.mouse.down();await page.mouse.move(resizeBox!.x+resizeBox!.width/2-90,resizeBox!.y+resizeBox!.height/2+90,{steps:14});await page.mouse.up();
  await widget.getByRole('heading',{name:spec.title,exact:true}).click();
  await page.getByLabel('Accent color hex',{exact:true}).fill('#bd6542');
  await saved(page);const resized=await document(page,dashboardId);const resizedSpec=resized.config.widgets.find((w:any)=>w.id===spec.id);expect(resizedSpec.layout).not.toEqual(draggedSpec.layout);expect(resizedSpec.color).toBe('#bd6542');movedLayout=resizedSpec.layout;
  await page.reload();await expect(page.getByText('All changes saved',{exact:true})).toBeVisible();const reopened=await document(page,dashboardId);expect(reopened.config.widgets.find((w:any)=>w.id===spec.id).layout).toEqual(movedLayout);
 });
 await test.step('custom KPI, duplication, deletion, text, date filter and theme',async()=>{
  await page.getByRole('button',{name:'Elements',exact:true}).click();
  await page.getByRole('button',{name:/Custom KPI A measure/}).click();
  await page.getByLabel('Title',{exact:true}).fill('Gross margin');
  await page.getByLabel('Calculated metric',{exact:false}).fill('SUM([Revenue]) - SUM([Cost])');
  const metric=namedWidget(page,'Gross margin');await metric.scrollIntoViewIfNeeded();await expect(metric.getByText('470',{exact:true})).toBeVisible();
  await metric.getByLabel('Duplicate Gross margin',{exact:true}).click();
  await expect(namedWidget(page,'Gross margin (copy)')).toBeVisible();
  await namedWidget(page,'Gross margin (copy)').getByLabel('Delete Gross margin (copy)',{exact:true}).click();
  await expect(namedWidget(page,'Gross margin (copy)')).toHaveCount(0);
  await page.getByRole('button',{name:/Heading & text Tell the story/}).click();await page.getByLabel('Title',{exact:true}).fill('Quarterly context');await page.getByRole('textbox',{name:'Text',exact:true}).fill('Actual uploaded workbook. Clearer decisions.');
  await page.getByRole('button',{name:/Interactive filter Connect controls/}).click();
  await page.getByLabel('Title',{exact:true}).fill('Reporting period');await page.getByRole('combobox',{name:'Field',exact:true}).selectOption('Date');await page.getByRole('combobox',{name:'Control',exact:true}).selectOption('date_range');
  await page.getByLabel('Canvas settings',{exact:true}).click();await page.getByRole('combobox',{name:'Mode',exact:true}).selectOption('dark');
  await saved(page);const doc=await document(page,dashboardId);expect(doc.config.theme.mode).toBe('dark');expect(doc.config.widgets.find((w:any)=>w.title==='Gross margin').formula).toBe('SUM([Revenue]) - SUM([Cost])');expect(doc.config.widgets.find((w:any)=>w.title==='Reporting period').control).toBe('date_range');
  await page.getByRole('button',{name:'Preview',exact:true}).click();
  await expect(page.locator('.widget-library')).toHaveCount(0);await expect(page.locator('.properties-panel')).toHaveCount(0);
  await page.getByLabel('Reporting period from',{exact:true}).fill('2026-01-01');await page.getByLabel('Reporting period to',{exact:true}).fill('2026-01-31');
  await expect(namedWidget(page,'Gross margin').getByText('120',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Reset all',exact:true}).click();await expect(namedWidget(page,'Gross margin').getByText('470',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Back to editor',exact:true}).click();await page.screenshot({path:'/tmp/prism-builder.png',fullPage:true});
 });
 let publicUrl='';
 await test.step('publish and verify private/public separation in a fresh visitor session',async()=>{
  await page.getByRole('button',{name:'Publish',exact:true}).click();
  await page.getByRole('button',{name:'Publish dashboard',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your dashboard is live',exact:true})).toBeVisible();
  publicUrl=await page.getByRole('link',{name:'Open dashboard',exact:false}).getAttribute('href')||'';
  expect(publicUrl).toMatch(/^\/dashboards\//);await page.getByRole('link',{name:'Open dashboard',exact:false}).click();
  await expect(page.getByRole('heading',{name:'Browser Revenue Review',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Publish',exact:true})).toHaveCount(0);await expect(page.locator('.widget-drag-handle')).toHaveCount(0);
  const visitor=await browser.newContext({viewport:{width:1440,height:1000}});const publicPage=await visitor.newPage();await publicPage.goto(new URL(publicUrl,page.url()).href);await expect(publicPage.getByRole('heading',{name:'Browser Revenue Review',exact:true})).toBeVisible();
  await publicPage.getByLabel('Reporting period from',{exact:true}).fill('2026-01-01');await publicPage.getByLabel('Reporting period to',{exact:true}).fill('2026-01-31');
  await expect(namedWidget(publicPage,'Gross margin').getByText('120',{exact:true})).toBeVisible();
  expect([403,404]).toContain((await publicPage.request.get(`/api/datasets/${datasetId}/`)).status());
  expect([403,404]).toContain((await publicPage.request.get(`/api/dashboards/${dashboardId}/`)).status());
  await publicPage.setViewportSize({width:390,height:844});await expect(publicPage.getByRole('heading',{name:'Browser Revenue Review',exact:true})).toBeVisible();
  expect(await publicPage.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+2)).toBeTruthy();
  await publicPage.screenshot({path:'/tmp/prism-published-mobile.png',fullPage:true});await visitor.close();
 });
 await test.step('reopen authorized editor, preserve draft isolation, then republish',async()=>{
  await page.goto(`/builder/${dashboardId}/`);await expect(page.getByLabel('Dashboard title',{exact:true})).toHaveValue('Browser Revenue Review');
  await page.getByLabel('Dashboard title',{exact:true}).fill('Browser Revenue Review · Revised');await saved(page);
  const publicResponse=await page.request.get(`/api/published/${publicUrl.split('/')[2]}/`);expect((await publicResponse.json()).title).toBe('Browser Revenue Review');
  await page.getByRole('button',{name:'Republish',exact:true}).click();await page.getByRole('button',{name:'Republish dashboard',exact:true}).click();await expect(page.getByRole('heading',{name:'Your dashboard is live',exact:true})).toBeVisible();await page.getByRole('link',{name:'Open dashboard',exact:false}).click();
  await expect(page.getByRole('heading',{name:'Browser Revenue Review · Revised',exact:true})).toBeVisible();
  await page.goto('/dashboards/');await expect(page.locator(`a.dashboard-card[href="${publicUrl}"]`).getByRole('heading',{name:'Browser Revenue Review · Revised',exact:true})).toBeVisible();
  await page.screenshot({path:'/tmp/prism-gallery.png',fullPage:true});
 });
 expect(errors).toEqual([]);
});

test('invalid file errors and mobile workspace remain usable',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto('/');await expect(page.getByRole('heading',{name:'A little data. A lot of possibility.'})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+2)).toBeTruthy();
 await page.getByRole('button',{name:'Toggle navigation',exact:true}).click();await page.getByRole('link',{name:'Upload dataset',exact:true}).click();
 await page.getByLabel('Upload dataset file').setInputFiles({name:'broken.json',mimeType:'application/json',buffer:Buffer.from('{"broken":')});
 await expect(page.getByRole('alert')).toBeVisible();await expect(page.getByRole('heading',{name:'Bring your data to the table.'})).toBeVisible();
 await page.screenshot({path:'/tmp/prism-upload-mobile.png',fullPage:true});
});

test('genuine WebGL 3D pie, scatter, surface and bars render uploaded values',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/');await expect(page.getByRole('heading',{name:'A little data. A lot of possibility.'})).toBeVisible();
 const cookies=await page.context().cookies();const csrf=cookies.find(c=>c.name==='csrftoken')?.value;expect(csrf).toBeTruthy();const headers={'X-CSRFToken':csrf!};
 const stagedResponse=await page.request.post('/api/imports/',{headers,multipart:{file:{name:'grid.csv',mimeType:'text/csv',buffer:Buffer.from('X,Y,Z,Region\n1,1,2,North\n1,2,4,South\n2,1,6,East\n2,2,8,West\n')}}});expect(stagedResponse.ok()).toBeTruthy();const staged=await stagedResponse.json();
 const datasetResponse=await page.request.post('/api/datasets/',{headers,data:{import_id:staged.id,table_key:staged.tables[0].key,name:'Browser WebGL data'}});expect(datasetResponse.ok()).toBeTruthy();const dataset=await datasetResponse.json();
 const widgets=['pie3d','scatter3d','surface3d','bar3d'].map((type,index)=>({id:`webgl-${type}`,type,title:`Actual ${type}`,dataset_id:dataset.id,x:type==='pie3d'?'Region':'X',y:type==='pie3d'?'Z':'Y',z:'Z',aggregation:'sum',layout:{x:index%2*6,y:Math.floor(index/2)*5,w:6,h:5}}));
 const dashboardResponse=await page.request.post('/api/dashboards/',{headers,data:{title:'Actual uploaded values in 3D',config:{widgets,theme:{mode:'light',background:'#f3f5fa',surface:'#ffffff',text:'#18243a',accent:'#3365ed'},grid:{columns:12,gap:16,rowHeight:70,padding:24}}}});expect(dashboardResponse.ok()).toBeTruthy();const dashboard=await dashboardResponse.json();
 const published=await page.request.post(`/api/dashboards/${dashboard.id}/publish/`,{headers,data:{}});expect(published.ok()).toBeTruthy();const publication=await published.json();await page.goto(`/dashboards/${publication.slug}/`);
 await expect(page.locator('.js-plotly-plot')).toHaveCount(4);await expect(page.locator('.js-plotly-plot canvas').first()).toBeVisible();
 const traceTypes=await page.locator('.js-plotly-plot').evaluateAll(elements=>elements.map(element=>(element as any).data.map((trace:any)=>trace.type)));
 expect(traceTypes).toEqual([expect.arrayContaining(['mesh3d']),['scatter3d'],['surface'],['mesh3d']]);
 await expect(page.locator('.widget-error')).toHaveCount(0);await page.screenshot({path:'/tmp/prism-webgl.png',fullPage:true});expect(errors).toEqual([]);
});

test('calculated-field GUI, undo/redo and Top/Bottom N change genuine aggregations',async({page})=>{
 await page.goto('/');await expect(page.getByRole('heading',{name:'A little data. A lot of possibility.'})).toBeVisible();const csrf=(await page.context().cookies()).find(c=>c.name==='csrftoken')!.value;const headers={'X-CSRFToken':csrf};
 const source=await page.request.post('/api/imports/',{headers,multipart:{file:{name:'profit.csv',mimeType:'text/csv',buffer:Buffer.from('Region,Revenue,Cost\nNorth,100,80\nSouth,200,100\nNorth,300,150\nWest,400,200\n')}}});expect(source.ok()).toBeTruthy();const stage=await source.json();
 const datasetResponse=await page.request.post('/api/datasets/',{headers,data:{import_id:stage.id,table_key:stage.tables[0].key,name:'Calculated field acceptance'}});expect(datasetResponse.ok()).toBeTruthy();const dataset=await datasetResponse.json();
 const dashboardResponse=await page.request.post('/api/dashboards/',{headers,data:{title:'Calculated-field acceptance',config:{widgets:[{id:'profit-chart',type:'bar',title:'Profit by Region',dataset_id:dataset.id,x:'Region',y:'Revenue',aggregation:'sum',sort:'value',direction:'desc',layout:{x:0,y:0,w:12,h:6}}],theme:{mode:'light',background:'#f3f5fa',surface:'#ffffff',text:'#18243a',accent:'#3365ed'},grid:{columns:12,gap:16,rowHeight:70,padding:24}}}});expect(dashboardResponse.ok()).toBeTruthy();const dashboard=await dashboardResponse.json();
 await page.goto(`/builder/${dashboard.id}/`);const widget=namedWidget(page,'Profit by Region');await widget.getByRole('heading',{name:'Profit by Region',exact:true}).click();
 await page.getByRole('textbox',{name:'Calculated field name',exact:true}).fill('Profit');await page.getByRole('textbox',{name:/Row calculation/}).fill('[Revenue] - [Cost]');await page.getByRole('button',{name:'Add calculated field',exact:true}).click();
 const measure=page.getByRole('combobox',{name:'Measure · Y axis',exact:true});await expect(measure.locator('option[value="Profit"]')).toHaveCount(1);await measure.selectOption('Profit');
 const series=()=>widget.locator('.js-plotly-plot').evaluate((element:any)=>element.data?.[0]?.y);
 await expect.poll(series).toEqual([200,170,100]);await saved(page);
 await page.getByRole('button',{name:'Undo',exact:true}).click();await expect.poll(series).toEqual([400,400,200]);
 await page.getByRole('button',{name:'Redo',exact:true}).click();await expect.poll(series).toEqual([200,170,100]);
 await widget.getByRole('heading',{name:'Profit by Region',exact:true}).click();
 await page.getByRole('combobox',{name:'Ranking mode',exact:true}).selectOption('top');await page.getByRole('spinbutton',{name:'Top N',exact:true}).fill('2');await expect.poll(series).toEqual([200,170]);
 await page.getByRole('combobox',{name:'Ranking mode',exact:true}).selectOption('bottom');await page.getByRole('spinbutton',{name:'Bottom N',exact:true}).fill('1');await expect.poll(series).toEqual([100]);
 await saved(page);await page.reload();await expect.poll(series).toEqual([100]);const persisted=await document(page,dashboard.id);expect(persisted.config.widgets[0].calculated_fields).toEqual([{name:'Profit',formula:'[Revenue] - [Cost]'}]);expect(persisted.config.widgets[0].y).toBe('Profit');expect(persisted.config.widgets[0].ranking_mode).toBe('bottom');expect(persisted.config.widgets[0].limit).toBe(1);
});

test('geographic map uses uploaded coordinates and bundled offline geography',async({page})=>{
 const errors:string[]=[],external:string[]=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',request=>{const url=new URL(request.url());if(url.protocol.startsWith('http')&&!['127.0.0.1','localhost'].includes(url.hostname))external.push(request.url());});
 await page.goto('/');await expect(page.getByRole('heading',{name:'A little data. A lot of possibility.'})).toBeVisible();const csrf=(await page.context().cookies()).find(c=>c.name==='csrftoken')!.value;const headers={'X-CSRFToken':csrf};
 const response=await page.request.post('/api/imports/',{headers,multipart:{file:{name:'locations.csv',mimeType:'text/csv',buffer:Buffer.from('City,Latitude,Longitude,Revenue\nNew York,40.7128,-74.0060,120\nLondon,51.5074,-0.1278,200\nDelhi,28.6139,77.2090,300\n')}}});expect(response.ok()).toBeTruthy();const source=await response.json();const dsResponse=await page.request.post('/api/datasets/',{headers,data:{import_id:source.id,table_key:source.tables[0].key,name:'Actual uploaded coordinates'}});expect(dsResponse.ok()).toBeTruthy();const dataset=await dsResponse.json();
 const creation=await page.request.post('/api/dashboards/',{headers,data:{title:'Where our uploaded data lives',config:{widgets:[{id:'geo',type:'map',title:'Uploaded locations',dataset_id:dataset.id,x:'Longitude',y:'Latitude',z:'Revenue',series:'City',layout:{x:0,y:0,w:12,h:8}}],theme:{mode:'light',background:'#f3f5fa',surface:'#ffffff',text:'#18243a',accent:'#3365ed'},grid:{columns:12,gap:16,rowHeight:70,padding:24}}}});expect(creation.ok()).toBeTruthy();const dashboard=await creation.json();await page.goto(`/builder/${dashboard.id}/`);
 await expect(page.locator('.js-plotly-plot')).toHaveCount(1);await expect(page.locator('.scattergeo path.point')).toHaveCount(3);
 const trace=await page.locator('.js-plotly-plot').evaluate((element:any)=>({type:element.data[0].type,lon:element.data[0].lon,lat:element.data[0].lat}));expect(trace).toEqual({type:'scattergeo',lon:[-74.006,-0.1278,77.209],lat:[40.7128,51.5074,28.6139]});
 expect(await page.locator('.geo path:not(.point)').count()).toBeGreaterThan(0);await expect(page.locator('.widget-error')).toHaveCount(0);expect(external).toEqual([]);expect(errors).toEqual([]);await page.screenshot({path:'/tmp/prism-map.png',fullPage:true});
});

test('provided intervals and weighted chord ribbons use real published data',async({page,browser})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto('/');await expect(page.getByRole('heading',{name:'A little data. A lot of possibility.'})).toBeVisible();
 const csrf=(await page.context().cookies()).find(cookie=>cookie.name==='csrftoken')!.value;const headers={'X-CSRFToken':csrf};
 const sourceResponse=await page.request.post('/api/imports/',{headers,multipart:{file:{name:'intervals.csv',mimeType:'text/csv',buffer:Buffer.from('Date,From,To,Value,Lower,Upper\n2026-01-01,A,X,10,8,12\n2026-02-01,A,X,20,16,24\n2026-03-01,B,Y,30,24,36\n')}}});expect(sourceResponse.ok()).toBeTruthy();const source=await sourceResponse.json();
 const dsResponse=await page.request.post('/api/datasets/',{headers,data:{import_id:source.id,table_key:source.tables[0].key,name:'Actual supplied intervals and relationships'}});expect(dsResponse.ok()).toBeTruthy();const dataset=await dsResponse.json();
 const widgets=[{id:'band',type:'confidence_band',title:'Provided bounds',dataset_id:dataset.id,x:'Date',y:'Value',lower:'Lower',upper:'Upper',layout:{x:0,y:0,w:6,h:6}},{id:'ribbons',type:'chord',title:'Weighted relationships',dataset_id:dataset.id,x:'From',series:'To',y:'Value',aggregation:'sum',layout:{x:6,y:0,w:6,h:6}}];
 const creation=await page.request.post('/api/dashboards/',{headers,data:{title:'Actual intervals and flows',config:{widgets,theme:{mode:'light',background:'#f3f5fa',surface:'#ffffff',text:'#18243a'},grid:{columns:12,gap:16,rowHeight:70,padding:24}}}});expect(creation.ok()).toBeTruthy();const dashboard=await creation.json();
 await page.goto(`/builder/${dashboard.id}/`);await expect(page.locator('.js-plotly-plot')).toHaveCount(1);await expect(page.getByRole('img',{name:'Weighted category relationship chord diagram'})).toBeVisible();
 const trace=await page.locator('.js-plotly-plot').evaluate((element:any)=>element.data.map((item:any)=>item.y));expect(trace).toEqual([[8,16,24],[12,24,36],[10,20,30]]);
 await page.getByRole('heading',{name:'Provided bounds',exact:true}).click();await expect(page.getByRole('combobox',{name:'Provided lower bound',exact:true})).toHaveValue('Lower');await expect(page.getByRole('combobox',{name:'Provided upper bound',exact:true})).toHaveValue('Upper');
 await saved(page);const publication=await page.request.post(`/api/dashboards/${dashboard.id}/publish/`,{headers,data:{}});expect(publication.ok()).toBeTruthy();const live=await publication.json();
 const visitor=await browser.newContext();const publicPage=await visitor.newPage();await publicPage.goto(`/dashboards/${live.slug}/`);await expect(publicPage.getByRole('img',{name:'Weighted category relationship chord diagram'})).toBeVisible();await expect(publicPage.locator('.js-plotly-plot')).toHaveCount(1);
 const context=await visitor.request.get('/api/workspace/');expect(context.ok()).toBeTruthy();const visitorCsrf=(await visitor.cookies()).find(cookie=>cookie.name==='csrftoken')!.value;
 const query=await visitor.request.post(`/api/published/${live.slug}/query/`,{headers:{'X-CSRFToken':visitorCsrf},data:{widget_id:'ribbons',filters:[{field:'From',op:'eq',value:'A'}]}});expect(query.ok()).toBeTruthy();expect((await query.json()).links.map((link:any)=>link.value)).toEqual([30]);
 await expect(publicPage.getByRole('button',{name:'Publish',exact:true})).toHaveCount(0);expect(errors).toEqual([]);await publicPage.screenshot({path:'/tmp/prism-intervals-chord.png',fullPage:true});await visitor.close();
});

test('hierarchies cascade actual categories and relationship clicks preserve both fields',async({page,browser})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));await page.goto('/');await expect(page.getByRole('heading',{name:'A little data. A lot of possibility.'})).toBeVisible();
 const csrf=(await page.context().cookies()).find(cookie=>cookie.name==='csrftoken')!.value,headers={'X-CSRFToken':csrf};
 const imported=await page.request.post('/api/imports/',{headers,multipart:{file:{name:'hierarchy.csv',mimeType:'text/csv',buffer:Buffer.from('From,To,Value\nA,X,10\nA,Y,20\nB,X,30\n')}}});expect(imported.ok()).toBeTruthy();const staged=await imported.json();
 const result=await page.request.post('/api/datasets/',{headers,data:{import_id:staged.id,table_key:staged.tables[0].key,name:'Real hierarchical paths'}});expect(result.ok()).toBeTruthy();const dataset=await result.json();
 const config={crossfilter:true,widgets:[{id:'metric',type:'kpi',title:'Filtered actual value',dataset_id:dataset.id,y:'Value',aggregation:'sum',layout:{x:0,y:0,w:4,h:2}},{id:'hierarchy',type:'filter',control:'hierarchy',title:'Explore paths',dataset_id:dataset.id,filter:{field:'From',op:'eq',value:null},hierarchy_fields:['To'],layout:{x:4,y:0,w:8,h:2}},{id:'flows',type:'chord',title:'Actual weighted paths',dataset_id:dataset.id,x:'From',series:'To',y:'Value',aggregation:'sum',layout:{x:0,y:2,w:12,h:6}}],theme:{mode:'light',surface:'#fff',background:'#f3f5fa',text:'#18243a'},grid:{columns:12,gap:16,rowHeight:70,padding:24}};
 const creation=await page.request.post('/api/dashboards/',{headers,data:{title:'Hierarchical exploration',config}});expect(creation.ok()).toBeTruthy();const dashboard=await creation.json();await page.goto(`/builder/${dashboard.id}/`);
 const metric=namedWidget(page,'Filtered actual value');await expect(metric.getByText('60',{exact:true})).toBeVisible();
 await page.getByRole('combobox',{name:'Explore paths From',exact:true}).selectOption('A');await page.getByRole('combobox',{name:'Explore paths To',exact:true}).selectOption('Y');await expect(metric.getByText('20',{exact:true})).toBeVisible();
 await page.getByRole('combobox',{name:'Explore paths From',exact:true}).selectOption('B');await expect(page.getByRole('combobox',{name:'Explore paths To',exact:true})).toHaveValue('');await expect(page.getByRole('combobox',{name:'Explore paths To',exact:true}).locator('option[value="Y"]')).toHaveCount(0);await expect(metric.getByText('30',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Reset all',exact:true}).click();await expect(metric.getByText('60',{exact:true})).toBeVisible();await page.getByRole('button',{name:'A to X: 10',exact:true}).focus();await page.keyboard.press('Enter');await expect(metric.getByText('10',{exact:true})).toBeVisible();
 await saved(page);const published=await page.request.post(`/api/dashboards/${dashboard.id}/publish/`,{headers,data:{}});expect(published.ok()).toBeTruthy();const publication=await published.json();const visitor=await browser.newContext(),publicPage=await visitor.newPage();await publicPage.goto(`/dashboards/${publication.slug}/`);
 await publicPage.getByRole('combobox',{name:'Explore paths From',exact:true}).selectOption('A');await publicPage.getByRole('combobox',{name:'Explore paths To',exact:true}).selectOption('Y');await expect(namedWidget(publicPage,'Filtered actual value').getByText('20',{exact:true})).toBeVisible();expect(errors).toEqual([]);await visitor.close();
});

test('blank canvas supports real text, image and design elements without a dataset',async({page})=>{
 await page.goto('/templates/');await expect(page.getByRole('heading',{name:'Start with a little inspiration.',exact:true})).toBeVisible();
 await page.getByRole('textbox',{name:'Dashboard name',exact:true}).fill('Blank creative canvas');await page.getByRole('button',{name:'Start from scratch',exact:true}).click();await expect(page).toHaveURL(/\/builder\/[\w-]+\/$/);
 await expect(page.locator('.canvas-widget')).toHaveCount(0);await page.getByRole('button',{name:'Elements',exact:true}).click();
 await page.getByRole('button',{name:/Heading & text Tell the story/}).click();await page.getByLabel('Title',{exact:true}).fill('Team note');await page.getByRole('textbox',{name:'Text',exact:true}).fill('Our next chapter starts with clarity.');
 await page.getByRole('button',{name:/Shape & divider Give your layout/}).click();await page.getByLabel('Title',{exact:true}).fill('Accent strip');await page.getByRole('combobox',{name:'Shape',exact:true}).selectOption('divider');
 await page.getByRole('button',{name:/Image or logo Add your company/}).click();await page.getByLabel('Title',{exact:true}).fill('Company mark');await page.getByLabel('Upload image',{exact:true}).setInputFiles(path.resolve('tests/fixtures/logo.png'));await page.getByLabel('Alt text',{exact:true}).fill('Prism test logo');
 await expect(page.getByRole('img',{name:'Prism test logo',exact:true})).toBeVisible();await saved(page);await page.reload();await expect(page.getByRole('img',{name:'Prism test logo',exact:true})).toBeVisible();await expect(page.getByText('Our next chapter starts with clarity.',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Publish',exact:true}).click();await page.getByRole('button',{name:'Publish dashboard',exact:true}).click();await expect(page.getByRole('heading',{name:'Your dashboard is live',exact:true})).toBeVisible();await page.getByRole('link',{name:'Open dashboard',exact:false}).click();await expect(page.getByRole('heading',{name:'Blank creative canvas',exact:true})).toBeVisible();await expect(page.getByRole('img',{name:'Prism test logo',exact:true})).toBeVisible();
});
