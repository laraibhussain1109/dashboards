import {useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {ArrowUpRight,Globe2,Search} from 'lucide-react';
import {api,date,message} from '../api';
import {Badge,DashboardThumbnail,Empty,ErrorBox,Loading,PageTitle} from '../components/Shared';

export default function Gallery(){
 const[data,setData]=useState<any[]|null>(null);
 const[search,setSearch]=useState('');const[sort,setSort]=useState('newest');const[error,setError]=useState('');const[loading,setLoading]=useState(true);
 useEffect(()=>{
  let active=true;
  const timer=setTimeout(async()=>{
   setLoading(true);
   try{const result=await api(`/api/published/?search=${encodeURIComponent(search)}&sort=${sort}`);if(active){setData(result.dashboards);setError('');}}
   catch(e){if(active)setError(message(e));}
   finally{if(active)setLoading(false);}
  },200);
  return()=>{active=false;clearTimeout(timer);};
 },[search,sort]);
 return <>
  <PageTitle eyebrow="INSIGHT IS BETTER SHARED" title="Out in the world." description="Live dashboards. Real data. A shared view of what matters." action={<Link to="/templates/" className="button">Create dashboard<ArrowUpRight size={16}/></Link>}/>
  <div className="public-notice"><Globe2 size={19}/><div><strong>A public window into your work.</strong><span> Published dashboards are accessible to anyone with their URL. Source files and editing access stay private.</span></div></div>
  <div className="toolbar-row"><label className="search-input"><Search size={17}/><input aria-label="Search published dashboards" placeholder="Find a dashboard…" value={search} onChange={e=>setSearch(e.target.value)}/></label><select aria-label="Sort published dashboards" value={sort} onChange={e=>setSort(e.target.value)}><option value="newest">Recently published</option><option value="name">Name A–Z</option></select></div>
  <ErrorBox error={error}/>
  {!data?loading?<Loading/>:null:data.length?<div className="dashboard-grid" aria-busy={loading}>{data.map(d=><Link to={`/dashboards/${d.slug}/`} className="dashboard-card" key={d.slug}><div className="dashboard-thumbnail" style={{background:d.config?.theme?.background}}><DashboardThumbnail config={d.config} title={d.title}/><Badge tone="success">Live</Badge></div><div className="dashboard-card-body"><h3>{d.title}</h3><p>{d.description||`${d.config?.widgets?.length||0} saved widgets · Open to explore the live data.`}</p><div><span>Published {date(d.published_at)}</span><ArrowUpRight size={18}/></div></div></Link>)}</div>:<div className="panel"><Empty icon={search?<Search size={27}/>:<Globe2 size={30}/>} title={search?'No dashboards match your search.':'Your big picture deserves an audience.'} action={search?<button className="button secondary" onClick={()=>setSearch('')}>Clear search</button>:<Link className="button secondary" to="/create/">Open your dashboards<ArrowUpRight size={15}/></Link>}>{search?'Try a different name or description.':'Publish a dashboard from the editor to share your insights here.'}</Empty></div>}
 </>;
}
