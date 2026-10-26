import { useEffect, useMemo, useRef, useState } from 'react';
import { Responsive, WidthProvider } from 'react-grid-layout';
import { AlertCircle, Copy, GripVertical, Maximize2, RefreshCw, Trash2, X } from 'lucide-react';
import type { Dataset, QueryResult, Theme, Widget } from '../types';
import { api } from '../api';
import Chart from './Chart';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';

const ResponsiveGrid = WidthProvider(Responsive);
export type FilterSelection = {dataset_id?:string;field:string;op:string;value:any;targets?:string[];source?:string};
type Props = {config:any;datasets:Dataset[];editing?:boolean;selected?:string|null;viewport?:string;publicSlug?:string;onSelect?:(id:string|null)=>void;onLayout?:(layout:any[],breakpoint:string)=>void;onDuplicate?:(id:string)=>void;onDelete?:(id:string)=>void;onDropWidget?:(type:string,x:number,y:number)=>void;refreshKey?:number;};
function categories(dataset:Dataset|undefined,field:string){const column=dataset?.columns?.find((c:any)=>c.name===field);return (column?.categories||[]).map((v:any)=>v&&typeof v==='object'&&'value'in v?v.value:v);}
function activeFilter(widget:Widget,value:any):FilterSelection|null{
  if(value===null||value===undefined||value===''||Array.isArray(value)&&value.every(v=>v===''||v===null)||Array.isArray(value)&&!value.length) return null;
  let op=widget.filter?.op||'eq';
  if(['multiselect','checkbox'].includes(widget.control)) op=op==='not_in'?'not_in':'in';
  if(widget.control==='search')op='contains';
  if(['date_range','number_range'].includes(widget.control))op='between';
  if(widget.control==='relative_date')op='relative_date';
  if(widget.control==='null')op=value==='empty'?'is_null':'not_null';
  return {dataset_id:widget.dataset_id,field:widget.filter?.field,op,value,targets:widget.filter?.targets,source:widget.id};
}
function FilterControl({widget,dataset,value,onChange,publicSlug}:any){
  const [hierarchy,setHierarchy]=useState<any>(null),[hierarchyError,setHierarchyError]=useState('');
  const hierarchyFields=[widget.filter?.field,...(widget.hierarchy_fields||[])].filter(Boolean);
  useEffect(()=>{
    if(widget.control!=='hierarchy'){setHierarchy(null);return;}
    const controller=new AbortController();setHierarchy(null);setHierarchyError('');
    api(publicSlug?`/api/published/${publicSlug}/filter-options/`:`/api/datasets/${widget.dataset_id}/filter-options/`,{method:'POST',body:JSON.stringify(publicSlug?{widget_id:widget.id}:{fields:hierarchyFields}),signal:controller.signal}).then(setHierarchy).catch(error=>{if(error.name!=='AbortError')setHierarchyError(error.message);});
    return()=>controller.abort();
  },[widget.control,widget.dataset_id,JSON.stringify(hierarchyFields),publicSlug]);
  const values=categories(dataset,widget.filter?.field);
  const field=widget.filter?.field;
  if(!field)return <div className="widget-empty"><AlertCircle size={20}/><span>Choose a dataset field in the properties panel.</span></div>;
  if(widget.control==='hierarchy'){
    if(hierarchyError)return <div className="widget-error" role="alert">{hierarchyError}</div>;
    if(!hierarchy)return <div className="widget-empty" role="status">Loading category relationships…</div>;
    const selections=Array.isArray(value)?value:[];
    return <div className="hierarchy-control">{hierarchyFields.map((level:string,index:number)=>{
      const paths=hierarchy.paths.filter((path:any[])=>path.slice(0,index).every((item:any,i:number)=>selections[i]===null||selections[i]===undefined||selections[i]===''||item===selections[i]));
      const choices=Array.from(new Set(paths.map((path:any[])=>path[index]))).filter(item=>item!==null&&item!==undefined&&item!=='');
      return <label key={level}>{level}<select className="filter-input" aria-label={`${widget.title} ${level}`} value={selections[index]===null||selections[index]===undefined?'':String(selections[index])} disabled={index>0&&(selections[index-1]===null||selections[index-1]===undefined||selections[index-1]==='')} onChange={event=>onChange([...selections.slice(0,index),event.target.value===''?null:choices.find(item=>String(item)===event.target.value)??event.target.value,...Array(hierarchyFields.length-index-1).fill(null)])}><option value="">All {level}</option>{choices.map((item:any,i:number)=><option key={i} value={String(item)}>{String(item)}</option>)}</select></label>;
    })}{hierarchyFields.length<2&&<small>Choose a child field in properties to add a hierarchy level.</small>}{hierarchy.truncated&&<small>The first 1,000 distinct paths are shown. Use fewer category levels for a complete selector.</small>}</div>;
  }
  if(['date_range','number_range'].includes(widget.control))return <div className="range-filter"><label>From<input aria-label={`${widget.title} from`} type={widget.control==='date_range'?'date':'number'} value={value?.[0]??''} onChange={e=>onChange([e.target.value,value?.[1]??''])}/></label><span>—</span><label>To<input aria-label={`${widget.title} to`} type={widget.control==='date_range'?'date':'number'} value={value?.[1]??''} onChange={e=>onChange([value?.[0]??'',e.target.value])}/></label>{widget.control==='number_range'&&(()=>{const col=dataset?.columns?.find((c:any)=>c.name===field);const lo=Number(col?.min),hi=Number(col?.max);return Number.isFinite(lo)&&Number.isFinite(hi)&&hi>lo?<div className="numeric-range-sliders"><input type="range" aria-label={`${widget.title} lower bound`} min={lo} max={hi} step={(hi-lo)/1000} value={value?.[0]||lo} onChange={e=>onChange([Number(e.target.value),Math.max(Number(e.target.value),Number(value?.[1])||hi)])}/><input type="range" aria-label={`${widget.title} upper bound`} min={lo} max={hi} step={(hi-lo)/1000} value={value?.[1]||hi} onChange={e=>onChange([Math.min(Number(e.target.value),Number(value?.[0])||lo),Number(e.target.value)])}/></div>:null;})()}</div>;
  if(widget.control==='relative_date')return <select className="filter-input" aria-label={widget.title||field} value={value??''} onChange={e=>onChange(e.target.value?Number(e.target.value):null)}><option value="">All dates</option>{[7,14,30,90,180,365].map(days=><option key={days} value={days}>Last {days} days</option>)}</select>;
  if(widget.control==='searchable')return <><input className="filter-input" list={`choices-${widget.id}`} aria-label={widget.title||field} value={value??''} placeholder={`Search ${field}…`} onChange={e=>onChange(e.target.value||null)}/><datalist id={`choices-${widget.id}`}>{values.map((v:any,i:number)=><option key={i} value={String(v)}/>)}</datalist></>;
  if(widget.control==='search')return <input className="filter-input" aria-label={widget.title||field} value={value??''} placeholder={`Search ${field}…`} onChange={e=>onChange(e.target.value)}/>;
  if(widget.control==='date')return <input className="filter-input" aria-label={widget.title||field} type="date" value={value??''} onChange={e=>onChange(e.target.value)}/>;
  if(widget.control==='boolean'||widget.control==='null')return <select className="filter-input" aria-label={widget.title||field} value={value??''} onChange={e=>onChange(e.target.value==='true'?true:e.target.value==='false'?false:e.target.value)}><option value="">All values</option>{widget.control==='boolean'?<><option value="true">True</option><option value="false">False</option></>:<><option value="empty">Empty</option><option value="not_empty">Not empty</option></>}</select>;
  if(['checkbox','radio'].includes(widget.control))return <div className="filter-choices">{values.map((v:any,i:number)=><label key={i}><input type={widget.control==='radio'?'radio':'checkbox'} name={widget.id} checked={widget.control==='radio'?value===v:Array.isArray(value)&&value.includes(v)} onChange={e=>onChange(widget.control==='radio'?v:e.target.checked?[...(Array.isArray(value)?value:[]),v]:(Array.isArray(value)?value:[]).filter((q:any)=>q!==v))}/>{String(v??'(Empty)')}</label>)}</div>;
  if(widget.control==='multiselect')return <select className="filter-input multi-filter" aria-label={widget.title||field} multiple value={(Array.isArray(value)?value:[]).map(String)} onChange={e=>onChange(Array.from(e.target.selectedOptions).map(o=>{const v=values.find((q:any)=>String(q)===o.value);return v??o.value;}))}>{values.map((v:any,i:number)=><option value={String(v)} key={i}>{String(v??'(Empty)')}</option>)}</select>;
  if(!values.length)return <input className="filter-input" aria-label={widget.title||field} value={value??''} placeholder={`Enter ${field} to match`} onChange={e=>onChange(e.target.value||null)}/>;
  return <select className="filter-input" aria-label={widget.title||field} value={value===null||value===undefined?'':String(value)} onChange={e=>onChange(e.target.value===''?null:values.find((q:any)=>String(q)===e.target.value)??e.target.value)}><option value="">All {field}</option>{values.map((v:any,i:number)=><option key={i} value={String(v)}>{String(v??'(Empty)')}</option>)}</select>;
}
function QueryWidget({widget,theme,filters,publicSlug,onCrossFilter,refreshKey}:any){
  const [data,setData]=useState<QueryResult|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  const querySpec={...widget};
  ['id','title','subtitle','description','layout','color','colors','background','text_color','font_size','font_family','show_legend','show_labels','show_grid','legend_position','decimals','number_format','currency','opacity','border','border_radius','shadow','padding','prefix','suffix','reason','score','group','ranking_mode'].forEach(k=>delete querySpec[k]);
  const requestKey=JSON.stringify({widget:querySpec,filters,refreshKey});
  useEffect(()=>{
    const controller=new AbortController();
    const timer=setTimeout(async()=>{setLoading(true);setError('');try{
      const local=Array.isArray(widget.filters)?widget.filters:[];
      const spec={...widget,filters:local.length?{logic:'and',conditions:[{logic:widget.filter_logic||'and',conditions:local},...filters]}:filters};
      const result=await api<QueryResult>(publicSlug?`/api/published/${publicSlug}/query/`:'/api/analytics/query/',{method:'POST',body:JSON.stringify(publicSlug?{widget_id:widget.id,filters}:spec),signal:controller.signal});
      setData(result);
    }catch(e:any){if(e.name!=='AbortError')setError(e.message||'Unable to load chart data.');}finally{if(!controller.signal.aborted)setLoading(false);}},160);
    return ()=>{clearTimeout(timer);controller.abort();};
  },[requestKey,publicSlug]);
  if(error)return <div className="widget-error" role="alert"><AlertCircle size={22}/><strong>Check this visualization</strong><span>{error}</span></div>;
  if(!data&&loading)return <div className="widget-loading"><div className="skeleton-bar"/><div className="skeleton-chart"/><span>Calculating from your dataset…</span></div>;
  return <div className={`query-widget ${loading?'is-refreshing':''}`}><Chart widget={widget} data={data!} theme={theme} onSelect={onCrossFilter}/>{loading&&<span className="chart-refreshing">Updating…</span>}</div>;
}
function WidgetContent({widget,theme,dataset,filters,publicSlug,onCrossFilter,value,onFilterChange,refreshKey}:any){
  if(widget.type==='text')return <div className="text-widget" style={{fontSize:widget.font_size||24,fontFamily:widget.font_family||theme.font,textAlign:widget.align||'left',fontWeight:widget.bold?700:400,fontStyle:widget.italic?'italic':'normal',color:widget.text_color||theme.text}}>{widget.text||'Add your text in the properties panel.'}</div>;
  if(widget.type==='image'){const safe=/^(https?:\/\/|data:image\/(png|jpeg|webp|gif);base64,)/i.test(widget.image||'');return safe?<img className="image-widget" src={widget.image} alt={widget.alt||widget.title||''} referrerPolicy="no-referrer"/>:<div className="widget-empty">Add an image in the properties panel.</div>;}
  if(widget.type==='shape')return <div className={`shape-widget shape-${widget.shape||'rectangle'}`} style={{background:widget.color||theme.accent}}/>;
  if(widget.type==='filter')return <FilterControl widget={widget} dataset={dataset} value={value} onChange={onFilterChange} publicSlug={publicSlug}/>;
  if(!widget.dataset_id)return <div className="widget-empty"><AlertCircle size={22}/><span>Connect a dataset in the properties panel.</span></div>;
  return <QueryWidget widget={widget} theme={theme} filters={filters} publicSlug={publicSlug} onCrossFilter={onCrossFilter} refreshKey={refreshKey}/>;
}
export default function DashboardCanvas(p:Props){
  const {config,datasets,editing=false}=p;
  const widgets:Widget[]=config.widgets||[];
  const theme=config.theme||{};
  const [values,setValues]=useState<Record<string,any>>({}),[crossFilters,setCrossFilters]=useState<FilterSelection[]>([]),[maximized,setMaximized]=useState<string|null>(null),[breakpoint,setBreakpoint]=useState('lg');
  const canvasRef=useRef<HTMLDivElement>(null);
  const [dropOver,setDropOver]=useState(false);
  useEffect(()=>{if(!maximized)return;const previous=document.activeElement as HTMLElement|null;const timer=setTimeout(()=>document.querySelector<HTMLElement>('.widget-modal button')?.focus(),0);const key=(e:KeyboardEvent)=>{if(e.key==='Escape')setMaximized(null);if(e.key==='Tab'){const nodes=Array.from(document.querySelectorAll<HTMLElement>('.widget-modal button,.widget-modal input,.widget-modal select,.widget-modal a[href]')).filter(n=>!n.hasAttribute('disabled'));if(nodes.length&&e.shiftKey&&document.activeElement===nodes[0]){e.preventDefault();nodes[nodes.length-1].focus();}else if(nodes.length&&!e.shiftKey&&document.activeElement===nodes[nodes.length-1]){e.preventDefault();nodes[0].focus();}}};window.addEventListener('keydown',key);return()=>{clearTimeout(timer);window.removeEventListener('keydown',key);previous?.focus();};},[maximized]);
  const filterWidgets=widgets.filter(w=>w.type==='filter');
  const selectedFilters=filterWidgets.flatMap(w=>{
    const value=Object.prototype.hasOwnProperty.call(values,w.id)?values[w.id]:w.filter?.value;
    if(w.control==='hierarchy')return [w.filter?.field,...(w.hierarchy_fields||[])].flatMap((field,index)=>{
      const selected=Array.isArray(value)?value[index]:index===0?value:null;
      return selected===null||selected===undefined||selected===''?[]:[{dataset_id:w.dataset_id,field,op:'eq',value:selected,targets:w.filter?.targets,source:w.id}];
    });
    const filter=activeFilter(w,value);return filter?[filter]:[];
  }) as FilterSelection[];
  const allFilters=[...selectedFilters,...crossFilters];
  const cols=Number(config.grid?.columns)||12;
  const layouts=useMemo(()=>{
    const base=widgets.map((w,i)=>({i:w.id,x:Math.min(Number(w.layout?.x)||0,cols-1),y:Number(w.layout?.y)||0,w:Math.max(1,Math.min(Number(w.layout?.w)||6,cols)),h:Math.max(1,Number(w.layout?.h)||4),minW:1,minH:1}));
    return {lg:base,md:config.layouts?.md||base,sm:config.layouts?.sm||base.map((w,i)=>({...w,x:(i%2)*3,y:Math.floor(i/2)*w.h,w:3})),xs:config.layouts?.xs||base.map((w,i)=>({...w,x:0,y:i*4,w:1,h:Math.max(3,w.h)}))};
  },[JSON.stringify(widgets.map(w=>({id:w.id,layout:w.layout}))),JSON.stringify(config.layouts),cols]);
  function filtersFor(w:Widget){
    const ds=datasets.find(d=>d.id===w.dataset_id);
    const computed=Array.isArray(w.calculated_fields)?w.calculated_fields.map((c:any)=>c.name):Object.keys(w.calculated_fields||{});
    const available=new Set([...(ds?.columns||[]).map((c:any)=>typeof c==='string'?c:c.name),...computed]);
    return allFilters.filter(f=>(!f.dataset_id||f.dataset_id===w.dataset_id)&&(!f.targets?.length||f.targets.includes(w.id))&&available.has(f.field)).map(({dataset_id,targets,source,...f})=>f);
  }
  function selectCross(w:Widget,field:string,value:any,additional?:{field:string;value:any}[]){
    if(!config.crossfilter)return;
    let op='eq';
    const column=datasets.find(d=>d.id===w.dataset_id)?.columns?.find((c:any)=>c.name===field);
    const granularity=w.granularity||w.time_granularity;
    if(value==='(Missing)'&&column?.missing){op='is_null';value=true;}
    else if(['date','datetime'].includes(column?.type||'')&&granularity){
      const match=String(value).match(/^(\d{4})(?:-(?:Q([1-4])|(\d{2}))(?:-(\d{2}))?)?/);
      if(match){const year=Number(match[1]),month=match[2]?(Number(match[2])-1)*3:Number(match[3]||1)-1,day=Number(match[4]||1);const start=new Date(Date.UTC(year,month,day)),end=new Date(start);
        if(granularity==='year')end.setUTCFullYear(year+1);else if(granularity==='quarter')end.setUTCMonth(month+3);else if(granularity==='month')end.setUTCMonth(month+1);else if(granularity==='week')end.setUTCDate(day+7);else end.setUTCDate(day+1);
        end.setUTCMilliseconds(end.getUTCMilliseconds()-1);op='between';value=[start.toISOString(),end.toISOString()];
      }
    }
    const related=(additional||[]).filter(item=>item.field&&item.field!==field).map(item=>({dataset_id:w.dataset_id,field:item.field,op:'eq',value:item.value,source:w.id}));
    setCrossFilters(current=>[...current.filter(f=>f.source!==w.id),{dataset_id:w.dataset_id,field,op,value,source:w.id},...related]);
  }
  const content=(w:Widget)=><WidgetContent widget={w} theme={theme} dataset={datasets.find(d=>d.id===w.dataset_id)} filters={filtersFor(w)} publicSlug={p.publicSlug} value={Object.prototype.hasOwnProperty.call(values,w.id)?values[w.id]:w.filter?.value} onFilterChange={(v:any)=>setValues(old=>({...old,[w.id]:v}))} onCrossFilter={(field:string,value:any,additional?:{field:string;value:any}[])=>selectCross(w,field,value,additional)} refreshKey={p.refreshKey}/>;
  function drop(e:React.DragEvent){e.preventDefault();setDropOver(false);const raw=e.dataTransfer.getData('prism/widget');if(!raw||!p.onDropWidget)return;const rect=canvasRef.current?.getBoundingClientRect();const x=rect?Math.max(0,Math.floor((e.clientX-rect.left)/rect.width*cols)):0;const y=rect?Math.max(0,Math.floor((e.clientY-rect.top)/(config.grid?.rowHeight||64))):0;p.onDropWidget(raw,Math.min(x,cols-2),y);}
  return <div className={`dashboard-canvas ${editing?'is-editing':'is-viewing'} viewport-${p.viewport||'desktop'} ${dropOver?'drag-over':''}`} ref={canvasRef} onDragOver={editing?e=>{if(e.dataTransfer.types.includes('prism/widget')){e.preventDefault();setDropOver(true);}}:undefined} onDragLeave={()=>setDropOver(false)} onDrop={editing?drop:undefined} style={{background:theme.background||'#f3f5fa',color:theme.text,fontFamily:theme.font,padding:config.grid?.padding??24}} onClick={e=>{if(e.target===e.currentTarget)p.onSelect?.(null);}}>
    {allFilters.length>0&&<div className="active-filter-bar"><span>Filtered view</span>{allFilters.map((f,i)=><button className="filter-chip" key={`${f.source}-${i}`} onClick={()=>{if(crossFilters.includes(f))setCrossFilters(old=>old.filter(q=>q!==f));else setValues(old=>({...old,[f.source!]:null}));}}>{f.field}: {Array.isArray(f.value)?f.value.join(' – '):String(f.value)}<X size={12}/></button>)}<button className="clear-filters" onClick={()=>{setCrossFilters([]);setValues(Object.fromEntries(filterWidgets.map(w=>[w.id,null])));}}>Reset all</button></div>}
    {config.crossfilter&&<div className="crossfilter-note">Click a chart category to filter related widgets.</div>}
    {!widgets.length?<div className="blank-canvas"><div className="blank-canvas-icon">✦</div><h2>Your next insight starts here</h2><p>{editing?'Drag a visualization onto the canvas, or add a chart from the library.':'This dashboard has no widgets yet.'}</p></div>:<ResponsiveGrid layouts={layouts} breakpoints={{lg:1100,md:800,sm:500,xs:0}} cols={{lg:cols,md:cols,sm:6,xs:1}} rowHeight={config.grid?.rowHeight||64} margin={[config.grid?.gap??16,config.grid?.gap??16]} containerPadding={[0,0]} isDraggable={editing} isResizable={editing} draggableHandle=".widget-drag-handle" draggableCancel="button,input,select,textarea,.modebar" compactType="vertical" preventCollision={false} useCSSTransforms={true} onBreakpointChange={setBreakpoint} onDragStop={(layout:any)=>p.onLayout?.(layout,breakpoint)} onResizeStop={(layout:any)=>p.onLayout?.(layout,breakpoint)} resizeHandles={['se','sw','ne','nw','e','s']}>
      {widgets.map(w=><div key={w.id} role="group" aria-label={w.title||w.type} tabIndex={editing?0:undefined} onKeyDown={e=>{if(editing&&e.target===e.currentTarget&&(e.key==='Enter'||e.key===' ')){e.preventDefault();p.onSelect?.(w.id);}}} className={`canvas-widget ${p.selected===w.id&&editing?'selected':''} widget-${w.type}`} style={{background:w.background||theme.surface||'#fff',borderRadius:w.border_radius??12,padding:w.padding??16,color:w.text_color||theme.text,opacity:w.opacity??1,boxShadow:w.shadow===false?'none':undefined,border:w.border||(theme.mode==='dark'?'1px solid #ffffff12':undefined)}} onClick={e=>{if(editing){e.stopPropagation();p.onSelect?.(w.id);}}}>
        <div className="widget-heading"><div className="widget-heading-text">{editing&&<span className="widget-drag-handle" aria-label={`Move ${w.title||w.type}`}><GripVertical size={14}/></span>}<div><h3>{w.title||({text:'Text',shape:'Shape',image:'Image'} as any)[w.type]||'Untitled visualization'}</h3>{w.subtitle&&<p>{w.subtitle}</p>}</div></div><div className="widget-actions">{editing&&<><button aria-label={`Duplicate ${w.title||w.type}`} onClick={e=>{e.stopPropagation();p.onDuplicate?.(w.id);}}><Copy size={13}/></button><button aria-label={`Delete ${w.title||w.type}`} onClick={e=>{e.stopPropagation();p.onDelete?.(w.id);}}><Trash2 size={13}/></button></>}<button aria-label={`Maximize ${w.title||w.type}`} onClick={e=>{e.stopPropagation();setMaximized(w.id);}}><Maximize2 size={13}/></button></div></div>
        {w.description&&<p className="widget-description">{w.description}</p>}<div className="widget-content">{content(w)}</div>
      </div>)}
    </ResponsiveGrid>}
    {maximized&&widgets.find(w=>w.id===maximized)&&<div className="widget-modal" role="dialog" aria-modal="true" aria-label="Expanded visualization" onClick={()=>setMaximized(null)}><div className="widget-modal-card" style={{background:theme.surface,color:theme.text}} onClick={e=>e.stopPropagation()}><div className="widget-modal-heading"><h2>{widgets.find(w=>w.id===maximized)?.title}</h2><button className="icon-button" aria-label="Close expanded visualization" onClick={()=>setMaximized(null)}><X/></button></div><div className="widget-modal-content">{content(widgets.find(w=>w.id===maximized)!)}</div></div></div>}
  </div>;
}
