import { useEffect, useState } from 'react';
export function paginate(items, requestedPage=1, pageSize=10) {
  const total=items.length,totalPages=Math.max(1,Math.ceil(total/pageSize));
  const page=Math.max(1,Math.min(requestedPage,totalPages));
  return {items:items.slice((page-1)*pageSize,page*pageSize),page,pageSize,total,totalPages};
}
export function usePagination(items,pageSize=10,resetKey='') {
  const [requested,setPage]=useState(1);
  useEffect(()=>setPage(1),[resetKey]);
  useEffect(()=>setPage(page=>Math.min(page,Math.max(1,Math.ceil(items.length/pageSize)))),[items.length,pageSize]);
  return {...paginate(items,requested,pageSize),setPage};
}
