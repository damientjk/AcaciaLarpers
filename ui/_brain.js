/* ===================== NEURAL BRAIN ===================== */
/* makeBrain(canvas,{onFrame}) -> {set(state), play(ms)}
   state = {who, stages:[{t,v}] x5, rules:[{ok}], options:[{ok,u}]}
   Smooth neon side view: cerebrum with gyri, temporal lobe, striated cerebellum, brain stem. */
function makeBrain(cv,opts={}){
 const UW=200,UH=150,SS=4;                       // unit space and supersample for the static art
 // ---- shapes (units; the brain faces left) ----
 const cerebrum=new Path2D("M34,88 C14,78 6,48 28,28 C50,8 92,0 130,5 C168,10 194,34 196,66 C198,88 186,102 170,106 C160,108 150,108 142,108 C130,120 106,124 88,118 C72,113 60,106 56,96 C54,90 60,86 68,88 C58,90 46,92 34,88 Z");
 const stem=new Path2D("M112,104 C112,122 116,138 122,150 L138,150 C134,134 134,118 138,104 Z");
 const cereb=new Path2D(); cereb.ellipse(160,120,27,14,-0.12,0,Math.PI*2);
 const stageOf=x=>Math.max(0,Math.min(4,Math.floor((x-8)/184*5)));
 const mk=(w,h)=>{const c=document.createElement("canvas");c.width=w;c.height=h;return c};
 // ---- mask of the cerebrum for fold and node placement ----
 const mw=UW*2,mh=UH*2,mc=mk(mw,mh),mx=mc.getContext("2d");mx.scale(2,2);mx.fillStyle="#fff";mx.fill(cerebrum);
 const md=mx.getImageData(0,0,mw,mh).data;
 const inside=(x,y)=>x>=0&&y>=0&&x<UW&&y<UH&&md[((Math.floor(y*2))*mw+Math.floor(x*2))*4+3]>128;
 const fold=(x,y)=>Math.abs(Math.sin(0.52*y+3.4*Math.sin(0.072*x+0.7*Math.sin(0.13*y))+1.7*Math.sin(0.12*x-0.05*y+1.0)));
 // ---- static art, drawn once ----
 function art(bright){
  const c=mk(UW*SS,UH*SS),g=c.getContext("2d");g.scale(SS,SS);g.lineJoin="round";g.lineCap="round";
  const glow=(col,b)=>{g.shadowColor=col;g.shadowBlur=b};
  if(!bright){
   // stem and cerebellum first so the cerebrum overlaps them
   const gs=g.createLinearGradient(0,104,0,150);gs.addColorStop(0,"#16419a");gs.addColorStop(1,"#0a2157");
   g.fillStyle=gs;g.fill(stem);g.strokeStyle="#7fd0ff";g.lineWidth=1.4;g.shadowColor="#46c3ff";g.shadowBlur=8;g.stroke(stem);g.shadowBlur=0;
   const gc=g.createRadialGradient(158,116,2,160,120,30);gc.addColorStop(0,"#2a62c8");gc.addColorStop(1,"#0d2a68");
   g.fillStyle=gc;g.fill(cereb);g.strokeStyle="#9fe4ff";g.lineWidth=1.4;g.shadowColor="#46c3ff";g.shadowBlur=8;g.stroke(cereb);g.shadowBlur=0;
   g.save();g.clip(cereb);g.strokeStyle="rgba(150,215,255,.55)";g.lineWidth=.7;
   for(let k=-12;k<=14;k+=2.6){g.beginPath();g.moveTo(130,120+k);g.quadraticCurveTo(160,126+k*1.15,190,114+k);g.stroke()}g.restore();
   // cerebrum body
   const gb=g.createRadialGradient(96,40,6,100,62,110);gb.addColorStop(0,"#3b7bf0");gb.addColorStop(.55,"#1c4cb3");gb.addColorStop(1,"#0b2562");
   g.fillStyle=gb;g.fill(cerebrum);
   // soft top light
   g.save();g.clip(cerebrum);const gl=g.createLinearGradient(0,0,0,70);gl.addColorStop(0,"rgba(150,220,255,.35)");gl.addColorStop(1,"rgba(150,220,255,0)");g.fillStyle=gl;g.fillRect(0,0,UW,70);g.restore();
  }
  // gyri: bright worm lines where the fold field is near zero
  const fc=mk(UW*2,UH*2),fx=fc.getContext("2d"),img=fx.createImageData(UW*2,UH*2);
  for(let y=0;y<UH*2;y++)for(let x=0;x<UW*2;x++){const ux=x/2,uy=y/2;if(!inside(ux,uy))continue;
   const f=fold(ux,uy),i=(y*UW*2+x)*4;
   if(f<0.21){const a=Math.min(1,(1-f/0.21)*1.25);img.data[i]=bright?200:130;img.data[i+1]=bright?245:205;img.data[i+2]=255;img.data[i+3]=Math.round(a*(bright?255:215))}}
  fx.putImageData(img,0,0);
  g.save();g.clip(cerebrum);g.imageSmoothingEnabled=true;g.drawImage(fc,0,0,UW,UH);g.restore();
  // landmarks: lateral (Sylvian) fissure, central sulcus, parieto-occipital sulcus
  g.save();g.clip(cerebrum);g.strokeStyle=bright?"#e6fbff":"rgba(170,225,255,.9)";g.lineWidth=bright?1.7:1.4;glow("#58c8ff",bright?8:5);
  g.beginPath();g.moveTo(70,90);g.bezierCurveTo(88,78,112,76,142,62);g.stroke();
  g.lineWidth=1.1;g.beginPath();g.moveTo(112,8);g.bezierCurveTo(100,28,104,44,96,66);g.stroke();
  g.beginPath();g.moveTo(166,18);g.bezierCurveTo(158,34,160,46,152,62);g.stroke();g.restore();
  // neon outline
  if(!bright){g.strokeStyle="#9fe4ff";g.lineWidth=1.5;glow("#46c3ff",9);g.stroke(cerebrum);g.shadowBlur=0}
  return c;
 }
 const base=art(false),brightArt=art(true);
 // ---- neurons live in the folds, then connect to near neighbours ----
 let seed=7;const rnd=()=>(seed=(seed*16807)%2147483647)/2147483647;
 const nodes=[];let guard=0;
 while(nodes.length<96&&guard++<60000){const x=6+rnd()*190,y=4+rnd()*110;
  if(inside(x,y)&&fold(x,y)<0.12&&nodes.every(n=>Math.hypot(n.x-x,n.y-y)>9))nodes.push({x,y,heat:0,stage:stageOf(x),col:null})}
 for(let k=0;k<12;k++){const a=rnd()*6.28,r=rnd();nodes.push({x:160+Math.cos(a)*r*22,y:120+Math.sin(a)*r*10,heat:0,stage:stageOf(160),col:null,cb:true})} // cerebellum
 const edges=[];
 nodes.forEach((n,i)=>nodes.map((m,j)=>[j,Math.hypot(m.x-n.x,m.y-n.y)]).filter(([j])=>j!==i).sort((a,b)=>a[1]-b[1]).slice(0,3)
  .forEach(([j,d])=>{if(d<26&&!edges.some(e=>(e.a===j&&e.b===i)||(e.a===i&&e.b===j))){const m=nodes[j],nx=-(m.y-n.y)/d,ny=(m.x-n.x)/d,bow=(rnd()-.5)*d*.35;
   edges.push({a:i,b:j,cx:(n.x+m.x)/2+nx*bow,cy:(n.y+m.y)/2+ny*bow,glow:0})}}));
 const qpt=(e,t)=>{const a=nodes[e.a],b=nodes[e.b],u=1-t;return[u*u*a.x+2*u*t*e.cx+t*t*b.x,u*u*a.y+2*u*t*e.cy+t*t*b.y]};
 let pulses=[],fired=0,state={stages:[],rules:[],options:[]},t0=0,dur=4200,playing=false,raf=0;
 function set(s){state=s;
  const st1=nodes.filter(n=>n.stage===1&&!n.cb),st2=nodes.filter(n=>n.stage===2&&!n.cb);
  st1.forEach((n,i)=>n.col=s.rules&&s.rules.length?(s.rules[i%s.rules.length].ok?"#5fe07a":"#ff5d6c"):null);
  st2.forEach((n,i)=>{const q=s.options&&s.options.length?s.options[i%s.options.length]:null;n.col=q?(q.ok?(q.u>=70?"#5fe07a":q.u>=50?"#ffd447":"#ff9a5c"):"#ff5d6c"):null})}
 function fire(i,chain){const n=nodes[i];n.heat=1;fired++;
  edges.forEach(e=>{if((e.a===i||e.b===i)&&Math.random()<(chain?.45:.85)){const to=e.a===i?e.b:e.a;e.glow=1;pulses.push({e,from:i,to,p:0,fwd:e.a===i,sp:.022+Math.random()*.03})}})}
 function play(ms){dur=ms;t0=performance.now();playing=true;fired=0;pulses=[];nodes.forEach(n=>n.heat=0);start()}
 function start(){cancelAnimationFrame(raf);const st=now=>{if(!cv.isConnected)return;draw(now);raf=requestAnimationFrame(st)};raf=requestAnimationFrame(st)}
 function draw(now){
  const prog=playing?Math.min(1,(now-t0)/dur):1;if(prog>=1)playing=false;
  const act=playing?Math.min(4,Math.floor(prog*5)):-1;
  if(playing){if(Math.random()<.5){const pool=nodes.map((n,i)=>[n,i]).filter(([n])=>n.stage===act);if(pool.length)fire(pool[Math.floor(Math.random()*pool.length)][1])}}
  else if(Math.random()<.05)fire(Math.floor(Math.random()*nodes.length));
  pulses.forEach(p=>{p.p+=p.sp;if(p.p>=1){p.done=true;const n=nodes[p.to];n.heat=1;if(Math.random()<.35&&(playing?Math.abs(n.stage-act)<=1:Math.random()<.3))fire(p.to,true)}});
  pulses=pulses.filter(p=>!p.done).slice(-200);
  const W=cv.clientWidth||700,H=cv.clientHeight||380,dpr=window.devicePixelRatio||1;
  if(cv.width!==Math.round(W*dpr)||cv.height!==Math.round(H*dpr)){cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr)}
  const c=cv.getContext("2d");c.setTransform(dpr,0,0,dpr,0,0);
  const bg=c.createRadialGradient(W/2,H*.45,10,W/2,H*.45,Math.max(W,H)*.7);bg.addColorStop(0,"#0b2150");bg.addColorStop(1,"#040b22");c.fillStyle=bg;c.fillRect(0,0,W,H);
  const s=Math.min((W-24)/UW,(H-96)/UH),bw=UW*s,bh=UH*s,bx=(W-bw)/2,by=30+((H-96)-bh)/2,X=x=>bx+x*s,Y=y=>by+y*s;
  c.imageSmoothingEnabled=true;c.imageSmoothingQuality="high";c.drawImage(base,bx,by,bw,bh);
  if(act>=0){const x0=X(8+184*act/5),x1=X(8+184*(act+1)/5);c.save();c.beginPath();c.rect(x0,by,x1-x0,bh);c.clip();c.translate(bx,by);c.scale(s,s);c.clip(cerebrum);c.scale(1/s,1/s);c.translate(-bx,-by);
   c.globalAlpha=.9;c.drawImage(brightArt,bx,by,bw,bh);
   const gh=c.createLinearGradient(x0,0,x1,0);gh.addColorStop(0,"rgba(255,212,71,0)");gh.addColorStop(.5,"rgba(255,212,71,.16)");gh.addColorStop(1,"rgba(255,212,71,0)");c.globalAlpha=1;c.fillStyle=gh;c.fillRect(x0,by,x1-x0,bh);c.restore()}
  // connections
  c.lineCap="round";edges.forEach(e=>{const a=nodes[e.a],b=nodes[e.b];c.beginPath();c.moveTo(X(a.x),Y(a.y));c.quadraticCurveTo(X(e.cx),Y(e.cy),X(b.x),Y(b.y));
   c.strokeStyle=e.glow>.08?`rgba(140,240,255,${.3+e.glow*.7})`:"rgba(120,190,255,.28)";c.lineWidth=e.glow>.08?1.6:.9;c.stroke();e.glow*=.93});
  // pulses
  c.save();c.shadowColor="#bff6ff";c.shadowBlur=8;c.fillStyle="#fff";pulses.forEach(p=>{const [px,py]=qpt(p.e,p.fwd?p.p:1-p.p);c.beginPath();c.arc(X(px),Y(py),1.9,0,6.283);c.fill()});c.restore();
  // neurons
  nodes.forEach(n=>{const lit=n.col&&(act===-1||n.stage<=act);const r=2.4+n.heat*2;
   c.save();c.shadowColor=lit?n.col:"#6fd3ff";c.shadowBlur=3+n.heat*16;c.fillStyle=lit?n.col:(n.heat>.3?"#eaffff":"#9fdcff");
   c.beginPath();c.arc(X(n.x),Y(n.y),r,0,6.283);c.fill();c.restore();n.heat*=.93});
  // HUD
  c.textAlign="left";c.font="700 13px 'Pixelify Sans',monospace";c.fillStyle="#6ff3ff";
  c.fillText(`${state.who?state.who+" · ":""}neurons fired ${fired}`,12,20);
  c.textAlign="right";c.fillStyle=playing?"#ffd447":"#8fb4ff";c.fillText(playing?`thinking: ${(state.stages[act]||{}).t||""}`:"idle",W-12,20);
  const segW=(W-24)/5;(state.stages||[]).forEach((st,i)=>{const x=12+i*segW,done=!playing||i<act,on=i===act;
   c.fillStyle=on?"#ffd447":done?"#3fae54":"#1a2a5c";c.fillRect(x+3,H-52,segW-6,8);
   c.textAlign="center";c.font="700 12px 'Pixelify Sans',monospace";c.fillStyle=on?"#ffd447":done?"#e6efff":"#5b6c9e";
   c.fillText(st.t,x+segW/2,H-30);
   c.font="600 11px Poppins,sans-serif";c.fillStyle=on?"#ffe58a":done?"#9fc4ff":"#3d4c7a";
   c.fillText(done||on?String(st.v):"…",x+segW/2,H-13)});
  if(opts.onFrame)opts.onFrame(prog,playing);
 }
 start();
 return {set,play};
}
/* pixel loading spinner: 12 bars, no text */
function spinnerHTML(){return `<span class="spin" aria-hidden="true">${Array.from({length:12},(_,k)=>`<i style="transform:rotate(${k*30}deg);opacity:${((k+1)/12).toFixed(2)}"></i>`).join("")}</span>`}
