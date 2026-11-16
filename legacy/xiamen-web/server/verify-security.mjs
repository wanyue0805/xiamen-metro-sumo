import fs from 'node:fs';import path from 'node:path';import {spawn} from 'node:child_process';import {fileURLToPath} from 'node:url';import {WebSocket} from 'ws';
const root=path.dirname(fileURLToPath(import.meta.url));const cfg=JSON.parse(fs.readFileSync(path.join(root,'../config/server-local.json')));cfg.port=3181;cfg.origin='http://127.0.0.1:3181';const config=path.join(root,'../config/server-test.json');fs.writeFileSync(config,JSON.stringify(cfg));
const child=spawn(process.execPath,[path.join(root,'server.mjs')],{env:{...process.env,SUMO_SERVER_CONFIG:config},stdio:'ignore'});const checks=[];
const check=(name,pass)=>{checks.push({name,pass});if(!pass)throw Error(name);};
try{
 for(let i=0;i<40;i++){try{await fetch(cfg.origin+'/health');break;}catch{await new Promise(r=>setTimeout(r,100));}}
 let r=await fetch(cfg.origin+'/api/login',{method:'POST',headers:{'Content-Type':'application/json','Origin':cfg.origin},body:JSON.stringify({username:'测试测试测',password:'wrong'})});check('Unicode username rejected without process crash',r.status===401);
 r=await fetch(cfg.origin+'/health');check('Relay survives malformed authentication',r.status===200);
 r=await fetch(cfg.origin+'/maps.json');check('Map requires login',r.status===401);
 r=await fetch(cfg.origin+'/%6daps.json');check('Encoded map path requires login',r.status===401);
 r=await fetch(cfg.origin+'/maps.json.gz');check('Compressed map cannot bypass login',r.status===404);
 r=await fetch(cfg.origin+'/api/login',{method:'POST',headers:{'Content-Type':'application/json','Origin':'http://untrusted.invalid'},body:'{}'});check('Foreign login origin rejected',r.status===403);
 r=await fetch(cfg.origin+'/api/command',{method:'POST',headers:{'Content-Type':'application/json','Origin':cfg.origin},body:'{}'});check('Anonymous commands rejected',r.status===401);
 const rejected=await new Promise(resolve=>{const ws=new WebSocket(cfg.origin.replace('http:','ws:')+'/ws/device',{headers:{Authorization:'Bearer wrong'}});ws.on('unexpected-response',(_,response)=>{response.resume();resolve(response.statusCode===403);});ws.on('open',()=>{ws.close();resolve(false);});ws.on('error',()=>resolve(false));setTimeout(()=>{ws.terminate();resolve(false);},3000).unref();});check('Unauthenticated device connection rejected',rejected);
 console.log(JSON.stringify(checks));
}finally{child.kill();fs.unlinkSync(config);}
