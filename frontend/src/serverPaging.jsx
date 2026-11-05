import React, {useState,useEffect} from 'react';
import {useResource} from './context';
import {Pagination} from './ui';

export function useServerPage(path,refresh=0,size=10) {
  const [cursor,setCursor]=useState({path:null,page:1});
  const page=cursor.path===path?cursor.page:1;
  const resource=useResource(path?`${path}${path.includes('?')?'&':'?'}page=${page}&page_size=${size}`:null,refresh);
  const setPage=value=>setCursor({path,page:value});
  const data=resource.data;
  useEffect(()=>{if(data?.total_pages&&page>data.total_pages)setCursor({path,page:data.total_pages});},[data,page,path]);
  return {...resource,items:Array.isArray(data)?data:data?.items||[],total:data?.total??data?.length??0,page,pageSize:size,setPage};
}
export function ServerPager({resource,label}) {
  return <Pagination page={resource.page} pageSize={resource.pageSize} total={resource.total} onChange={resource.setPage} label={label}/>;
}
