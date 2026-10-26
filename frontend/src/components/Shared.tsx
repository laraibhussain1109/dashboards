import {useEffect,useRef,type ReactNode} from 'react';
import {AlertCircle,BarChart3,Hash,Image as ImageIcon,Layers3,LayoutDashboard,LineChart,LoaderCircle,Minus,SlidersHorizontal,Table2,Type,X} from 'lucide-react';
import {Link} from 'react-router-dom';
import type {DashboardConfig} from '../types';

export function Logo(){return <Link className="brand" to="/"><span className="brand-mark"><svg width="24" height="26" viewBox="0 0 24 26" aria-hidden="true"><path d="M12 2 23 23H1Z" fill="currentColor"/><path d="m12 2 1 21h10Z" fill="white" opacity=".45"/></svg></span><span>prism<span className="brand-dot">.</span></span></Link>;}
export function ErrorBox({error}:{error:string}){return error?<div className="error-box" role="alert"><AlertCircle size={18}/><span>{error}</span></div>:null;}
export function Loading({text='Loading your workspace…'}:{text?:string}){return <div className="loading" role="status"><LoaderCircle className="spin" size={24}/><span>{text}</span></div>;}
export function Empty({icon=<Layers3 size={28}/>,title,children,action}:{icon?:ReactNode;title:string;children?:ReactNode;action?:ReactNode}){return <div className="empty-state"><span className="empty-icon">{icon}</span><h3>{title}</h3><p>{children}</p>{action}</div>;}
export function PageTitle({eyebrow,title,description,action}:{eyebrow?:string;title:string;description?:string;action?:ReactNode}){return <div className="page-heading"><div>{eyebrow&&<div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1>{description&&<p>{description}</p>}</div>{action&&<div className="heading-action">{action}</div>}</div>;}
export function Badge({children,tone='neutral'}:{children:ReactNode;tone?:string}){return <span className={`badge ${tone}`}>{children}</span>;}

/** An illustrative template, explicitly labeled; never used as saved chart data. */
export function MiniLayout({index=0,dark=false}:{index?:number;dark?:boolean}){return <div className={`mini-layout layout-${index%6} ${dark?'dark-mini':''}`} aria-label="Template layout preview"><div className="mini-heading"><i/><i/></div><div className="mini-kpis">{[0,1,2].map(i=><div key={i}><i/><b/></div>)}</div><div className="mini-charts"><div className="mini-trend"><svg viewBox="0 0 220 80" preserveAspectRatio="none"><path d="M0 75 22 56 44 62 66 37 88 43 110 16 132 30 154 10 176 18 198 6 220 1V80H0Z" fill="currentColor" opacity=".12"/><path d="M0 75 22 56 44 62 66 37 88 43 110 16 132 30 154 10 176 18 198 6 220 1" fill="none" stroke="currentColor" strokeWidth="3"/></svg></div><div className="mini-bars">{[45,75,55,90,65].map((h,i)=><i key={i} style={{height:`${h}%`}}/>)}</div></div><div className="mini-footer"><i/><i/><i/></div></div>;}

/** The actual persisted grid, widget titles, types and colors; no invented metrics. */
export function DashboardThumbnail({config,title}:{config?:DashboardConfig;title:string}){
 const widgets=config?.widgets||[];
 const theme=config?.theme||{};
 const columns=Math.max(1,Number(config?.grid?.columns)||12);
 const rows=Math.max(1,...widgets.map(w=>(Number(w.layout?.y)||0)+(Number(w.layout?.h)||1)));
 const dark=theme.mode==='dark';
 return <div className={`saved-layout-preview ${dark?'is-dark':''}`} role="img" aria-label={`${title}: saved layout with ${widgets.length} widgets`}>
  <div className="saved-layout-grid" aria-hidden="true">
   {widgets.map(widget=>{
    const layout=widget.layout||{x:0,y:0,w:columns,h:1};
    const kind=widget.type;
    const Icon=kind==='kpi'?Hash:kind==='filter'?SlidersHorizontal:kind==='text'?Type:kind==='image'?ImageIcon:kind==='divider'?Minus:kind.includes('table')?Table2:kind.includes('line')||kind.includes('area')?LineChart:kind==='shape'?Layers3:BarChart3;
    return <div className="saved-widget-position" key={widget.id} data-widget-id={widget.id} data-widget-type={kind} style={{left:`${Math.max(0,layout.x)/columns*100}%`,top:`${Math.max(0,layout.y)/rows*100}%`,width:`${Math.min(columns,layout.w)/columns*100}%`,height:`${layout.h/rows*100}%`}}>
     <div className={`saved-widget-element saved-widget-${kind}`} title={`${widget.title||kind} · ${kind.replaceAll('_',' ')}`} style={{backgroundColor:widget.background||theme.surface||(dark?'#162a35':'#fff'),color:widget.color||theme.accent||(dark?'#83d3c1':'#3f6b4b'),borderRadius:Math.min(8,Number(widget.radius)||4)}}><Icon size={13}/><span>{widget.title||kind.replaceAll('_',' ')}</span></div>
    </div>;
   })}
   {!widgets.length&&<div className="saved-layout-empty"><LayoutDashboard size={23}/><span>Blank canvas</span></div>}
  </div>
  <div className="saved-layout-caption">Saved layout<span>{widgets.length} widget{widgets.length===1?'':'s'}</span></div>
 </div>;
}

export function ConfirmDialog({title,description,onConfirm,onClose,busy=false,confirmLabel='Delete'}:{title:string;description:string;onConfirm:()=>void;onClose:()=>void;busy?:boolean;confirmLabel?:string}){
 const container=useRef<HTMLDivElement>(null);
 const cancel=useRef<HTMLButtonElement>(null);
 const latest=useRef({busy,onClose});latest.current={busy,onClose};
 useEffect(()=>{
  const previous=document.activeElement instanceof HTMLElement?document.activeElement:null;
  cancel.current?.focus();
  function keydown(event:KeyboardEvent){
   if(event.key==='Escape'&&!latest.current.busy){event.preventDefault();latest.current.onClose();}
   if(event.key==='Tab'){
    const elements=container.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]');
    if(!elements?.length){event.preventDefault();return;}
    const first=elements[0],last=elements[elements.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
   }
  }
  document.addEventListener('keydown',keydown);
  return()=>{document.removeEventListener('keydown',keydown);previous?.focus();};
 },[]);
 return <div className="modal-backdrop" onClick={()=>!busy&&onClose()}><div ref={container} className="modal small-modal" role="dialog" aria-modal="true" aria-label={title} aria-busy={busy} onClick={e=>e.stopPropagation()}><button className="icon-button modal-close" aria-label="Close" disabled={busy} onClick={onClose}><X size={20}/></button><h2>{title}</h2><p>{description}</p><div className="modal-actions"><button ref={cancel} className="button secondary" disabled={busy} onClick={onClose}>Cancel</button><button className="button danger" disabled={busy} onClick={onConfirm}>{busy&&<LoaderCircle size={15} className="spin"/>}{busy?'Deleting…':confirmLabel}</button></div></div></div>;
}
