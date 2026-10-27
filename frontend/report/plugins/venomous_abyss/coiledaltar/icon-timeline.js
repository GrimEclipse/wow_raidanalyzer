/* Coiled Altar icon timeline: the report and focus dialog share one instance. */
((global)=>{
  const finite=value=>Number.isFinite(Number(value))?Number(value):0;
  function comparison(pull){
    const g=pull.coiledaltar?.guildTimeline, evidence=g?.bossComparison;
    if(!evidence)return null;
    return {id:pull.fightID,duration:Math.max(1,finite(pull.durationMs||g.durationMs)/1000),
      phases:(evidence.phaseTimeline||[]).map(p=>[p.key,finite(p.timeMs)/1000]),
      boss:(evidence.events||[]).map(e=>[e.key,finite(e.timeMs)/1000,finite(e.endTimeMs)/1000,e.phase,e.sourceType])};
  }
  function makeModel(guild,pull,pulls,scope='dps',assets=global.CoiledAltarTimelineAssets){
    if(!assets||!guild.displayTimelines||!guild.bossComparison)return null;
    const current=comparison(pull),skills={},images={...assets.icons,boss:'/assets/raids/venomous_abyss/07-coiledaltar-hero.jpg'};
    const rows=global.CoiledAltarGuildView.groupBurstRows(guild.displayTimelines,pull.players||[],guild.unresolved||[],scope);
    current.players=rows.map(row=>{
      const specIcon=/^[a-z0-9-]+$/.test(row.icon||'')?row.icon:'';
      if(specIcon)images[specIcon]='/assets/specs/'+specIcon+'.jpg';
      return {n:row.player,color:/^#[a-f0-9]{6}$/i.test(row.classColor||'')?row.classColor:'#8d99aa',specIcon,
        s:row.skills.map(s=>{
          const kind=s.category==='trinket'?'item':s.category==='major-burst'?'major':'minor';
          skills[s.ability]={name:s.label,kind,spellID:(s.spellIDs||[])[0]};
          return {key:s.ability,c:(s.casts||[]).map(t=>finite(t)/1000),
            a:(s.intervals||[]).filter(a=>a.evidence!=='configured-estimate').map(a=>[finite(a.startTimeMs)/1000,finite(a.endTimeMs)/1000]),
            plan:!guild.actualOnly&&kind==='major'?(s.plannedWindows||[]).map(w=>[finite(w.timeMs)/1000,finite(w.endTimeMs)/1000,finite(w.windowStartMs)/1000,finite(w.windowEndMs)/1000]):[]};
        })};
    });
    const references=pulls.map(p=>({pull:p,value:comparison(p)})).filter(p=>p.value).map(p=>({...p.value,id:'night-'+p.pull.fightID,label:'Fight '+p.pull.fightID+'，'+(p.pull.duration||'')}));
    return {current,reference:assets.reference,references,skills,images,defs:assets.defs,bossIDs:assets.bossIDs};
  }

  function mount(host,guild,options={}){
 host._iconTimeline?.destroy();
 const data=makeModel(guild,options.pull,options.pulls||[],options.scope||'dps',options.assets);
 if(!data){host.textContent='本报告缺少新版图标轴证据，请重新分析或导入更新后的报告。';return null;}
 host.innerHTML="<div class=\"m7-icon-axis\">\n\n<div class=\"i-tools\">\n\n<label>参照 <select aria-label=\"参照时间轴\"><option value=\"old-m\">旧 M，10:36</option><option value=\"night-7\">Fight 7，08:04</option></select></label>\n<label>缩放 <output class=\"i-zoom\">200%</output><input type=\"range\" min=\"1\" max=\"12\" step=\"0.01\" value=\"2\" aria-label=\"时间轴缩放\"></label>\n<div class=\"i-buttons\"><button type=\"button\" class=\"i-action\" data-phase=\"all\" aria-pressed=\"false\">全场</button><button type=\"button\" class=\"i-action\" data-phase=\"p1\" aria-pressed=\"false\">P1</button><button type=\"button\" class=\"i-action\" data-phase=\"p2\" aria-pressed=\"false\">P2</button><button type=\"button\" class=\"i-action\" data-phase=\"intermission\" aria-pressed=\"false\">P2.5</button><button type=\"button\" class=\"i-action\" data-phase=\"p3\" aria-pressed=\"false\">P3</button></div>\n<span class=\"i-hint\">轴内滚轮缩放，拖动平移</span>\n</div>\n<div class=\"i-selection\" aria-label=\"技能与饰品选择\"></div>\n<div class=\"i-plan-key\"><label><input type=\"checkbox\" aria-label=\"显示预定轴\" checked><span class=\"i-key-ghost\"></span>预定轴（仅大技能）</label><span><i class=\"i-key-window\"></i>允许窗口</span><span><i class=\"i-key-actual\"></i>实心图标 / 持续条：实际</span></div>\n<div class=\"i-axis\" role=\"group\" aria-label=\"参照 Boss、当前 Boss 和全体 DPS 的预定与实际时间轴\"></div>\n<div class=\"i-footer\"><label>平移 <input type=\"range\" min=\"0\" max=\"320\" step=\"0.1\" value=\"0\" aria-label=\"时间轴平移\"></label><span class=\"i-range\"></span><span class=\"i-detail\" aria-live=\"polite\">—</span></div>\n<div class=\"i-note\">新旧 Boss 均取施法起点；阶段按同一光环生效划分（非 1 血退场）。预定轴按原表固定，判定仍为 2:50 / 3:05。</div>\n<div class=\"i-tooltip\" role=\"tooltip\" hidden></div></div>";
 const root=host.querySelector('.m7-icon-axis'),axis=root.querySelector('.i-axis'),selection=root.querySelector('.i-selection');
 const refSelect=root.querySelector('[aria-label="参照时间轴"]'),zoom=root.querySelector('[aria-label="时间轴缩放"]'),pan=root.querySelector('[aria-label="时间轴平移"]'),detail=root.querySelector('.i-detail');
 const names={p1:'P1',p2:'P2',intermission:'P2.5',p3:'P3'},colors={major:'var(--i-main)',minor:'var(--i-minor)',item:'var(--i-item)',boss:'var(--i-phase)'};
 const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const clock=s=>`${String(Math.floor(Math.max(0,s)/60)).padStart(2,'0')}:${String(Math.floor(Math.max(0,s)%60)).padStart(2,'0')}`;
 const allKeys=[...data.defs.map(d=>'boss.'+d[0]),...Object.keys(data.skills)];
 let state={fight:data.current.id,ref:'old-m',zoom:2,start:0,phase:'',showPlan:true,hidden:Object.keys(data.skills).filter(k=>data.skills[k].kind==='item'),...options.state},view=null,drag=null,saveTimer=null;
 if(guild.actualOnly){state.showPlan=false;root.querySelector('.i-plan-key').hidden=true;root.querySelector('.i-note').textContent='实心图标表示实际成功施法；上方为本场Boss机制。';} if(guild.checksEnabled===false)refSelect.closest('label').hidden=true; state.fight=data.current.id;state.zoom=Math.max(1,Math.min(12,+state.zoom||2));state.hidden=Array.isArray(state.hidden)?state.hidden:[];
 refSelect.innerHTML='<option value="old-m">旧 M，10:36</option>'+data.references.map(r=>`<option value="${r.id}">${escape(r.label)}</option>`).join('');
 if(state.ref!=='old-m'&&!data.references.some(r=>r.id===state.ref))state.ref='old-m';
 const save=()=>{if(options.state)Object.assign(options.state,state);};
 const queueSave=()=>{clearTimeout(saveTimer);saveTimer=setTimeout(save,250);};
 const fallbackNames=Object.fromEntries(Object.values(data.skills).map(s=>[String(s.spellID),s.name]));
 const img=(key,alt='')=>data.images[key]?`<img src="${escape(data.images[key])}" alt="${escape(alt)}" draggable="false">`:`<span class="i-missing-icon" title="${escape(fallbackNames[key]||alt||'技能')}">${escape((fallbackNames[key]||alt||'技能').slice(0,2))}</span>`;
 function filters(){
  const group=(kind,label,items)=>`<div class="i-group" style="--cat:${colors[kind]}"><label class="i-group-title"><input type="checkbox" data-group="${kind}" aria-label="显示${label}"><i></i>${label}</label><div class="i-filters">${items.map(([key,name,image])=>`<label class="i-filter" data-tooltip="${escape(name)}">${img(image)}<input type="checkbox" aria-label="显示${escape(name)}" data-key="${key}" ${state.hidden.includes(key)?'':'checked'}></label>`).join('')}</div></div>`;
  let html=group('boss','Boss',data.defs.map(([key,name])=>['boss.'+key,name,String(data.bossIDs[key])]));
  for(const [kind,label] of [['major','主要爆发'],['minor','次要爆发'],['item','饰品']])html+=group(kind,label,Object.entries(data.skills).filter(([key,s])=>s.kind===kind).map(([key,s])=>[key,s.name,String(s.spellID)]));
  selection.innerHTML=html;
  selection.querySelectorAll('[data-key]').forEach(input=>input.addEventListener('change',()=>{state.hidden=state.hidden.filter(k=>k!==input.dataset.key);if(!input.checked)state.hidden.push(input.dataset.key);syncGroups();render();save();}));
  selection.querySelectorAll('[data-group]').forEach(input=>input.addEventListener('change',()=>{const keys=input.dataset.group==='boss'?data.defs.map(d=>'boss.'+d[0]):Object.keys(data.skills).filter(k=>data.skills[k].kind===input.dataset.group);state.hidden=state.hidden.filter(k=>!keys.includes(k));if(!input.checked)state.hidden.push(...keys);filters();render();save();}));syncGroups();
 }
 function syncGroups(){selection.querySelectorAll('[data-group]').forEach(input=>{const groupInputs=Array.from(input.closest('.i-group').querySelectorAll('[data-key]'));input.checked=groupInputs.some(i=>i.checked);input.indeterminate=groupInputs.some(i=>i.checked)&&groupInputs.some(i=>!i.checked);});}
 function render(){
  const p=data.current,r=guild.checksEnabled===false?p:(data.references.find(r=>r.id===state.ref)||data.reference),total=Math.max(p.duration,r.duration),span=total/state.zoom;
  state.start=Math.max(0,Math.min(total-span,+state.start||0));view={p,r,total,span};
  refSelect.value=state.ref;zoom.value=state.zoom;root.querySelector('[aria-label="显示预定轴"]').checked=state.showPlan;root.querySelector('.i-zoom').textContent=Math.round(state.zoom*100)+'%';pan.max=total-span;pan.value=state.start;pan.disabled=state.zoom===1;root.querySelector('.i-range').textContent=clock(state.start)+' — '+clock(state.start+span);
  root.querySelectorAll('[data-phase]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.phase===state.phase)));
  const width=Math.max(100,root.clientWidth-(root.clientWidth<=600?118:165)),x=t=>(t-state.start)/span*100,visible=(a,b)=>b>=state.start&&a<=state.start+span;
  const segment=(a,b,cls,style='',content='')=>{if(!visible(a,b))return '';const left=Math.max(0,x(a)),right=Math.min(100,x(b));return `<span class="${cls}" style="left:${left}%;width:${Math.max(0,right-left)}%;${style}">${content}</span>`;};
  const step=[5,10,15,30,60,90,120,180,300,600].find(s=>span/s<=Math.max(2,Math.floor(width/65)))||600,ticks=[];
  for(let t=Math.ceil(state.start/step)*step;t<state.start+span;t+=step)ticks.push(t);
  const grid=()=>ticks.map(t=>`<span class="i-grid" style="left:${x(t)}%"></span>`).join('');
  const phases=(source,flags=false,compare=false)=>source.phases.map(([key,t],i)=>{const end=source.phases[i+1]?.[1]??source.duration;let out=segment(t,end,'i-shade');if(flags&&visible(t,t)){const other=r.phases.find(row=>row[0]===key),delta=compare&&other?t-other[1]:0,label=names[key]+(Math.abs(delta)>.05?` ${delta<0?'早':'晚'}${Math.abs(delta).toFixed(1)}s`:'');out+=`<span class="i-flag" style="left:${x(t)}%"><span class="i-flag-text">${label}</span></span>`;}return out;}).join('');
  const row=(label,content,cls='',style='')=>`<div class="i-row ${cls}"><div class="i-label" style="${style}">${label}</div><div class="i-lane">${content}</div></div>`;
  function event(a,b,image,kind,tooltip,aria,caption=false){if(!visible(a,b))return '';const left=Math.max(0,x(a)),duration=Math.max(0,b-a)/span*100,imageVisible=a>=state.start;return `<button type="button" class="i-event ${kind}" style="left:${left}%;width:${Math.max(0,duration)}%;--cat:${colors[kind]||colors.boss}" data-tooltip="${escape(tooltip)}" data-time="${escape(tooltip)}" aria-label="${escape(aria)}">${imageVisible?img(image):''}${caption?`<span class="i-time">${clock(a)}</span>`:''}</button>`;}
  let html=row('玩家 / 时间',ticks.map(t=>`<span class="i-tick" style="left:${x(t)}%;${x(t)<2?'transform:none':x(t)>94?'transform:translateX(-100%)':''}">${clock(t)}</span>`).join(''),'i-ruler');
  for(const [source,label,compare] of (guild.checksEnabled===false?[[p,'Fight '+p.id,true]]:[[r,state.ref==='old-m'?'旧 M':r.label||r.id,false],[p,'Fight '+p.id,true]])){
   let marks=grid()+phases(source,true,compare);
   const bossEvents=source.boss.filter(e=>!state.hidden.includes('boss.'+e[0])).slice().sort((a,b)=>a[1]-b[1]);
   bossEvents.forEach((e,i)=>{const [key,a,b]=e,name=data.defs.find(d=>d[0]===key)[1],sid=String(data.bossIDs[key]),tip=name+' '+clock(a)+(b>a?'–'+clock(b):''),next=Math.min(bossEvents[i+1]?.[1]??Infinity,state.start+span),caption=(next-a)/span*width>=70;marks+=event(a,b,sid,'boss',tip,tip,caption);});
   html+=row(img('boss')+`<span>${compare?'当前':'参照'}，${label}<small>${clock(source.duration)}</small></span>`,marks,'i-boss');
  }
  html+=`<div class="i-divider"><span>${guild.actualOnly?'玩家实际施法':'DPS，同一玩家的预定 / 实际'}</span><span>${p.players.length} 人</span></div>`;
  for(const player of p.players){let marks=phases(p)+grid();
   if(state.showPlan)for(const s of player.s){const def=data.skills[s.key];if(state.hidden.includes(s.key)||def.kind!=='major')continue;
    for(const [a,b,lo,hi] of s.plan||[]){if(!visible(lo,hi))continue;marks+=segment(lo,hi,'i-plan-window');const text=clock(a)+(b>a?'–'+clock(b):'');marks+=`<button type="button" class="i-planned" style="left:${x(lo)}%" data-tooltip="${text}" data-time="${text}" aria-label="${escape(player.n+' '+def.name+' 预定 '+text)}">${img(String(def.spellID))}</button>`;}
   }
   for(const s of player.s){if(state.hidden.includes(s.key))continue;const def=data.skills[s.key],used=new Set();
    const draws=s.c.map(t=>{let index=-1,best=Infinity;s.a.forEach(([a,b],i)=>{if(!used.has(i)&&Math.abs(a-t)<best&&Math.abs(a-t)<=3){index=i;best=Math.abs(a-t);}});if(index>=0){used.add(index);return [t,s.a[index][1]];}return[t,t];});
    s.a.forEach((a,i)=>{if(!used.has(i)&&!s.c.some(t=>t>=a[0]&&t<a[1]))draws.push(a);});
    draws.forEach(([a,b])=>{const text=clock(a)+(b>a?'–'+clock(b):'');marks+=event(a,b,String(def.spellID),def.kind,text,player.n+' '+def.name+' '+text);});
   }
   if(state.start+span>p.duration)marks+=segment(p.duration,state.start+span,'i-after');
   html+=row(img(player.specIcon)+`<span>${escape(player.n)}</span>`,marks,'',`--cls:${player.color}`);
  }
  html+='<div class="i-cross"><span class="i-cross-time"></span></div>';axis.innerHTML=html;
  axis.querySelectorAll('[data-time]').forEach(el=>{const show=()=>{detail.textContent=el.dataset.time;el.style.zIndex='12';};const clear=()=>el.style.zIndex='';el.addEventListener('pointerenter',show);el.addEventListener('focus',show);el.addEventListener('click',show);el.addEventListener('pointerleave',clear);el.addEventListener('blur',clear);});
 }
 refSelect.addEventListener('change',()=>{state.ref=refSelect.value;render();save();});
 zoom.addEventListener('input',()=>{const center=state.start+view.span/2;state.zoom=+zoom.value;state.start=center-view.total/state.zoom/2;state.phase='';render();});zoom.addEventListener('change',save);pan.addEventListener('input',()=>{state.start=+pan.value;state.phase='';render();});pan.addEventListener('change',save);
 root.querySelector('[aria-label="显示预定轴"]').addEventListener('change',e=>{state.showPlan=e.target.checked;render();save();});
 root.querySelectorAll('[data-phase]').forEach(b=>b.addEventListener('click',()=>{state.phase=b.dataset.phase;if(state.phase==='all'){state.zoom=1;state.start=0;}else{const bounds=[view.p,view.r].map(p=>{const i=p.phases.findIndex(v=>v[0]===state.phase);return i<0?null:[p.phases[i][1],p.phases[i+1]?.[1]??p.duration];}).filter(Boolean);if(bounds.length){state.start=Math.max(0,Math.min(...bounds.map(v=>v[0]))-5);state.zoom=Math.min(12,Math.max(1,view.total/(Math.max(...bounds.map(v=>v[1]))-state.start+5)));}}render();save();}));
 function anchoredZoom(start,total,currentZoom,fraction,delta){const next=Math.max(1,Math.min(12,currentZoom*Math.exp(-delta*.0018))),anchor=start+fraction*total/currentZoom;return {zoom:next,start:Math.max(0,Math.min(total-total/next,anchor-fraction*total/next))};}
 axis.addEventListener('wheel',e=>{const lane=e.target.closest('.i-lane');if(!lane)return;e.preventDefault();const rect=lane.getBoundingClientRect(),f=Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width));if(Math.abs(e.deltaX)>Math.abs(e.deltaY)&&!e.ctrlKey){state.start+=e.deltaX/rect.width*view.span;}else{const delta=e.deltaMode===1?e.deltaY*16:e.deltaY;Object.assign(state,anchoredZoom(state.start,view.total,state.zoom,f,delta));}state.phase='';render();queueSave();},{passive:false});
 axis.addEventListener('pointerdown',e=>{const lane=e.target.closest('.i-lane');if(!lane)return;drag={x:e.clientX,start:state.start,width:lane.clientWidth,moved:false,pointer:e.pointerId};});
 axis.addEventListener('pointermove',e=>{const lane=e.target.closest('.i-lane'),cross=axis.querySelector('.i-cross');if(drag&&Math.abs(e.clientX-drag.x)>3){drag.moved=true;axis.setPointerCapture(e.pointerId);state.start=drag.start-(e.clientX-drag.x)/drag.width*view.span;state.phase='';render();return;}if(lane&&cross){const rect=lane.getBoundingClientRect(),axisRect=axis.getBoundingClientRect(),f=Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width));cross.style.display='block';cross.style.left=(e.clientX-axisRect.left)+'px';cross.querySelector('span').textContent=clock(state.start+f*view.span);}});
 axis.addEventListener('pointerup',()=>{if(drag?.moved)save();drag=null;});axis.addEventListener('pointercancel',()=>{drag=null;});axis.addEventListener('pointerleave',()=>{const c=axis.querySelector('.i-cross');if(c)c.style.display='none';});
 filters();render();let lastWidth=root.clientWidth;const observer=new ResizeObserver(()=>{if(lastWidth!==root.clientWidth){lastWidth=root.clientWidth;render();}});observer.observe(root);
 const tooltip=root.querySelector('.i-tooltip');
 const showTip=el=>{tooltip.textContent=el.dataset.tooltip;tooltip.hidden=false;const r=el.getBoundingClientRect(),parent=root.getBoundingClientRect();tooltip.style.left=Math.max(4,Math.min(parent.width-tooltip.offsetWidth-4,r.left-parent.left))+'px';tooltip.style.top=Math.max(0,r.top-parent.top-tooltip.offsetHeight-5)+'px';};
 root.addEventListener('pointerover',e=>{const el=e.target.closest('[data-tooltip]');if(el)showTip(el);});
 root.addEventListener('pointerout',e=>{if(e.target.closest('[data-tooltip]'))tooltip.hidden=true;});
 root.addEventListener('focusin',e=>{const el=e.target.closest('[data-tooltip]');if(el)showTip(el);});
 root.addEventListener('focusout',()=>tooltip.hidden=true);
 root.addEventListener('pointerdown',()=>tooltip.hidden=true);
 const controller={destroy(){save();observer.disconnect();clearTimeout(saveTimer);},state};host._iconTimeline=controller;return controller;

}


  const api={makeModel,mount};
  global.CoiledAltarIconTimeline=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
