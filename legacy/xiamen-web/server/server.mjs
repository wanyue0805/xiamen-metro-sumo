import express from 'express';
import http from 'node:http';
import https from 'node:https';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {WebSocketServer,WebSocket} from 'ws';

const root=path.dirname(fileURLToPath(import.meta.url));
const cfg=JSON.parse(fs.readFileSync(process.env.SUMO_SERVER_CONFIG||path.join(root,'../config/server-local.json')));
const local=cfg.local===true;
const wsOrigin=cfg.origin.replace(/^http/, 'ws');
if(local&&!['127.0.0.1','::1'].includes(cfg.host))throw Error('Local mode requires loopback');
if(!local&&(!cfg.key||!cfg.cert||!cfg.origin.startsWith('https://')))throw Error('TLS configuration required');
const app=express();app.disable('x-powered-by');
const sessions=new Map(),attempts=new Map(),pending=new Map(),streams=new Set();
let device=null,latest=null,lastTelemetry=0,owner=null,ownerSeen=0,ownerTransport=null,revision=0;
const actions=new Set(['start','pause','resume','stop','rate','line_speed','headway','line_start','line_stop','vehicle_speed','signal_hold','signal_release','bus_start','bus_stop','demand','depot_enter','depot_release']);
const eq=(a,b)=>{if(typeof a!=='string'||typeof b!=='string')return false;const left=Buffer.from(a),right=Buffer.from(b);return left.length===right.length&&crypto.timingSafeEqual(left,right);};
const cookie=req=>{const c=(req.headers.cookie||'').split(';').map(x=>x.trim()).find(x=>x.startsWith('sumo_session='));return c?.slice(13)};
const session=req=>{const id=cookie(req),s=sessions.get(id);return s&&s.expires>Date.now()?{...s,id}:null};
const sameOrigin=req=>req.headers.origin===cfg.origin;
const online=()=>device?.readyState===WebSocket.OPEN&&Date.now()-lastTelemetry<(latest?.state?.status==='starting'?45000:5000);
const send=(ws,data)=>{if(ws.readyState===WebSocket.OPEN&&ws.bufferedAmount<512*1024)ws.send(JSON.stringify(data));};
const pauseController=()=>{if(device)send(device,{type:'control_lost'});owner=null;ownerSeen=0;ownerTransport=null;revision++;};
const renewOwner=(sid,mode)=>{if(owner!==sid||ownerTransport!==mode)return false;if(Date.now()-ownerSeen>=15000){pauseController();return false;}ownerSeen=Date.now();return true;};
const statusFor=s=>({type:'status',revision,online:!!online(),deviceConnected:device?.readyState===WebSocket.OPEN,telemetryAgeMs:lastTelemetry?Date.now()-lastTelemetry:null,control:owner&&Date.now()-ownerSeen<15000?(owner===s.id?'owned':'busy'):'available',controlTransport:owner===s.id?ownerTransport:null});
const streamSend=(client,data)=>{
 if(client.res.destroyed||client.res.writableEnded){streams.delete(client);return;}
 if(client.res.writableLength>512*1024){client.res.destroy();streams.delete(client);return;}
 client.res.write(`data: ${JSON.stringify(data)}\n\n`);
};
const browserCount=()=>[...wss.clients].filter(b=>b.role==='browser').length+streams.size;
// Do not log cookies, authorization headers, CSRF tokens, or query strings.
const connectionLog=(event,req,details={})=>console.log(JSON.stringify({event,path:req?.url?.split('?')[0],ray:String(req?.headers['cf-ray']||'').slice(0,80),...details}));
app.use((req,res,next)=>{res.set({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cache-Control':'no-store','Content-Security-Policy':`default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' ${wsOrigin}; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`});if(!local)res.set('Strict-Transport-Security','max-age=31536000');next();});
app.use(express.json({limit:'8kb',strict:true}));
// Apply the data boundary before static serving, including encoded path names.
app.use((req,res,next)=>{
 let pathname;
 try{pathname=decodeURIComponent(new URL(req.url,cfg.origin).pathname).replaceAll('\\','/').toLowerCase().replace(/[ .]+$/,'').split(':')[0];}
 catch{return res.status(400).json({error:'请求路径无效'});}
 if(pathname.endsWith('/maps.json.gz'))return res.sendStatus(404);
 if(pathname.endsWith('/maps.json')&&!session(req))return res.sendStatus(401);
 next();
});
app.get('/health',(_,res)=>res.json({ok:true,deviceOnline:online(),version:'0.1.0'}));
app.post('/api/login',(req,res)=>{
 if(!sameOrigin(req))return res.status(403).json({error:'来源校验失败'});
 const ip=req.socket.remoteAddress,rec=attempts.get(ip)||{n:0,until:Date.now()+600000};
 if(rec.until<Date.now()){rec.n=0;rec.until=Date.now()+600000;}
 attempts.set(ip,rec);if(++rec.n>10)return res.status(429).json({error:'尝试过多，请稍后重试'});
 const password=req.body?.password;if(typeof password!=='string'||password.length>256)return res.status(400).json({error:'登录信息无效'});
 crypto.scrypt(password,cfg.passwordSalt,64,(err,key)=>{
  if(err||!eq(req.body.username,cfg.username)||!eq(key.toString('hex'),cfg.passwordHash))return res.status(401).json({error:'用户名或密码不正确'});
  if(sessions.size>=32)return res.status(503).json({error:'会话已满'});
  const id=crypto.randomBytes(32).toString('hex'),csrf=crypto.randomBytes(24).toString('hex');sessions.set(id,{csrf,expires:Date.now()+8*3600000});rec.n=0;
  res.setHeader('Set-Cookie',`sumo_session=${id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800${local?'':'; Secure'}`);res.json({ok:true,csrf,username:cfg.username});
 });
});
app.get('/api/session',(req,res)=>{const s=session(req);if(!s)return res.status(401).json({error:'请登录'});res.json({csrf:s.csrf,username:cfg.username,leaseAgeMs:owner===s.id?Date.now()-ownerSeen:null,ownBrowserConnections:[...wss.clients].filter(b=>b.role==='browser'&&b.sid===s.id).map(b=>({alive:b.alive,lastPingAgeMs:Date.now()-b.lastPing,lastPongAgeMs:Date.now()-b.lastPong,lastMessageAgeMs:Date.now()-b.lastMessage}))});});
app.get('/api/status',(req,res)=>{const s=session(req);if(!s)return res.status(401).json({error:'请登录',code:'AUTH_REQUIRED'});res.json({...statusFor(s),...(req.query.summary==='1'?{}:{state:online()?latest?.state:null})});});
app.get('/api/events',(req,res)=>{
 const s=session(req);if(!s)return res.status(401).json({error:'请登录',code:'AUTH_REQUIRED'});
 if(req.headers.origin&&!sameOrigin(req)||req.headers['sec-fetch-site']==='cross-site')return res.status(403).json({error:'来源校验失败'});
 if(browserCount()>=20)return res.status(429).json({error:'连接已满',code:'BROWSER_LIMIT'});
 res.set({'Content-Type':'text/event-stream; charset=utf-8','Cache-Control':'no-store, no-transform','X-Accel-Buffering':'no'});res.flushHeaders();
 const client={sid:s.id,res};streams.add(client);res.write(': connected\n\n');
 connectionLog('event_stream_connected',req);streamSend(client,statusFor(s));if(online()&&latest)streamSend(client,latest);
 const remove=()=>streams.delete(client);req.on('close',remove);res.on('error',remove);
});
app.post('/api/heartbeat',(req,res)=>{
 const s=session(req);if(!s)return res.status(401).json({error:'请登录'});
 if(!sameOrigin(req)||!eq(req.headers['x-csrf-token'],s.csrf))return res.status(403).json({error:'来源或会话校验失败'});
 // Presence renews an existing lease even while SUMO is loading and telemetry is stale.
 // Commands still require online() and cannot bypass the telemetry freshness check.
 if(device?.readyState!==WebSocket.OPEN)return res.status(503).json({error:'Windows 仿真端离线'});
 if(!renewOwner(s.id,'http'))return res.status(409).json({error:'控制权已释放，请重新操作'});
 res.json({ok:true});
});
app.post('/api/logout',(req,res)=>{const s=session(req);if(!s||!sameOrigin(req)||!eq(req.headers['x-csrf-token'],s.csrf))return res.sendStatus(403);sessions.delete(s.id);if(owner===s.id)pauseController();for(const client of streams)if(client.sid===s.id){streams.delete(client);client.res.end();}res.setHeader('Set-Cookie','sumo_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0');res.json({ok:true});});
app.post('/api/command',(req,res)=>{
 const s=session(req);if(!s)return res.status(401).json({error:'请登录'});
 if(!sameOrigin(req)||!eq(req.headers['x-csrf-token'],s.csrf))return res.status(403).json({error:'来源或会话校验失败'});
 if(!online())return res.status(503).json({error:'Windows 仿真端离线'});
 if(owner&&Date.now()-ownerSeen>=15000)pauseController();
 const {action,args={},generation}=req.body||{};if(!actions.has(action)||typeof args!=='object'||Array.isArray(args)||args===null)return res.status(400).json({error:'不支持的指令'});
 if(owner&&owner!==s.id&&Date.now()-ownerSeen<15000)return res.status(409).json({error:'另一个网页会话正在控制'});
 if(pending.size>=16)return res.status(429).json({error:'指令队列繁忙'});
 const previous=sessions.get(s.id);if(Date.now()-(previous.lastCommand||0)<100)return res.status(429).json({error:'操作过快'});previous.lastCommand=Date.now();
 owner=s.id;ownerSeen=Date.now();ownerTransport=req.body.transport==='http'?'http':'websocket';revision++;const id=crypto.randomUUID(),expires=Date.now()+8000;
 const timer=setTimeout(()=>{pending.delete(id);if(!res.writableEnded)res.status(504).json({error:'未收到执行回执，请查看当前状态',id});},action==='start'||action==='line_start'?45000:10000);
 pending.set(id,{res,timer});send(device,{type:'command',id,action,args,generation,expires});
});
app.get('/maps.json',(req,res,next)=>{if(!session(req))return res.sendStatus(401);if((req.headers['accept-encoding']||'').includes('gzip'))return res.set({'Content-Type':'application/json','Content-Encoding':'gzip','Vary':'Accept-Encoding'}).sendFile(path.join(root,'public/maps.json.gz'));next();});
app.use('/maps.json.gz',(req,res)=>res.sendStatus(404));
app.use(express.static(path.join(root,'public'),{etag:true,maxAge:0}));
app.use((err,req,res,next)=>{if(!res.headersSent)res.status(400).json({error:'请求格式无效'});});
const server=local?http.createServer(app):https.createServer({key:fs.readFileSync(cfg.key),cert:fs.readFileSync(cfg.cert),minVersion:'TLSv1.2'},app);
const wss=new WebSocketServer({noServer:true,maxPayload:256*1024,perMessageDeflate:false});
server.on('upgrade',(req,socket,head)=>{
 const url=new URL(req.url,cfg.origin);
 if(url.pathname==='/ws/device'){
  if(!eq(req.headers.authorization,`Bearer ${cfg.deviceToken}`)||device?.readyState===WebSocket.OPEN){socket.write('HTTP/1.1 403 Forbidden\r\n\r\n');return socket.destroy();}
  wss.handleUpgrade(req,socket,head,ws=>{ws.role='device';device=ws;lastTelemetry=0;latest=null;revision++;attach(ws);});
 }else if(url.pathname==='/ws/browser'){
  const s=session(req);const failure=!s?[401,'Unauthorized','AUTH_REQUIRED']:!sameOrigin(req)?[403,'Forbidden','ORIGIN_REJECTED']:browserCount()>=20?[429,'Too Many Requests','BROWSER_LIMIT']:null;
  if(failure){const [code,reason,error]=failure;connectionLog('browser_rejected',req,{status:code,reason:error});const body=JSON.stringify({error});socket.end(`HTTP/1.1 ${code} ${reason}\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`);return;}
  wss.handleUpgrade(req,socket,head,ws=>{ws.role='browser';ws.sid=s.id;connectionLog('browser_connected',req);ws.on('close',code=>connectionLog('browser_closed',req,{code}));attach(ws);send(ws,statusFor(s));if(online()&&latest)send(ws,latest);});
 }else socket.destroy();
});
function attach(ws){
 ws.alive=true;ws.lastPong=Date.now();ws.lastMessage=Date.now();ws.on('pong',()=>{ws.alive=true;ws.lastPong=Date.now();if(ws.role==='browser'&&sessions.get(ws.sid)?.expires>Date.now())renewOwner(ws.sid,'websocket');});
 ws.on('message',raw=>{ws.lastMessage=Date.now();let msg;try{msg=JSON.parse(raw.toString());}catch{return ws.close(1008,'Invalid JSON');}
  if(ws.role==='device'){
   if(msg.type==='telemetry'&&msg.state&&typeof msg.state==='object'){
    // Resending a frozen snapshot keeps TCP alive, but is not new simulation data.
    if(msg.sequence!==undefined&&latest?.sequence===msg.sequence)return;
    latest={...msg,revision:++revision};lastTelemetry=Date.now();for(const b of wss.clients)if(b.role==='browser'&&sessions.has(b.sid))send(b,latest);
    for(const client of streams)if(sessions.get(client.sid)?.expires>Date.now())streamSend(client,latest);
   }else if(msg.type==='result'&&typeof msg.id==='string'){
    const p=pending.get(msg.id);if(p){clearTimeout(p.timer);pending.delete(msg.id);p.res.status(msg.ok?200:400).json(msg);}
   }
  }else if(msg.type==='heartbeat'&&sessions.get(ws.sid)?.expires>Date.now()){renewOwner(ws.sid,'websocket');send(ws,{type:'heartbeat'});}
 });
 ws.on('error',()=>{});ws.on('close',()=>{
  if(ws===device){device=null;lastTelemetry=0;revision++;for(const p of pending.values()){clearTimeout(p.timer);p.res.status(503).json({error:'Windows 连接断开'});}pending.clear();for(const b of wss.clients)if(b.role==='browser')send(b,statusFor({id:b.sid}));for(const client of streams)streamSend(client,statusFor({id:client.sid}));}
  if(ws.role==='browser'&&owner===ws.sid&&ownerTransport!=='http'&&![...wss.clients].some(b=>b!==ws&&b.role==='browser'&&b.sid===ws.sid))pauseController();
 });
}
setInterval(()=>{
 const now=Date.now();for(const [id,s]of sessions)if(s.expires<now){sessions.delete(id);for(const b of wss.clients)if(b.sid===id)b.close(1008,'Session expired');if(owner===id)pauseController();}
 for(const [ip,r]of attempts)if(r.until<now)attempts.delete(ip);
 if(owner&&now-ownerSeen>15000)pauseController();
 for(const client of streams){if(!(sessions.get(client.sid)?.expires>now)){streams.delete(client);client.res.end();}else streamSend(client,statusFor({id:client.sid}));}
 for(const ws of wss.clients){if(!ws.alive){if(now-ws.lastPing>(ws.role==='device'?45000:10000))ws.terminate();continue;}ws.alive=false;ws.lastPing=now;ws.ping();if(ws.role==='browser')send(ws,statusFor({id:ws.sid}));}
},5000).unref();
setInterval(()=>{if(owner&&Date.now()-ownerSeen>=15000)pauseController();},1000).unref();
server.requestTimeout=15000;server.headersTimeout=10000;
server.listen(cfg.port,cfg.host,()=>console.log(`SUMO relay ready ${cfg.origin}`));
process.on('SIGTERM',()=>{pauseController();for(const ws of wss.clients)ws.close(1001);for(const client of streams)client.res.end();streams.clear();server.close(()=>process.exit(0));setTimeout(()=>process.exit(0),3000).unref();});
