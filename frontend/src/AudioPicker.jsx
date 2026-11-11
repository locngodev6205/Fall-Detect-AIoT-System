import React,{useEffect,useState} from 'react';
import {api,dateTime} from './api';
import {useApp,useResource,ResourceState} from './context';
import {useServerPage,ServerPager} from './serverPaging';
import {Field,Button} from './ui';

export function AudioPicker({camera,value,onChange,onReady,upload=false}) {
  const {home,notify}=useApp();
  const [search,setSearch]=useState(''),[query,setQuery]=useState(''),[busy,setBusy]=useState(false),[version,setVersion]=useState(0);
  useEffect(()=>{const timer=setTimeout(()=>setQuery(search.trim()),250);return()=>clearTimeout(timer);},[search]);
  const list=useServerPage(camera?`/homes/${home.id}/assets?audio_only=true&status=ready&camera_id=${camera}&q=${encodeURIComponent(query)}`:null,version);
  const selected=useResource(value?'/assets/'+value+'/metadata':null,version);
  const ready=!!value&&selected.data?.status==='ready'&&selected.data?.camera_id===camera;
  useEffect(()=>{onReady?.(ready);},[ready,onReady]);
  useEffect(()=>{
    if(!value||!['uploading','processing'].includes(selected.data?.status))return;
    const timer=setTimeout(()=>setVersion(n=>n+1),3000);return()=>clearTimeout(timer);
  },[value,selected.data,version]);
  async function add(file){
    if(!file)return;setBusy(true);
    try{const result=await api('/cameras/'+camera+'/assets',{method:'POST',body:file,headers:{'Content-Type':file.type||'audio/wav','X-File-Name':encodeURIComponent(file.name)}});onChange(result.id);setVersion(n=>n+1);notify('Đã nhận file âm thanh.');}
    catch(error){notify(error.message);}finally{setBusy(false);}
  }
  const options=(list.items||[]).filter(a => !a.mime || a.mime.startsWith('audio/'));
  return <div className="audio-picker">
    <Field label="Tìm âm thanh"><input type="search" value={search} placeholder="Nhập tên file…" onChange={e=>setSearch(e.target.value)}/></Field>
    <ResourceState resource={list}><Field label="Chọn file thuộc camera đích"><select value={value||''} onChange={e=>onChange(e.target.value)}><option value="">Chọn âm thanh</option>{value&&!options.some(a=>a.id===value)&&<option value={value}>{selected.data?.name||'File đang chọn'}</option>}{options.map(a=><option key={a.id} value={a.id}>{a.name} · {dateTime(a.created_at)}</option>)}</select></Field><ServerPager resource={list} label="file để chọn"/></ResourceState>
    {upload&&<Field label="Hoặc tải âm thanh mới"><input type="file" accept="audio/wav,audio/mpeg,audio/webm,audio/ogg" disabled={busy||!camera} onChange={e=>{add(e.target.files?.[0]);e.target.value='';}}/></Field>}
    {busy&&<p role="status">Đang tải âm thanh…</p>}{value&&!ready&&<p role="status">{selected.error||({uploading:'Đang tải file…',processing:'Đang chuẩn bị file…',failed:'Tải file thất bại. Hãy thử lại trong thư viện.',expired:'File đã hết hạn.',deleted:'File đã bị xóa.'})[selected.data?.status]||'Đang kiểm tra file…'} <Button kind="ghost" onClick={()=>setVersion(n=>n+1)}>Cập nhật</Button></p>}
  </div>;
}
