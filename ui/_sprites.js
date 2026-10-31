const OUT="#1b1f3b";
function spriteGrid(kind,opt={}){
 const W=20,H=27,g=Array.from({length:H},()=>Array(W).fill(null));
 const f=(x,y,w,h,c)=>{for(let j=y;j<y+h;j++)for(let i=x;i<x+w;i++)if(j>=0&&j<H&&i>=0&&i<W)g[j][i]=c};
 const P={atc:{skin:"#e8b58a",shirt:"#2b4c8c",pants:"#1f2a44",shoe:"#111827"},
  pilot:{skin:"#f6cfa8",shirt:"#f8fafc",pants:"#1e3a8a",shoe:"#111827"},
  ground:{skin:"#c68a5c",shirt:"#4b5563",pants:"#334155",shoe:"#7c4a1e"},
  mod:{skin:"#f2c9a6",shirt:"#efe6d2",pants:"#1f2937",shoe:"#f8fafc"},
  custom:{skin:"#f0c08f",shirt:opt.color||"#14b8a6",pants:"#374151",shoe:"#111827"}}[kind];
 // head: rounded, with a chin
 f(4,5,12,10,P.skin);f(5,15,10,1,P.skin);
 // neck, shoulders, torso, arms
 f(8,16,4,1,"#d9a27a");
 f(6,17,8,1,P.shirt);f(7,18,6,4,P.shirt);f(5,18,2,4,P.shirt);f(13,18,2,4,P.shirt);f(5,22,2,1,P.skin);f(13,22,2,1,P.skin);
 f(7,22,2,3,P.pants);f(11,22,2,3,P.pants);f(6,25,3,1,P.shoe);f(11,25,3,1,P.shoe);
 // face
 const blink=opt.blink;
 if(blink){f(6,10,3,1,OUT);f(11,10,3,1,OUT)}else{f(6,9,3,3,"#fff");f(11,9,3,3,"#fff");f(8,10,1,2,OUT);f(13,10,1,2,OUT)}
 f(9,13,2,1,"#8a3b2e");f(5,13,1,1,"#f29b9b");f(14,13,1,1,"#f29b9b");
 if(kind==="atc"){f(4,4,12,3,"#5a3a22");f(4,7,1,5,"#5a3a22");f(15,7,1,5,"#5a3a22");f(3,7,1,8,"#5a3a22");f(16,7,1,8,"#5a3a22");
  f(5,3,10,1,"#6b7280");f(4,4,1,1,"#6b7280");f(15,4,1,1,"#6b7280");f(2,9,2,4,"#374151");f(16,9,2,4,"#374151");f(3,13,1,2,"#374151");f(4,14,4,1,"#374151");f(8,14,1,1,"#ef4444");
  f(8,19,2,2,"#ffd447")}
 if(kind==="pilot"){f(4,1,12,4,"#1e3a8a");f(5,0,10,1,"#1e3a8a");f(4,5,12,1,"#f8fafc");f(3,6,14,1,"#111827");f(9,2,2,2,"#ffd447");
  f(4,7,1,3,"#3b2a1a");f(15,7,1,3,"#3b2a1a");f(9,17,2,5,"#1e3a8a");f(6,17,2,1,"#ffd447");f(12,17,2,1,"#ffd447");f(5,21,2,1,"#ffd447");f(13,21,2,1,"#ffd447")}
 if(kind==="ground"){f(5,1,10,5,"#ffc83d");f(6,0,8,1,"#ffc83d");f(9,1,2,5,"#ffe083");f(3,6,14,1,"#e0a800");f(4,7,1,2,"#7a4a24");f(15,7,1,2,"#7a4a24");
  f(6,17,8,1,"#ff7a1a");f(7,18,2,4,"#ff7a1a");f(11,18,2,4,"#ff7a1a");f(7,20,6,1,"#e5e7eb");f(5,18,2,2,"#ff7a1a");f(13,18,2,2,"#ff7a1a");
  f(4,15,1,7,"#ff4d1a");f(4,14,1,1,"#ffe08a");f(15,15,1,7,"#ff4d1a");f(15,14,1,1,"#ffe08a")}
 if(kind==="mod"){const hr="#2a1c2e";f(5,2,10,1,hr);f(4,3,12,3,hr);f(4,6,5,2,hr);f(11,6,5,2,hr);f(6,8,2,1,hr);f(12,8,2,1,hr);
  f(3,5,1,8,hr);f(16,5,1,8,hr);f(4,8,1,4,hr);f(15,8,1,4,hr);f(7,3,3,1,"#4a3352");
  f(16,13,1,1,"#e5e7eb");f(16,14,1,1,"#cbd5e1");
  f(8,17,4,1,"#111827");f(9,18,2,4,"#111827");f(8,18,1,3,"#d6c9ad");f(11,18,1,3,"#d6c9ad");
  f(15,16,2,2,"#6b7280");f(15,16,1,1,"#e5e7eb");f(15,18,1,4,"#374151")}
 if(kind==="custom"){f(4,2,12,4,opt.color||"#14b8a6");f(3,5,14,1,"#1b1f3b");f(4,6,1,3,"#2d1d10");f(15,6,1,3,"#2d1d10");f(8,19,4,2,"#ffffff")}
 // auto outline
 const o=g.map(r=>r.slice());
 for(let y=0;y<H;y++)for(let x=0;x<W;x++)if(!g[y][x]&&[[1,0],[-1,0],[0,1],[0,-1]].some(([dx,dy])=>g[y+dy]&&g[y+dy][x+dx]&&g[y+dy][x+dx]!==OUT))o[y][x]=OUT;
 return o;
}
function drawSprite(cv,kind,opt={}){
 const g=spriteGrid(kind,opt),s=2;cv.width=20*s;cv.height=27*s;const c=cv.getContext("2d");c.clearRect(0,0,cv.width,cv.height);
 g.forEach((r,y)=>r.forEach((col,x)=>{if(col){c.fillStyle=col;c.fillRect(x*s,y*s,s,s)}}));
}
function newSprite(kind,opt){const cv=document.createElement("canvas");cv.className="px";drawSprite(cv,kind,opt);cv.setAttribute("aria-hidden","true");return cv}
const kindOf=a=>a.custom?"custom":a.id;
const blinkers=[];
function blinkable(cv,kind,opt={}){blinkers.push({cv,kind,opt});return cv}
setInterval(()=>{const b=blinkers.filter(x=>x.cv.isConnected);if(!b.length)return;const t=b[Math.floor(Math.random()*b.length)];drawSprite(t.cv,t.kind,{...t.opt,blink:true});setTimeout(()=>drawSprite(t.cv,t.kind,t.opt),140)},900);

