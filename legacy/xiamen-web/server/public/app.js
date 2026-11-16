const $=id=>document.getElementById(id);
let csrf='',ws=null,state=null,online=false,maps=null,mode='model',selected='',view={zoom:1,x:0,y:0},busy=false,lastUpdate=0,toastTimer,heartbeat,retryTimer,stopped=false,transport='connecting',control='available',lastStatus=0,polling=false,lastHttpStatus=0,leaseTransport=null,leasePending=false,renewing=false,retryCount=0,lastConnectionError='',lastSocketMessage=0,deviceConnected=false,lastRevision=-1,lastHttpResult=null,reconnectAt=0,pageSuspended=false,retireConnection=null,events=null,eventTransport='idle',lastEventMessage=0,eventRetryTimer=null,eventRetryCount=0,eventConnectTimer=null;
const colors={"1": "#d65d8d", "2": "#56a76c", "3": "#41abc1", "4": "#9a7cc8", "6": "#ed9251"};
function toast(message,error=false){$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
async function api(url,body,timeoutMs=12000){const abort=new AbortController();const timer=setTimeout(()=>abort.abort(),timeoutMs);try{const res=await fetch(url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-CSRF-Token':csrf}:{},body:body?JSON.stringify(body):undefined,signal:abort.signal});lastHttpResult={path:new URL(url,location.href).pathname,status:res.status,ray:res.headers.get('cf-ray')||'',at:Date.now()};const data=await res.json().catch(()=>{const err=Error(`服务返回非 JSON 响应（HTTP ${res.status}），请检查登录或网络验证`);err.status=res.status;throw err;});if(res.status===401&&url!='/api/login'&&url!='/api/session'){location.reload();throw Error('会话过期');}if(!res.ok){const err=Error(data.error||`操作失败（HTTP ${res.status}）`);err.status=res.status;throw err;}return data;}catch(err){if(err.name==='AbortError')throw Error('网络请求超时，请检查连接；控制指令不会自动重发');throw err;}finally{clearTimeout(timer);}}
$('loginForm').addEventListener('submit',async e=>{e.preventDefault();const form=new FormData(e.target);const button=e.target.querySelector('button');button.disabled=true;$('loginError').textContent='';try{const data=await api('/api/login',{username:form.get('username'),password:form.get('password')});e.target.password.value='';await enter(data);}catch(err){$('loginError').textContent=err.message;}finally{button.disabled=false;}});
async function enter(data){csrf=data.csrf;$('login').hidden=true;$('dashboard').hidden=false;connect();pollStatus();try{maps=await api('/maps.json',undefined,20000);resize();drawBase();}catch{toast('地图暂时无法加载',true);}}
function stopEvents(){clearTimeout(eventRetryTimer);clearTimeout(eventConnectTimer);if(events){events.onopen=events.onmessage=events.onerror=null;events.close();events=null;}eventTransport='idle';}
function startEvents(){
 if(stopped||pageSuspended||transport==='open'||events&&events.readyState<2||typeof EventSource==='undefined')return;
 clearTimeout(eventRetryTimer);let source;
 try{source=new EventSource('/api/events');}catch{return;}
 events=source;eventTransport='connecting';let openedAt=0;
 const timer=eventConnectTimer=setTimeout(()=>failed('HTTPS 推送连接超时'),10000);
 const failed=reason=>{if(events!==source)return;clearTimeout(timer);source.onopen=source.onmessage=source.onerror=null;source.close();events=null;eventTransport='failed';lastConnectionError=reason;if(openedAt&&Date.now()-openedAt>=10000)eventRetryCount=0;updateConnection();if(!stopped&&!pageSuspended&&transport!=='open'){const delay=Math.min(30000,2500*2**Math.min(eventRetryCount++,4))*(.8+Math.random()*.4);eventRetryTimer=setTimeout(startEvents,delay);}};
 source.onopen=()=>{if(events!==source)return;clearTimeout(timer);openedAt=Date.now();eventTransport='open';lastEventMessage=Date.now();updateConnection();};
 source.onmessage=e=>{if(events!==source)return;lastEventMessage=Date.now();try{receivePacket(JSON.parse(e.data));}catch{failed('HTTPS 推送数据无效');}};
 source.onerror=()=>failed('HTTPS 推送不可用，继续使用状态查询');
}
let lastTelemetryRevision=-1;
function receivePacket(packet){
 if(packet.type==='status'){applyStatus(packet);return;}
 if(packet.type!=='telemetry'||!acceptRevision(packet))return;
 // WSS/SSE can both deliver the same sample during transport handover.
 // Only a new device sample may renew telemetry freshness.
 if(Number.isSafeInteger(packet.revision)&&packet.revision===lastTelemetryRevision)return;
 if(!ingestFrame(packet.state))return;
 if(Number.isSafeInteger(packet.revision))lastTelemetryRevision=packet.revision;
 lastUpdate=Date.now();lastStatus=Date.now();online=true;deviceConnected=true;render();
}
function acceptRevision(packet){if(Number.isSafeInteger(packet.revision)){if(packet.revision<lastRevision)return false;lastRevision=packet.revision;}return true;}
function applyStatus(packet){if(!acceptRevision(packet))return false;online=packet.online;deviceConnected=packet.deviceConnected??packet.online;control=packet.control||'available';leaseTransport=packet.controlTransport||null;lastStatus=Date.now();if(packet.telemetryAgeMs!=null)lastUpdate=Date.now()-packet.telemetryAgeMs;updateConnection();return true;}
async function pollStatus(){if(stopped||pageSuspended||polling)return;polling=true;try{const packet=await api((transport==='open'&&Date.now()-lastSocketMessage<9000||eventTransport==='open'&&Date.now()-lastEventMessage<12000)?'/api/status?summary=1':'/api/status',undefined,8000);lastHttpStatus=Date.now();if(applyStatus(packet)&&packet.state&&ingestFrame(packet.state)){render();}}catch(err){lastConnectionError=err.message;updateConnection();}finally{polling=false;}}
async function renewHttpLease(){if(stopped||pageSuspended||renewing||document.hidden||!(leaseTransport==='http'&&control==='owned'||leasePending)||Date.now()-lastHttpStatus>7000&&!(eventTransport==='open'&&Date.now()-lastEventMessage<12000))return;renewing=true;try{await api('/api/heartbeat',{},6000);}catch(err){lastConnectionError=err.message;if(err.status===409){leaseTransport=null;control='available';}updateConnection();}finally{renewing=false;}}
function scheduleReconnect(){if(stopped||pageSuspended)return;const delay=Math.min(30000,2500*2**Math.min(retryCount++,4))*(.8+Math.random()*.4);clearTimeout(retryTimer);reconnectAt=Date.now()+delay;retryTimer=setTimeout(connect,delay);}
function connect(){
 if(stopped||pageSuspended||ws&&ws.readyState<3)return;
 clearTimeout(retryTimer);clearInterval(heartbeat);reconnectAt=0;transport='connecting';updateConnection();
 let socket;
 try{const url=new URL('/ws/browser',location.href);url.protocol=location.protocol==='https:'?'wss:':'ws:';socket=new WebSocket(url.href);}
 catch{transport='failed';lastConnectionError='实时连接建立失败，正在尝试 HTTPS';updateConnection();startEvents();scheduleReconnect();return;}
 ws=socket;let retired=false,openedAt=0,beatTimer=null,closeTimer=null;
 const current=()=>!retired&&ws===socket;
 const cleanup=()=>{clearTimeout(timeout);clearTimeout(closeTimer);clearInterval(beatTimer);};
 const finish=message=>{
  if(!current())return;retired=true;cleanup();
  // A late open from a timed-out mobile handshake must not become a live orphan.
  socket.onopen=()=>{try{socket.close(1000,'Superseded connection');}catch{}};
  socket.onmessage=null;socket.onclose=null;socket.onerror=()=>{};ws=null;retireConnection=null;
  if(openedAt&&Date.now()-openedAt>=10000)retryCount=0;
  transport='failed';lastConnectionError=message;updateConnection();if(!pageSuspended){startEvents();pollStatus();scheduleReconnect();}
 };
 const close=(code,reason)=>{
  if(!current()||closeTimer)return;
  clearTimeout(timeout);clearInterval(beatTimer);transport='failed';lastConnectionError=reason;updateConnection();pollStatus();
  // Some mobile failures never deliver close. Retire the attempt after a bounded wait.
  closeTimer=setTimeout(()=>finish(reason),1500);
  try{socket.close(code,reason);}catch{finish(reason);}
 };
 const timeout=setTimeout(()=>close(4002,'Connection timeout'),10000);
 retireConnection=()=>{if(!current())return;try{socket.close(1000,'Page hidden');}catch{}finish('页面已离开，返回后恢复连接');};
 socket.onopen=()=>{
  if(!current()){try{socket.close();}catch{}return;}
  clearTimeout(timeout);openedAt=Date.now();lastSocketMessage=Date.now();transport='open';stopEvents();lastConnectionError='';updateConnection();
  heartbeat=beatTimer=setInterval(()=>{
   if(!current()){clearInterval(beatTimer);return;}
   if(Date.now()-lastSocketMessage>9000){close(4000,'Heartbeat timeout');return;}
   if(socket.readyState===1){try{socket.send(JSON.stringify({type:'heartbeat'}));}catch{close(4003,'Heartbeat send failed');}}
  },3000);
 };
 socket.onmessage=e=>{
  if(!current())return;lastSocketMessage=Date.now();
  try{const packet=JSON.parse(e.data);receivePacket(packet);}
  catch{lastConnectionError='状态数据无效';updateConnection();}
 };
 socket.onclose=e=>finish(`实时连接关闭（${e.code}${e.reason?' · '+e.reason:''}）`);
 socket.onerror=()=>close(4003,'WebSocket connection error');
}
function connectionReport(){return {website:location.origin+location.pathname,browser:navigator.userAgent,transport,statusChannel:transport==='open'?'WebSocket':eventTransport==='open'?'HTTPS push':'HTTPS polling',eventTransport,websocketState:ws?.readyState??null,simulation:state?.status||'unknown',deviceOnline:online,deviceConnected,stateAgeSeconds:lastUpdate?Math.round((Date.now()-lastUpdate)/1000):null,lastError:lastConnectionError||null,lastHttp:lastHttpResult?{path:lastHttpResult.path,status:lastHttpResult.status,ray:lastHttpResult.ray}:null,retryInSeconds:reconnectAt?Math.max(0,Math.ceil((reconnectAt-Date.now())/1000)):0};}
function updateConnection(){if($('connectionReport'))$('connectionReport').textContent=JSON.stringify(connectionReport(),null,2);const known=Date.now()-lastStatus<7000;const live=known&&online&&Date.now()-lastUpdate<(state?.status==='starting'?45000:6000);const connected=transport==='open';const pushed=eventTransport==='open'&&Date.now()-lastEventMessage<12000;const httpReady=Date.now()-lastHttpStatus<7000;const canControl=live&&(connected||pushed||httpReady)&&control!=='busy';const c=$('connection');c.classList.toggle('offline',!live);c.replaceChildren();const dot=document.createElement('i');let label=!known?'状态连接中 · 仿真状态未知':!online?(deviceConnected?'仿真状态更新超时':'仿真端离线'):!live?'仿真状态更新超时':control==='busy'?'仿真端在线 · 其他会话控制中':!connected&&pushed?'仿真端在线 · HTTPS 控制（实时推送）':!connected&&httpReady?'仿真端在线 · HTTPS 控制':!connected?'实时连接恢复中':'仿真端已连接';c.append(dot,document.createTextNode(label));c.title=lastConnectionError;$('mapNotice').hidden=live&&canControl&&state?.status==='running';$('mapNotice').textContent=!known?'无法确认仿真状态 · 正在重试网络连接':!online?(deviceConnected?'仿真端已连接，但数据更新超时 · 控制已禁用':'Windows 仿真端离线 · 控制已禁用'):!live?'仿真数据更新超时 · 控制已禁用':control==='busy'?'其他会话持有控制权 · 可查看实时状态':!connected&&pushed?'已通过 HTTPS 实时推送连接，可正常控制':!connected&&httpReady?'实时连接不可用 · 已切换 HTTPS，可正常控制':state?.status==='paused'?'仿真已暂停 · 点击继续恢复':state?.status==='starting'?'正在加载路网，请稍候…':'仿真已就绪 · 等待启动';for(const button of document.querySelectorAll('.controls button,.vehicle-detail button,.signal-card button'))button.disabled=!canControl||busy;for(const input of document.querySelectorAll('.controls input,.controls select,.signal-card input,.signal-card select'))input.disabled=!canControl||busy;$('freshness').textContent=lastUpdate?`更新于 ${((Date.now()-lastUpdate)/1000).toFixed(1)} 秒前`:'—';}
async function command(action,args={}){if(!online||!state||busy||control==='busy'||Date.now()-lastStatus>=7000||transport!=='open'&&Date.now()-lastHttpStatus>=7000&&!(eventTransport==='open'&&Date.now()-lastEventMessage<12000))return;const mode=control==='owned'&&leaseTransport==='http'?'http':transport==='open'?'websocket':'http';busy=true;leasePending=mode==='http';updateConnection();try{const result=await api('/api/command',{action,args,generation:state.generation,transport:mode},action==='start'||action==='line_start'?50000:12000);toast(result.message||'操作已执行');}catch(err){toast(err.message,true);}finally{leasePending=false;await pollStatus();busy=false;updateConnection();}}
for(const b of document.querySelectorAll('[data-action]'))b.onclick=()=>command(b.dataset.action);
$('setRate').onclick=()=>command('rate',{value:Number($('rateInput').value)});
$('lineStart').onclick=()=>command('line_start',{line:Number($('line').value)});
$('lineStop').onclick=()=>command('line_stop',{line:Number($('line').value)});
$('setLineSpeed').onclick=()=>command('line_speed',{line:Number($('line').value),value:Number($('lineSpeed').value)});
$('setHeadway').onclick=()=>command('headway',{line:Number($('line').value),value:Number($('headway').value)});
$('busStart').onclick=()=>command('bus_start');$('demand').onchange=()=>command('demand',{enabled:$('demand').checked});
$('setVehicleSpeed').onclick=()=>command('vehicle_speed',{id:selected,value:Number($('vehicleSpeed').value)});
$('autoSpeed').onclick=()=>command('vehicle_speed',{id:selected,value:-1});$('vehicleHalt').onclick=()=>command('vehicle_speed',{id:selected,value:0});
$('depotEnter').onclick=()=>command('depot_enter',{id:selected,track:0});$('depotRelease').onclick=()=>command('depot_release',{id:selected});
$('busStop').onclick=()=>{const v=state?.vehicles.find(v=>v.id===selected);if(v)command('bus_stop',{id:String(v.line)});};
$('holdSignal').onclick=()=>command('signal_hold',{id:$('signal').value,seconds:Number($('signalSeconds').value)});
$('releaseSignal').onclick=()=>command('signal_release',{id:$('signal').value});$('signal').onchange=signalInfo;
$('logout').onclick=async()=>{try{await api('/api/logout',{});}finally{stopped=true;stopEvents();clearTimeout(retryTimer);ws?.close();location.reload();}};
$('vehicleSearch').oninput=renderVehicles;
function render(){const statuses={ready:'准备就绪',starting:'正在加载路网',paused:'仿真已暂停',running:'仿真运行中'};$('statusText').textContent=statuses[state.status]||state.status;$('network').textContent=state.network;const t=Math.floor(state.time);$('time').textContent=[Math.floor(t/3600),Math.floor(t/60)%60,t%60].map(n=>String(n).padStart(2,'0')).join(':');const count=$('vehicleCount');count.replaceChildren(document.createTextNode(`${state.vehicles.length} `));const em=document.createElement('em');em.textContent='辆';count.append(em);const trains=state.vehicles.filter(v=>v.kind==='train').length;$('fleetSplit').textContent=`地铁 ${trains} · 公交 ${state.vehicles.length-trains}`;$('signalCount').firstChild.textContent=`${state.signals.length} `;const held=state.signals.filter(s=>s.mode==='红灯保持').length;$('signalSplit').textContent=`红灯保持 ${held} · 自动闭塞 ${state.signals.filter(s=>s.mode==='自动闭塞').length}`;$('rateText').firstChild.textContent=`${state.rate} `;if($('actualRate'))$('actualRate').textContent=Number.isFinite(state.actual_rate)?`实际 ${state.actual_rate.toFixed(1)}× · 目标 ${state.rate}×`:'实际倍率：等待测量';renderAssessment();
 const old=$('signal').value;const ids=state.signals.map(s=>s.id).join(',');if($('signal').dataset.ids!==ids){$('signal').replaceChildren(...state.signals.map(s=>{const o=document.createElement('option');o.value=s.id;o.textContent=s.id;return o;}));$('signal').dataset.ids=ids;if(state.signals.some(s=>s.id===old))$('signal').value=old;}signalInfo();
 const eventKey=JSON.stringify(state.events.slice(-4));if($('events').dataset.snapshot!==eventKey){$('events').dataset.snapshot=eventKey;$('events').replaceChildren(...state.events.slice(-4).reverse().map(event=>{const li=document.createElement('li');li.textContent=event;return li;}));}const flow=state.mobility||{};if($('peopleSummary'))$('peopleSummary').textContent=`候车 ${flow.people_waiting||0} · 步行 ${flow.people_walking||0} · 乘车 ${flow.people_onboard||0} · 已到达 ${flow.people_arrived||0} 人`;renderVehicles();updateConnection();drawLive();}
function signalInfo(){const signal=state?.signals.find(s=>s.id===$('signal').value);$('signalInfo').textContent=signal?`${signal.mode} · 灯色 ${signal.state} · 占用 ${signal.occupied}${signal.remaining?` · 剩余 ${signal.remaining.toFixed(0)} 仿真秒`:''}`:'启动后显示实际灯色与占用。';}
const vehicleRows=new Map();
function renderVehicles(){
 if(!state)return;
 const query=$('vehicleSearch').value.toLowerCase();
 const items=state.vehicles.filter(v=>v.id.toLowerCase().includes(query)),wanted=new Set(items.map(v=>v.id));
 for(const [id,row] of vehicleRows)if(!wanted.has(id)){row.remove();vehicleRows.delete(id);}
 if(items.length)$('vehicles').querySelector('.empty')?.remove();
 for(const v of items){
  let row=vehicleRows.get(v.id);
  if(!row){row=document.createElement('button');row.className='vehicle-row';const info=document.createElement('div'),name=document.createElement('strong'),meta=document.createElement('small'),speed=document.createElement('span');info.append(name,meta);row.append(info,speed);row.onclick=()=>{selected=v.id;renderVehicles();drawLive();};vehicleRows.set(v.id,row);$('vehicles').append(row);}
  row.classList.toggle('selected',v.id===selected);
  const values=[v.id,v.kind==='train'?`${v.line} 号线 · ${v.depot}`:`公交 · ${v.line}`,`${v.speed.toFixed(1)} km/h`];
  [row.children[0].children[0],row.children[0].children[1],row.children[1]].forEach((el,i)=>{if(el.textContent!==values[i])el.textContent=values[i];});
 }
 if(!items.length&&!$('vehicles').querySelector('.empty')){const hint=document.createElement('p');hint.className='empty';hint.textContent='暂无匹配的实际车辆';$('vehicles').append(hint);}
 const v=state.vehicles.find(v=>v.id===selected);$('vehicleDetail').hidden=!v;
 if(v){$('selectedId').textContent=v.id;$('selectedInfo').textContent=`${v.people} 人 · ${v.edge} · ${v.speed.toFixed(1)} km/h`;$('selectedBadge').textContent='已选中';$('depotEnter').hidden=$('depotRelease').hidden=v.kind!=='train';$('busStop').hidden=v.kind!=='bus';}else $('selectedBadge').textContent='SELECT A VEHICLE';
}
let previousVehicles=new Map(),previousPeople=new Map(),frameArrived=0,blendDuration=250,animationHandle=0;
function ingestFrame(next){
 if(!next||!Number.isFinite(next.time)||!Array.isArray(next.vehicles))return false;
 const now=performance.now(),gap=now-frameArrived,sameGeneration=state&&state.generation===next.generation;
 // A late polling reply must never rewind an already accepted simulation.
 if(sameGeneration&&next.time<state.time)return false;
 // Repeated HTTP snapshots preserve the existing interpolation clock.
 if(sameGeneration&&state.time===next.time&&state.status===next.status){state=next;return true;}
 const continuous=sameGeneration&&state.status==='running'&&next.status==='running'&&next.time>state.time&&gap<1200&&online&&Date.now()-lastUpdate<=1500&&!document.hidden;
 function capture(items,person){
  return new Map((items||[]).map(v=>[v.id,{...v,position:displayPoint(v,person,'model'),geo:displayPoint(v,person,'geo')}]));
 }
 // Capture where an unfinished animation currently is, not its previous target.
 // Uneven packet intervals otherwise restart it at a different coordinate.
 previousVehicles=continuous?capture(state.vehicles,false):new Map();
 previousPeople=continuous?capture(state.people,true):new Map();
 blendDuration=Math.max(100,Math.min(400,gap||250));frameArrived=now;state=next;
 if(animationHandle)cancelAnimationFrame(animationHandle);animationHandle=0;
 if(continuous)animationHandle=requestAnimationFrame(animateTraffic);
 return true;
}
function displayPoint(v,person=false,projection=mode){
 const key=projection==='geo'?'geo':'position',target=v[key],old=(person?previousPeople:previousVehicles).get(v.id);
 if(!target||!old?.[key]||state.status!=='running'||!online||Date.now()-lastUpdate>1500)return target;
 if(person?(old.mode!==v.mode||old.vehicle!==v.vehicle):old.edge!==v.edge)return target;
 if(projection==='geo'&&old.geoSegment!==v.geoSegment)return target;
 const alpha=Math.min(1,Math.max(0,(performance.now()-frameArrived)/blendDuration));
 return [old[key][0]+(target[0]-old[key][0])*alpha,old[key][1]+(target[1]-old[key][1])*alpha];
}
function animateTraffic(){
 animationHandle=0;if(document.hidden||!online||!state||state.status!=='running'||Date.now()-lastUpdate>1500)return;
 drawLive();if(performance.now()-frameArrived<blendDuration)animationHandle=requestAnimationFrame(animateTraffic);
}
const base=$('basemap'),live=$('liveMap');let width=0,height=0,dpr=1;
function resize(){const rect=base.parentElement.getBoundingClientRect();width=rect.width;height=rect.height;dpr=Math.min(devicePixelRatio||1,2);for(const c of [base,live]){c.width=width*dpr;c.height=height*dpr;c.getContext('2d').setTransform(dpr,0,0,dpr,0,0);}drawBase();drawLive();}
if(typeof ResizeObserver!=='undefined')new ResizeObserver(resize).observe(base.parentElement);else window.addEventListener('resize',resize);
function transform(){const bounds=maps?.[mode]?.bounds||[-18000,-1000,32000,30000],cx=(bounds[0]+bounds[2])/2,cy=(bounds[1]+bounds[3])/2;const scale=Math.min((width-50)/(bounds[2]-bounds[0]),(height-50)/(bounds[3]-bounds[1]))*view.zoom;return {cx,cy,scale,xy:p=>[width/2+(p[0]-cx)*scale+view.x,height/2-(p[1]-cy)*scale+view.y]};}
function line(ctx,points,xy){if(!points?.length)return;const [x,y]=xy(points[0]);ctx.moveTo(x,y);for(let i=1;i<points.length;i++){const p=xy(points[i]);ctx.lineTo(p[0],p[1]);}}
function drawBase(){if(!width)return;const ctx=base.getContext('2d');ctx.clearRect(0,0,width,height);ctx.fillStyle='#0c1825';ctx.fillRect(0,0,width,height);if(!maps)return;const {xy}=transform(),data=maps[mode];if(mode==='geo'){for(const kind of ['land','water','green','coast','road','future_rail','rail']){ctx.beginPath();for(const f of data.features){if(f.kind!==kind)continue;line(ctx,f.points,xy);}ctx.strokeStyle={land:'#293329',water:'#1b3b4b',green:'#244036',coast:'#3e6172',road:'#263d50',future_rail:'#4d4562',rail:'#528476'}[kind];ctx.lineWidth=kind==='rail'?1.6:kind==='coast'?1.1:.7;ctx.stroke();}}else{ctx.beginPath();for(const e of data.edges)line(ctx,e.points,xy);ctx.strokeStyle='#314860';ctx.lineWidth=1.2;ctx.stroke();}for(const station of data.stations){const p=xy(station.point);ctx.beginPath();ctx.arc(p[0],p[1],2.3,0,Math.PI*2);ctx.fillStyle=colors[station.line]||'#779cb3';ctx.fill();if(view.zoom>1.7){ctx.fillStyle='#9db2bf';ctx.font='9px "Microsoft YaHei"';ctx.fillText(station.name,p[0]+5,p[1]-5);}}}
function drawLive(){
 if(!width)return;const ctx=live.getContext('2d');ctx.clearRect(0,0,width,height);if(!state||!maps)return;
 const {xy}=transform();const visible=p=>p[0]>-25&&p[0]<width+25&&p[1]>-25&&p[1]<height+25;
 for(const signal of state.signals){
  const point=mode==='model'?signal.position:maps.geo.signalPoints?.[signal.id];if(!point)continue;const p=xy(point);if(!visible(p))continue;
  ctx.beginPath();ctx.arc(p[0],p[1],signal.mode==='红灯保持'?3.5:1.7,0,Math.PI*2);ctx.fillStyle=signal.mode==='红灯保持'?'#ff8787':signal.state.toLowerCase().includes('g')?'#50b990':'#886264';ctx.fill();
 }
 for(const v of state.vehicles){
  const point=displayPoint(v);if(!point)continue;const [x,y]=xy(point);if(!visible([x,y]))continue;
  if(v.id===selected){ctx.beginPath();ctx.arc(x,y,15,0,Math.PI*2);ctx.strokeStyle='#ffffff';ctx.lineWidth=2;ctx.stroke();}
  ctx.fillStyle=v.kind==='bus'?'#ffb454':colors[v.line]||'#6bafff';ctx.strokeStyle='#ffffff';ctx.lineWidth=1.3;
  if(v.kind==='bus'){ctx.fillRect(x-5,y-7,10,14);ctx.strokeRect(x-5,y-7,10,14);ctx.fillStyle='#503716';ctx.fillRect(x-3,y-4,6,2);}
  else{ctx.fillRect(x-10,y-4,20,8);ctx.strokeRect(x-10,y-4,20,8);ctx.fillStyle='#142438';for(let dx=-6;dx<=4;dx+=5)ctx.fillRect(x+dx,y-1,3,2);}
  if(v.id===selected){ctx.font='11px "Segoe UI"';ctx.fillStyle='#eafaff';ctx.fillText(v.id,x+17,y-9);}
 }
 const personColors={walking:'#66e0cc',waiting:'#ffe178',bus:'#ffb454',metro:'#cfb5ff'};
 for(const person of state.people||[]){
  const point=displayPoint(person,true);if(!point)continue;let [x,y]=xy(point);const seed=[...person.id].reduce((a,c)=>a+c.charCodeAt(0),0),angle=seed*2.39996,offset=11+(seed%4)*3;x+=Math.cos(angle)*offset;y+=Math.sin(angle)*offset;
  if(!visible([x,y]))continue;ctx.beginPath();ctx.arc(x,y,person.count===20?3.3:2.7,0,Math.PI*2);ctx.fillStyle=personColors[person.mode]||personColors.walking;ctx.fill();ctx.strokeStyle='#122436';ctx.lineWidth=1.2;ctx.stroke();
  if(person.count!==20){ctx.font='10px "Segoe UI"';ctx.fillText(String(person.count),x+5,y-5);}
 }
}
function fit(){view={zoom:1,x:0,y:0};drawBase();drawLive();}
function setMode(value){mode=value;$('modelMode').classList.toggle('active',mode==='model');$('geoMode').classList.toggle('active',mode==='geo');$('mapCaption').textContent=mode==='geo'?'OSM 实景映射 · 车辆与信号位置为线路映射':'仿真路网 · 支持拖动、滚轮缩放与车辆定位';fit();}
$('modelMode').onclick=()=>setMode('model');$('geoMode').onclick=()=>setMode('geo');$('fitMap').onclick=fit;
function zoom(factor,x=width/2,y=height/2){const before=view.zoom;view.zoom=Math.max(.5,Math.min(20,view.zoom*factor));const ratio=view.zoom/before;view.x=x-width/2-(x-width/2-view.x)*ratio;view.y=y-height/2-(y-height/2-view.y)*ratio;drawBase();drawLive();}
$('zoomIn').onclick=()=>zoom(1.4);$('zoomOut').onclick=()=>zoom(1/1.4);live.onwheel=e=>{e.preventDefault();const r=live.getBoundingClientRect();zoom(e.deltaY<0?1.13:1/1.13,e.clientX-r.left,e.clientY-r.top);};
let drag=null;live.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,ox:view.x,oy:view.y};live.setPointerCapture(e.pointerId);};live.onpointermove=e=>{if(drag){view.x=drag.ox+e.clientX-drag.x;view.y=drag.oy+e.clientY-drag.y;drawBase();drawLive();}};live.onpointerup=e=>{if(drag&&Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<5&&state){const r=live.getBoundingClientRect(),{xy}=transform();const found=state.vehicles.find(v=>{const point=displayPoint(v);if(!point)return false;const p=xy(point);return Math.hypot(p[0]-e.clientX+r.left,p[1]-e.clientY+r.top)<12;});if(found){selected=found.id;renderVehicles();drawLive();}else{const signal=state.signals.find(s=>{const point=mode==='model'?s.position:maps.geo.signalPoints?.[s.id];if(!point)return false;const p=xy(point);return Math.hypot(p[0]-e.clientX+r.left,p[1]-e.clientY+r.top)<10;});if(signal){$('signal').value=signal.id;signalInfo();toast('已选择信号 '+signal.id);}}}drag=null;};live.onpointercancel=()=>drag=null;
$('locate').onclick=()=>{const v=state?.vehicles.find(v=>v.id===selected),point=v&&(mode==='geo'?v.geo:v.position);if(!point)return toast('此车辆暂无当前地图位置',true);view.zoom=Math.max(view.zoom,3);view.x=0;view.y=0;const p=transform().xy(point);view.x=width/2-p[0];view.y=height/2-p[1];drawBase();drawLive();};
window.addEventListener('online',()=>{pollStatus();if(!ws||ws.readyState===3)connect();});document.addEventListener('visibilitychange',()=>{if(!document.hidden){pollStatus();if(!ws||ws.readyState===3)connect();}});setInterval(()=>{if(csrf&&!stopped){if(eventTransport==='open'&&Date.now()-lastEventMessage>=12000){stopEvents();startEvents();}pollStatus();renewHttpLease();}},3000);setInterval(updateConnection,1000);api('/api/session').then(enter).catch(()=>{});

if($('copyConnectionReport'))$('copyConnectionReport').onclick=async()=>{try{await navigator.clipboard.writeText(JSON.stringify(connectionReport(),null,2));toast('诊断信息已复制，可用于反馈连接问题');}catch{toast('请展开连接诊断并手动复制',true);}};

window.addEventListener('pagehide',()=>{pageSuspended=true;stopEvents();clearTimeout(retryTimer);reconnectAt=0;clearInterval(heartbeat);retireConnection?.();});window.addEventListener('pageshow',()=>{if(pageSuspended){pageSuspended=false;if(csrf&&!stopped){pollStatus();connect();}}});

function renderAssessment(){
 const flow=state?.assessment?.passengers||state?.mobility||{},minutes=value=>Number.isFinite(value)?`${(value/60).toFixed(1)} 分钟`:'暂无完成行程';
 if($('completedPeople'))$('completedPeople').textContent=`${flow.people_arrived||0} / ${flow.people_total||0} 人`;
 if($('meanJourney'))$('meanJourney').textContent=minutes(flow.mean_journey_seconds);
 if($('meanWaiting'))$('meanWaiting').textContent=minutes(flow.mean_waiting_seconds);
 if($('longestWaiting'))$('longestWaiting').textContent=minutes(flow.longest_waiting_seconds??0);
 if($('exportAssessment'))$('exportAssessment').disabled=!state?.assessment||!online||Date.now()-lastUpdate>6000;
}
if($('exportAssessment'))$('exportAssessment').onclick=()=>{
 if(!state?.assessment||!online||Date.now()-lastUpdate>6000)return toast('请等待仿真端的新状态后再导出',true);
 const report={...state.assessment,downloaded_at:new Date().toISOString(),telemetry_age_ms:Math.max(0,Date.now()-lastUpdate)};
 const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),link=document.createElement('a');
 link.href=url;link.download=`厦门运行评估_${Math.floor(state.time)}秒.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('运行报告已导出');
};
