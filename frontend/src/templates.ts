import type { Dataset, Theme, Widget } from './types';

export const PALETTES = {
  'Corporate Blue': ['#3365ed','#61b4ff','#12b8a0','#a5b4fc','#f4b84b','#e77191'],
  'Emerald Analytics': ['#059669','#36bda5','#60a5fa','#a3d977','#fbbf24','#a78bfa'],
  'Graphite Professional': ['#526a82','#7a9eae','#ceb37a','#99b9a5','#ab96c7','#df8e93'],
  'Futuristic Cyan': ['#22d3ee','#818cf8','#c084fc','#34d399','#fbbf24','#fb7185'],
  'Violet Intelligence': ['#8b5cf6','#b39bf5','#ec7bb3','#6cb9e8','#63c4b0','#f3bd65'],
};
const baseTheme: Theme = { mode:'light',background:'#f3f5fa',surface:'#ffffff',text:'#18243a',accent:'#3365ed',palette:PALETTES['Corporate Blue'],font:'Inter, system-ui, sans-serif' };
export const TEMPLATES = [
  {id:'executive',name:'Executive Command Center',eyebrow:'THE COMPLETE PICTURE',description:'A clear executive overview with a full-width trend, key measures, and a balanced comparison grid.',theme:{...baseTheme},layout:'executive',tags:['Overview','Balanced']},
  {id:'finance',name:'Financial Intelligence',eyebrow:'EVERY NUMBER, IN CONTEXT',description:'A measured financial workspace with a wide performance chart and a detailed summary ledger.',theme:{...baseTheme,accent:'#17675b',palette:PALETTES['Emerald Analytics'],background:'#edf3f0'},layout:'finance',tags:['Finance','Ledger']},
  {id:'sales',name:'Sales & Marketing Analytics',eyebrow:'FROM INSIGHT TO MOMENTUM',description:'A visual story of performance, category contribution, and the drivers behind your results.',theme:{...baseTheme,accent:'#8b5cf6',palette:PALETTES['Violet Intelligence'],background:'#f4f1fa'},layout:'sales',tags:['Growth','Composition']},
  {id:'operations',name:'Industrial Operations',eyebrow:'PRECISION AT EVERY LEVEL',description:'A dense, structured control room with operational measures, rankings, and a wide data table.',theme:{...baseTheme,accent:'#b96b12',palette:PALETTES['Graphite Professional'],background:'#f1f2f4'},layout:'operations',tags:['Operations','Technical']},
  {id:'lab',name:'Futuristic Analytics Lab',eyebrow:'A NEW PERSPECTIVE',description:'An immersive dark canvas with a dominant visualization, compact measures, and luminous details.',theme:{...baseTheme,mode:'dark',background:'#0c1221',surface:'#141e30',text:'#e8effc',accent:'#22d3ee',palette:PALETTES['Futuristic Cyan']},layout:'lab',tags:['Dark','Immersive']},
  {id:'blank',name:'Create From Scratch',eyebrow:'MAKE IT YOUR OWN',description:'Start with a clean canvas. Bring in charts, KPIs, filters, and text at your own pace.',theme:{...baseTheme},layout:'blank',tags:['Flexible','Blank']},
];
const id = () => crypto.randomUUID();
export function makeConfig(templateId: string, dataset: Dataset | null, recommendations: any[] = []) {
  const template = TEMPLATES.find(t=>t.id===templateId) || TEMPLATES[0];
  const widgets: Widget[] = [];
  if(template.id!=='blank' && dataset){
    const kpis = recommendations.filter(r=>r.type==='kpi').slice(0,template.id==='lab'?3:4);
    const charts = recommendations.filter(r=>!['kpi','table','summary','pivot'].includes(r.type));
    const chosen:any[] = [];
    const unique = (types:string[]) => charts.find(r=>types.includes(r.type)&&!chosen.includes(r));
    const add = (r:any) => {if(r) chosen.push(r);};
    add(unique(['line','area','smooth_line','cumulative']) || charts[0]);
    add(unique(template.id==='finance'?['waterfall','bar','horizontal_bar']:['bar','horizontal_bar','ranking']));
    add(unique(['donut','pie','treemap','histogram']));
    if(template.id==='operations') add(unique(['pareto','heatmap','box','scatter']));
    kpis.forEach((r,i)=>widgets.push({...r,id:id(),dataset_id:dataset.id,layout:{x:template.id==='lab'?9:i*3,y:template.id==='lab'?i*2:0,w:template.id==='lab'?3:3,h:2}}));
    const start = kpis.length?2:0;
    const positions:Record<string,any[]> = {
      executive:[{x:0,y:start,w:12,h:5},{x:0,y:start+5,w:7,h:5},{x:7,y:start+5,w:5,h:5}],
      finance:[{x:0,y:start,w:8,h:6},{x:8,y:start,w:4,h:3},{x:8,y:start+3,w:4,h:3}],
      sales:[{x:0,y:start,w:7,h:5},{x:0,y:start+5,w:7,h:4},{x:7,y:start,w:5,h:9}],
      operations:[{x:0,y:start,w:6,h:4},{x:6,y:start,w:6,h:4},{x:0,y:start+4,w:6,h:4},{x:6,y:start+4,w:6,h:4}],
      lab:[{x:0,y:0,w:9,h:6},{x:0,y:6,w:6,h:5},{x:6,y:6,w:6,h:5}],
    };
    chosen.forEach((r,i)=>widgets.push({...r,id:id(),dataset_id:dataset.id,layout:positions[template.id][i] || {x:0,y:12,w:6,h:4}}));
    const lastY = Math.max(0,...widgets.map(w=>w.layout.y+w.layout.h));
    const columns = dataset.columns || [];
    widgets.push({id:id(),type:'table',title:`${dataset.name} · detail`,dataset_id:dataset.id,columns:columns.slice(0,8).map((c:any)=>typeof c==='string'?c:c.name),layout:{x:0,y:lastY,w:12,h:5}} as Widget);
  }
  return {widgets,theme:{...template.theme},grid:{columns:12,gap:16,rowHeight:64,padding:24},crossfilter:false,template:template.id};
}
