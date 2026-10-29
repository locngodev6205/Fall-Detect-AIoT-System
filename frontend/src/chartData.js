export function chartPoints(rows,metric,unit) {
  const byTime=new Map();
  for(const row of rows){const x=new Date(row.observed_at).getTime(),reading=row.payload?.readings?.[metric];if(!Number.isFinite(x)||byTime.has(x))continue;byTime.set(x,{x,y:reading?.quality==='valid'&&reading.unit===unit&&Number.isFinite(reading.value)?reading.value:null});}
  const data=[...byTime.values()].sort((a,b)=>a.x-b.x),gaps=data.slice(1).map((point,i)=>point.x-data[i].x).filter(gap=>gap>0).sort((a,b)=>a-b);
  const threshold=Math.max(60000,(gaps[Math.floor(gaps.length/2)]||60000)*3),result=[];
  for(const point of data){if(result.length&&point.x-result.at(-1).x>threshold)result.push({x:point.x-1,y:null});result.push(point);}
  return result;
}
