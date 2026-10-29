import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Chart,LineController,LineElement,PointElement,LinearScale,Tooltip,Filler} from 'chart.js';
import {Thermometer,Drop,Leaf,ChartLine} from '@phosphor-icons/react';
import {dateTime} from './api';
import {chartPoints} from './chartData';
Chart.register(LineController,LineElement,PointElement,LinearScale,Tooltip,Filler);
const metrics={temperature:{label:'Nhiệt độ',unit:'°C',rawUnit:'C',color:'#c18145',Icon:Thermometer},humidity:{label:'Độ ẩm',unit:'%',rawUnit:'%',color:'#458cb4',Icon:Drop},gas:{label:'Tín hiệu gas',unit:'ADC',rawUnit:'ADC',color:'#147d78',Icon:Leaf}};
export function EnvironmentChart({rows}) {
  const [metric,setMetric]=useState('temperature'),canvas=useRef();
  const settings=metrics[metric],rawUnit=metric==='gas'?(rows.find(row=>row.payload?.readings?.gas?.quality==='valid')?.payload.readings.gas.unit||'ADC'):settings.rawUnit;
  const points=useMemo(()=>chartPoints(rows,metric,rawUnit),[rows,metric,rawUnit]);
  const valid=points.filter(point=>point.y!==null),displayUnit=metric==='gas'?rawUnit:settings.unit;
  useEffect(()=>{
    if(!canvas.current||!valid.length)return;
    const chart=new Chart(canvas.current,{type:'line',data:{datasets:[{label:settings.label,data:points,borderColor:settings.color,backgroundColor:settings.color+'12',fill:true,tension:0,spanGaps:false,pointRadius:points.length<70?2:0,pointHoverRadius:5,borderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,animation:false,parsing:false,interaction:{mode:'nearest',intersect:false},plugins:{tooltip:{callbacks:{title:items=>dateTime(items[0]?.parsed.x),label:item=>`${settings.label}: ${new Intl.NumberFormat('vi-VN',{maximumFractionDigits:2}).format(item.parsed.y)} ${displayUnit}`}}},scales:{x:{type:'linear',grid:{display:false},ticks:{maxTicksLimit:6,color:'#71827e',callback:value=>new Date(value).toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'})}},y:{title:{display:true,text:displayUnit},ticks:{maxTicksLimit:6,color:'#71827e'},grid:{color:'#edf2ef'}}}}});
    return()=>chart.destroy();
  },[points,metric,displayUnit]);
  return <section className="panel environment-chart"><div className="section-heading"><div><h2><ChartLine/> Biểu đồ theo thời gian</h2><p>Các khoảng thiếu hoặc lỗi dữ liệu được ngắt, không thay bằng số 0.</p></div></div><div className="chart-metrics" role="group" aria-label="Chỉ số trên biểu đồ">{Object.entries(metrics).map(([key,{label,Icon}])=><button key={key} aria-pressed={metric===key} className={metric===key?'active':''} onClick={()=>setMetric(key)}><Icon/>{label}</button>)}</div>{valid.length?<><div className="chart-canvas"><canvas ref={canvas} role="img" aria-label={`Biểu đồ ${settings.label}, ${valid.length} số đo, đơn vị ${displayUnit}`}>Xem các số đo trong bảng bên dưới.</canvas></div><div className="chart-footnote"><span>{valid.length} số đo hợp lệ · {displayUnit}</span><span>{dateTime(valid[0].x)} — {dateTime(valid.at(-1).x)}</span></div></>:<div className="quiet-state"><Leaf/><strong>Chưa có số đo hợp lệ cho chỉ số này</strong><p>Chọn khoảng thời gian khác hoặc kiểm tra cảm biến.</p></div>}</section>;
}
