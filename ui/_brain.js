/* ===================== NEURAL BRAIN ===================== */
/* makeBrain(canvas,{onFrame}) -> {set(state), play(ms)}
   state = {who, stages:[{t,v}] x5, rules:[{ok}], options:[{ok,u}]}  */
function makeBrain(cv,opts={}){
 const LW=200,LH=104,off=document.createElement("canvas");off.width=LW;off.height=LH;const o=off.getContext("2d");
 const inside=(x,y)=>{const nx=(x-98)/86,ny=(y-46)/38;const main=nx*nx+ny*ny<1&&!(ny>.5&&nx>.05&&nx<.55);
  const cb=((x-136)/26)**2+((y-80)/12)**2<1;const stem=x>112&&x<124&&y>72&&y<100;return main||cb||stem};
 const stageOf=x=>Math.max(0,Math.min(4,Math.floor((x-12)/172*5)));
 let seed=11;const rnd=()=>(seed=(seed*16807)%2147483647)/2147483647;
 const nodes=[];let guard=0;
 while(nodes.length<58&&guard++<5000){const x=14+rnd()*170,y=10+rnd()*88;if(inside(x,y)&&nodes.every(n=>Math.hypot(n.x-x,n.y-y)>10.5))nodes.push({x:Math.round(x),y:Math.round(y),heat:0,stage:stageOf(x),col:null})}
 const edges=[];nodes.forEach((n,i)=>nodes.map((m,j)=>[j,Math.hypot(m.x-n.x,m.y-n.y)]).filter(([j])=>j!==i).sort((a,b)=>a[1]-b[1]).slice(0,3)
  .forEach(([j,d])=>{if(d<30&&!edges.some(e=>(e.a===j&&e.b===i)||(e.a===i&&e.b===j)))edges.push({a:i,b:j,glow:0})}));
 // static brain images: none active, and each stage active
 const statics=[-1,0,1,2,3,4].map(act=>{const c=document.createElement("canvas");c.width=LW;c.height=LH;const g=c.getContext("2d");
  for(let y=0;y<LH;y++)for(let x=0;x<LW;x++){if(!inside(x,y))continue;
   const edge=[[1,0],[-1,0],[0,1],[0,-1]].some(([dx,dy])=>!inside(x+dx,y+dy));
   const fold=Math.sin(x*.19+Math.sin(y*.16)*2.2)+Math.cos(y*.24+x*.03)>1.45;
   let col=edge?"#5aa0ff":fold?"#1c4597":"#0f2a66";
   if(!edge&&stageOf(x)===act)col=fold?"#2a63c9":"#173d8c";
   g.fillStyle=col;g.fillRect(x,y,1,1)}return c});
 let pulses=[],fired=0,state={stages:[],rules:[],options:[]},t0=0,dur=4200,playing=false,raf=0;
 function set(s){state=s;
  nodes.filter(n=>n.stage===1).forEach((n,i)=>n.col=s.rules&&s.rules.length?(s.rules[i%s.rules.length].ok?"#5fd068":"#ff5d5d"):null);
  nodes.filter(n=>n.stage===2).forEach((n,i)=>{const q=s.options&&s.options[i%(s.options.length||1)];n.col=q?(q.ok?(q.u>=70?"#5fd068":q.u>=50?"#ffd166":"#ff8f6b"):"#ff5d5d"):null})}
 function fire(i,chain){const n=nodes[i];n.heat=1;fired++;
  edges.forEach(e=>{if((e.a===i||e.b===i)&&Math.random()<(chain?.45:.8)){const to=e.a===i?e.b:e.a;e.glow=1;pulses.push({from:i,to,p:0,sp:.03+Math.random()*.035})}})}
 function play(ms){dur=ms;t0=performance.now();playing=true;fired=0;pulses=[];nodes.forEach(n=>n.heat=0);start()}
 function start(){cancelAnimationFrame(raf);const st=now=>{if(!cv.isConnected)return;draw(now);raf=requestAnimationFrame(st)};raf=requestAnimationFrame(st)}
 function draw(now){
  const prog=playing?Math.min(1,(now-t0)/dur):1;if(prog>=1)playing=false;
  const act=playing?Math.min(4,Math.floor(prog*5)):-1;
  if(playing){if(Math.random()<.45){const pool=nodes.map((n,i)=>[n,i]).filter(([n])=>n.stage===act);if(pool.length)fire(pool[Math.floor(Math.random()*pool.length)][1])}}
  else if(Math.random()<.05)fire(Math.floor(Math.random()*nodes.length));
  pulses.forEach(p=>{p.p+=p.sp;if(p.p>=1){p.done=true;const n=nodes[p.to];n.heat=1;if(Math.random()<.35&&(playing?Math.abs(n.stage-act)<=1:Math.random()<.3))fire(p.to,true)}});
  pulses=pulses.filter(p=>!p.done).slice(-160);
  o.clearRect(0,0,LW,LH);o.fillStyle="#06122e";o.fillRect(0,0,LW,LH);o.drawImage(statics[act+1],0,0);
  edges.forEach(e=>{const a=nodes[e.a],b=nodes[e.b],len=Math.max(1,Math.round(Math.hypot(b.x-a.x,b.y-a.y)));
   o.fillStyle=e.glow>.1?`rgba(143,233,255,${.35+e.glow*.65})`:"rgba(70,120,220,.55)";
   for(let k=0;k<=len;k+=1)o.fillRect(Math.round(a.x+(b.x-a.x)*k/len),Math.round(a.y+(b.y-a.y)*k/len),1,1);e.glow*=.92});
  pulses.forEach(p=>{const a=nodes[p.from],b=nodes[p.to];o.fillStyle="#ffffff";o.fillRect(Math.round(a.x+(b.x-a.x)*p.p)-1,Math.round(a.y+(b.y-a.y)*p.p)-1,2,2)});
  nodes.forEach(n=>{const lit=n.col&&(n.stage<act||act===-1&&!playing&&prog>=1||n.stage===act);
   if(n.heat>.05){o.fillStyle=`rgba(111,243,255,${n.heat*.5})`;o.fillRect(n.x-3,n.y-3,7,7)}
   o.fillStyle=lit?n.col:"#3b6fd6";o.fillRect(n.x-1,n.y-1,3,3);
   if(n.heat>.4){o.fillStyle="#fff";o.fillRect(n.x,n.y,1,1)}n.heat*=.93});
  // to screen
  const W=cv.clientWidth||700,H=cv.clientHeight||280,dpr=window.devicePixelRatio||1;
  if(cv.width!==Math.round(W*dpr)||cv.height!==Math.round(H*dpr)){cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr)}
  const c=cv.getContext("2d");c.setTransform(dpr,0,0,dpr,0,0);c.fillStyle="#06122e";c.fillRect(0,0,W,H);
  const s=Math.min((W-20)/LW,(H-70)/LH),bw=LW*s,bh=LH*s,bx=(W-bw)/2,by=34;
  c.imageSmoothingEnabled=false;c.drawImage(off,bx,by,bw,bh);
  c.save();c.globalCompositeOperation="lighter";c.globalAlpha=.35;c.filter="blur(7px)";c.drawImage(off,bx,by,bw,bh);c.restore();
  // HUD
  c.textAlign="left";c.font="700 13px 'Pixelify Sans',monospace";c.fillStyle="#6ff3ff";
  c.fillText(`${state.who?state.who+" · ":""}neurons fired ${fired}`,10,18);
  c.textAlign="right";c.fillStyle=playing?"#ffd447":"#8fb4ff";c.fillText(playing?`thinking: ${(state.stages[act]||{}).t||""}`:"idle",W-10,18);
  const segW=(W-20)/5;(state.stages||[]).forEach((st,i)=>{const x=10+i*segW,done=!playing||i<act,on=i===act;
   c.fillStyle=on?"#ffd447":done?"#3fae54":"#1a2a5c";c.fillRect(x+2,H-30,segW-4,8);
   c.textAlign="center";c.font="700 11px 'Pixelify Sans',monospace";c.fillStyle=on?"#ffd447":done?"#e6efff":"#5b6c9e";
   c.fillText(`${st.t}${done||on?": "+st.v:""}`,x+segW/2,H-9)});
  if(opts.onFrame)opts.onFrame(prog,playing);
 }
 start();
 return {set,play};
}
/* pixel loading spinner: 12 bars, no text */
function spinnerHTML(){return `<span class="spin" aria-hidden="true">${Array.from({length:12},(_,k)=>`<i style="transform:rotate(${k*30}deg);opacity:${((k+1)/12).toFixed(2)}"></i>`).join("")}</span>`}
