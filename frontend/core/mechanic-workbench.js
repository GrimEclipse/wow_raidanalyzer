/* Generic event explorer. Boss adapters own rules, labels and map projections. */
(function (global) {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const time = ms => { const s=Math.max(0,Number(ms)||0)/1000;return `${Math.floor(s/60)}:${(s%60).toFixed(1).padStart(4,'0')}`; };
  const unique = rows => [...new Set(rows.filter(value => value != null && value !== ''))];
  function trackPosition(unit, cursor, maxGap=5000) {
    const rows=unit.samples||[];if(!rows.length)return null;
    let lo=0,hi=rows.length;while(lo<hi){const mid=(lo+hi)>>1;if(rows[mid][0]<=cursor)lo=mid+1;else hi=mid;}
    const a=rows[Math.max(0,lo-1)],b=rows[lo];
    if(cursor<a[0]&&a[0]-cursor>maxGap)return null;
    if(b&&cursor>=a[0]&&b[0]-a[0]<=maxGap){const f=(cursor-a[0])/(b[0]-a[0]||1);return {x:a[1]+(b[1]-a[1])*f,y:a[2]+(b[2]-a[2])*f,stale:false};}
    return {x:a[1],y:a[2],stale:Math.abs(cursor-a[0])>maxGap};
  }
  function lifeState(unit,cursor,duration=900){
    const state=(unit.states||[]).findLast(s=>s[0]<=cursor),dead=state?.[1]==='dead';
    return {dead,opacity:dead?Math.max(0,1-(cursor-state[0])/duration):1,positionTime:dead?state[0]:cursor};
  }
  function avatar(unit,q,r=12,hit=false,dead=false,opacity){
    const color=hit?'#ff414f':unit.color||unit.classColor||'#fff',icon=unit.icon?.startsWith('/')?unit.icon:unit.icon?`/assets/specs/${unit.icon}.jpg`:null;
    return `<g data-key="actor:${esc(unit.key||unit.actorID)}" transform="translate(${q.x} ${q.y})" opacity="${opacity??(dead?.45:q.stale?.6:1)}"><title>${esc(unit.name||unit.player)}${dead?' · 已死亡':hit?' · 受到伤害':''}${q.stale?' · 最近已知位置':''}</title><circle r="${r+2}" fill="${hit?'#ff414f':'#070c16'}" stroke="${color}" stroke-width="${hit?4:2}"/>${icon?`<image href="${esc(icon)}" x="${-r}" y="${-r}" width="${r*2}" height="${r*2}" preserveAspectRatio="xMidYMid slice" style="clip-path:circle(50%)"/>`:`<text text-anchor="middle" y="4" fill="${color}" font-size="11">${esc((unit.name||unit.player||'?').slice(0,1))}</text>`}${hit?`<circle r="${r}" fill="#ff223b" opacity=".5"/>`:''}${dead?`<path d="M -7 -7 L 7 7 M 7 -7 L -7 7" stroke="#fff" stroke-width="2"/>`:''}</g>`;
  }
  function activeCast(b,cursor){
    return !lifeState(b,cursor).dead&&(b.casts||[]).findLast(c=>['completed','interrupted'].includes(c.outcome)&&c.startTimeMs<=cursor&&c.endTimeMs>cursor)||null;
  }
  function castBar(b,cursor,q,width=124){
    const cast=activeCast(b,cursor);if(!cast||!q)return '';
    const progress=Math.max(0,Math.min(1,(cursor-cast.startTimeMs)/(cast.endTimeMs-cast.startTimeMs))),fill=cast.phase==='channel'?1-progress:progress,color=cast.phase==='channel'?'#78cee6':'#efbd6a';
    return `<g data-key="castbar:${b.actorID}" transform="translate(${q.x-width/2} ${q.y-44})" pointer-events="none"><rect width="${width}" height="19" rx="4" fill="#09111fe8" stroke="${color}" stroke-width="1"/><rect x="2" y="2" width="${(width-4)*fill}" height="15" rx="2" fill="${color}" opacity=".55"/><text x="${width/2}" y="13" text-anchor="middle" style="font:10px system-ui;fill:#fff;stroke:#09111f;stroke-width:2px;paint-order:stroke">${esc(cast.spellName||'施法')}</text></g>`;
  }
  function bossStatus(replay,cursor){
    return `<div class="mw-boss-status" aria-label="首领血量与施法">${(replay?.bosses||[]).map(b=>{
      const dead=lifeState(b,cursor).dead,hp=(b.health||[]).findLast(p=>p[0]<=cursor),percent=dead?0:hp?Math.max(0,Math.min(100,hp[1]/hp[2]*100)):null;
      const cast=activeCast(b,cursor),progress=cast?(cursor-cast.startTimeMs)/(cast.endTimeMs-cast.startTimeMs)*100:0;
      const energy=(b.energy||[]).findLast(p=>p[0]<=cursor),power=b.energy?.length?`<div class="mw-energy"><span>能量 ${energy?Math.round(energy[1])+'/'+Math.round(energy[2]):'—'}</span><i style="width:${energy?Math.max(0,Math.min(100,energy[1]/energy[2]*100)):0}%"></i></div>`:'';
      return `<div class="mw-boss-card ${b.energy?.length?'mw-has-energy':''}" data-key="boss-status:${b.actorID}"><div><b>${esc(b.name)}</b><span>${percent==null?'血量未记录':percent.toFixed(1)+'%'}</span></div><div class="mw-health"><i style="width:${percent??0}%"></i></div>${power}<div class="mw-cast ${cast?'active':''}"><i style="width:${cast?.phase==='channel'?100-progress:progress}%"></i><span>${cast?`${cast.phase==='channel'?'引导 · ':''}${esc(cast.spellName||'施法')} · ${((cast.endTimeMs-cursor)/1000).toFixed(1)}s`:''}</span></div></div>`;
    }).join('')}</div>`;
  }
  // Keep loaded image nodes and keyed actor nodes alive during playback.
  function patchMap(host,html){
    const template=document.createElement('template'),svg=host.namespaceURI==='http://www.w3.org/2000/svg';template.innerHTML=svg?`<svg>${html}</svg>`:html;
    const key=n=>n.nodeType===1?(n.getAttribute('data-key')||n.id||null):null;
    const compatible=(a,b)=>a&&a.nodeType===b.nodeType&&(a.nodeType!==1||(a.localName===b.localName&&a.namespaceURI===b.namespaceURI));
    function reconcile(parent,next){
      const old=[...parent.childNodes],used=new Set(),keyed=new Map(old.filter(key).map(n=>[key(n),n]));let anchor=parent.firstChild;
      for(const fresh of [...next.childNodes]){
        const k=key(fresh);let node=k?keyed.get(k):old.find(n=>!used.has(n)&&!key(n)&&compatible(n,fresh));
        if(!compatible(node,fresh)){node=fresh.cloneNode(true);}else if(node.nodeType===1){
          for(const attr of [...node.attributes])if(!fresh.hasAttribute(attr.name))node.removeAttribute(attr.name);
          for(const attr of [...fresh.attributes])if(node.getAttribute(attr.name)!==attr.value)node.setAttribute(attr.name,attr.value);
          reconcile(node,fresh);
        }else if(node.nodeValue!==fresh.nodeValue)node.nodeValue=fresh.nodeValue;
        used.add(node);if(node!==anchor)parent.insertBefore(node,anchor);anchor=node.nextSibling;
      }
      for(const node of old)if(!used.has(node)&&!node.hasAttribute?.('data-managed'))node.remove();
    }
    reconcile(host,svg?template.content.firstElementChild:template.content);
  }
  const fields = {sourceID:'施法者 ID',targetID:'目标 ID',actor:'玩家 / 单位',role:'角色',layer:'机制',group:'分组 / 轮次',outcome:'结果',kind:'事件类型',spellID:'法术 ID'};
  const columns={timeMs:'时间',label:'机制 / 事件',actor:'玩家 / 单位',role:'角色',group:'轮次 / 分组',outcome:'结果',kind:'事件类型',spellID:'法术 ID',amount:'伤害',stack:'光环层数',points:'坐标证据',positionX:'原始 X',positionY:'原始 Y',sampleOffsetMs:'坐标偏移（ms）',evidence:'证据说明',sourceID:'施法者 ID',targetID:'目标 ID'};
  const defaultColumns=['timeMs','label','actor','group','outcome','points'];
  function projectGuides(event,project){return (event?.guides||[]).flatMap(g=>{const p=g.origin,a=g.axis;if(!p||!a||![p.x,p.y,a.x,a.y].every(v=>v!=null&&Number.isFinite(Number(v))))return [];const q=project(p),r=project({x:Number(p.x)+Number(a.x)*100,y:Number(p.y)+Number(a.y)*100});if(!q||!r)return [];const dx=r.x-q.x,dy=(r.y-q.y)*.56,length=Math.hypot(dx,dy);if(!length)return [];return [{x1:q.x-dx/length*150,y1:q.y*.56-dy/length*150,x2:q.x+dx/length*150,y2:q.y*.56+dy/length*150,label:g.label||'方向参考'}];});}
  function filterEvents(events, config) {
    const query=String(config.query||'').toLocaleLowerCase();
    return events.filter(e => (!config.layers?.length || config.layers.includes(e.layer)) && (!config.actor || e.actor===config.actor)
      && (!config.group || String(e.group)===String(config.group)) && (!config.problemOnly || e.problem)
      && Number(e.timeMs)>=Number(config.from||0) && Number(e.timeMs)<=Number(config.to??Infinity)
      && (!query || [e.label,e.actor,e.group,e.outcome,e.evidence,e.spellID].join(' ').toLocaleLowerCase().includes(query)));
  }
  function aggregate(events, rowKey, colKey, metric='count') {
    const rows=unique(events.map(e=>String(e[rowKey]??'未知'))),columns=unique(events.map(e=>String(e[colKey]??'未知'))),values=new Map();
    for(const e of events){const key=JSON.stringify([String(e[rowKey]??'未知'),String(e[colKey]??'未知')]);values.set(key,metric==='maxStack'?Math.max(values.get(key)||0,Number(e.stack||0)):(values.get(key)||0)+(metric==='amount'?Number(e.amount||0):metric==='problems'?Number(Boolean(e.problem)):1));}
    return {rows,columns,values};
  }
  function cleanConfig(raw, duration, layers) {
    const number=(value,fallback,min,max)=>Number.isFinite(Number(value))?Math.min(max,Math.max(min,Number(value))):fallback;
    const from=number(raw.from,0,0,duration),to=number(raw.to,duration,from,duration);
    return {layers:Array.isArray(raw.layers)?raw.layers.filter(x=>layers.includes(x)||x==='__none__'):[],actor:String(raw.actor||''),group:String(raw.group||''),query:String(raw.query||'').slice(0,200),
      problemOnly:raw.problemOnly===true,from,to,zoom:number(raw.zoom,1,1,3),windowMs:number(raw.windowMs,3000,100,60000),rowKey:Object.hasOwn(fields,raw.rowKey)?raw.rowKey:'actor',colKey:Object.hasOwn(fields,raw.colKey)?raw.colKey:'layer',
      metric:['count','amount','problems','maxStack'].includes(raw.metric)?raw.metric:'count',view:['map','matrix','table'].includes(raw.view)?raw.view:'map',
      columns:Array.isArray(raw.columns)&&raw.columns.some(k=>Object.hasOwn(columns,k))?raw.columns.filter(k=>Object.hasOwn(columns,k)):defaultColumns,projection:raw.projection==='relative'?'relative':'calibrated',calibration:raw.calibration && ['minX','maxX','minY','maxY'].every(k=>Number.isFinite(Number(raw.calibration[k])))?Object.fromEntries(['minX','maxX','minY','maxY'].map(k=>[k,Number(raw.calibration[k])])):null};
  }
  function mount(host, scene, adapter={}) {
    if(!host)return;
    host._workbench?.destroy();
    const events=[...(scene.events||[])].filter(e=>e.timeMs!=null&&Number.isFinite(Number(e.timeMs))).map(e=>{const p=e.points?.find(p=>p.position)?.position;return {...e,positionX:p?.x,positionY:p?.y,sampleOffsetMs:p?p.sampleOffsetMs??0:null};}).sort((a,b)=>a.timeMs-b.timeMs);
    const duration=Math.max(1,Number(scene.durationMs)||events.at(-1)?.timeMs||1),layers=unique(events.map(e=>e.layer)),storageKey=`mythic:view:v1:${scene.key}`;
    let config=cleanConfig({},duration,layers),selected=events[0]||null,cursor=Number(selected?.timeMs||0),playing=false,frame=0,last=0,page=0,filtered=[];
    function relativeBounds(){const pts=events.flatMap(x=>(x.points||[]).map(p=>p.position)).filter(p=>p&&Number.isFinite(Number(p.x))&&Number.isFinite(Number(p.y)));if(!pts.length)return null;const extent=pts.reduce((b,p)=>({minX:Math.min(b.minX,Number(p.x)),maxX:Math.max(b.maxX,Number(p.x)),minY:Math.min(b.minY,Number(p.y)),maxY:Math.max(b.maxY,Number(p.y))}),{minX:Infinity,maxX:-Infinity,minY:Infinity,maxY:-Infinity}),dx=Math.max(100,(extent.maxX-extent.minX)*.1),dy=Math.max(100,(extent.maxY-extent.minY)*.1);return {minX:extent.minX-dx,maxX:extent.maxX+dx,minY:extent.minY-dy,maxY:extent.maxY+dy};}
    if(scene.projection==='uncalibrated'){config.calibration=relativeBounds();config.projection='relative';}
    host.classList.add('mw');
    if(new URLSearchParams(global.location?.search||'').get('embed')==='1')document.body.classList.add('mw-embed');
    host.classList.toggle('mw-video',Boolean(adapter.video)||new URLSearchParams(global.location?.search||'').get('embed')==='1');
    const choices=(items,label='全部')=>`<option value="">${esc(label)}</option>${items.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('')}`;
    const fieldOptions=Object.entries(fields).map(([k,v])=>`<option value="${k}">${v}</option>`).join('');
    host.innerHTML=`<header class="mw-head"><div><span class="mw-eyebrow">MECHANIC WORKSPACE</span><h2>${esc(scene.title||'机制工作台')}</h2></div><div class="mw-actions"><button data-action="save">保存视图</button><button data-action="restore">恢复视图</button><button data-action="export">导出视图</button><label class="mw-upload">导入视图<input type="file" accept="application/json,.json" data-input="preset" hidden></label><button data-action="csv">导出数据 CSV</button></div></header>
      <p class="mw-note">${esc(scene.note||'视图调整在浏览器内完成。')}</p><div class="mw-filters"><label>玩家 / 单位<select data-config="actor">${choices(unique(events.map(e=>e.actor)))}</select></label><label>分组 / 轮次<select data-config="group">${choices(unique(events.map(e=>String(e.group??''))))}</select></label><label>搜索证据<input data-config="query" placeholder="玩家、法术或结果"></label><label>开始（秒）<input data-config="from" type="number" min="0" step=".1" value="0"></label><label>结束（秒）<input data-config="to" type="number" min="0" step=".1" value="${duration/1000}"></label><label>位置快照窗口（秒）<input data-config="windowMs" type="number" min=".1" max="60" step=".1" value="3"></label><label>死亡截止<select data-input="deathCutoff"><option value="">完整战斗</option>${(scene.deaths||[]).filter(e=>e.kind!=='combat_res').slice(0,10).map((e,i)=>`<option value="${e.timeMs}">第 ${i+1} 次死亡 · ${time(e.timeMs)}</option>`).join('')}</select></label><label class="mw-check"><input data-config="problemOnly" type="checkbox">只看已标记问题</label></div>
      <div class="mw-layers">${layers.map(layer=>`<label><input type="checkbox" data-layer="${esc(layer)}" checked>${esc(layer)}</label>`).join('')}<button data-action="layers">显示全部</button></div>
      <div class="mw-transport"><button data-action="play" aria-label="播放事件时间轴">播放</button><button data-action="prev">上一事件</button><button data-action="next">下一事件</button><button data-action="problem">下一问题</button><select data-input="speed" aria-label="播放速度"><option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option><option value="8">8×</option></select><output data-slot="clock"></output><span data-slot="count"></span></div>
      <input class="mw-scrub" data-input="time" type="range" min="0" max="${duration}" step="100" value="${cursor}" aria-label="战斗时间"><div class="mw-tracks" data-slot="tracks"></div>
      <div class="mw-views"><label>地图缩放<select data-config="zoom"><option value="1">1×</option><option value="1.5">1.5×</option><option value="2">2×</option><option value="3">3×</option></select></label><button data-action="focus">定位选中事件</button><button data-view="map">场地快照</button><button data-view="matrix">自定义矩阵</button><button data-view="table">证据表</button></div>
      <div class="mw-matrix-options" data-slot="matrixOptions" hidden><label>行<select data-config="rowKey">${fieldOptions}</select></label><label>列<select data-config="colKey">${fieldOptions}</select></label><label>数值<select data-config="metric"><option value="count">事件次数</option><option value="amount">伤害总量</option><option value="problems">标记问题数</option><option value="maxStack">最高光环层数</option></select></label></div>
      <div class="mw-layout"><section data-slot="stage" class="mw-stage"></section><aside data-slot="detail" class="mw-detail"></aside></div>
      <details class="mw-calibration" ${adapter.renderMap||adapter.project?'hidden':''}><summary>场地坐标校准</summary><p>输入与图片边界对应的 WCL 坐标。相对坐标视图展示事件间的位置关系；手动边界校准仅适用于图片与坐标轴同向的场地。</p>${['minX','maxX','minY','maxY'].map((k,i)=>`<label>${['左 X','右 X','下 Y','上 Y'][i]}<input type="number" data-bound="${k}" step="any"></label>`).join('')}<button data-action="calibrate">应用校准</button><button data-action="relative">相对坐标示意</button><span data-slot="calibrationStatus"></span></details>
      <details class="mw-columns"><summary>自定义证据表列</summary>${Object.entries(columns).map(([key,label])=>`<label><input type="checkbox" data-column="${key}" ${defaultColumns.includes(key)?'checked':''}>${label}</label>`).join('')}</details><div class="mw-evidence" data-slot="list"></div><div class="mw-pages"><button data-action="pagePrev">前页</button><span data-slot="page"></span><button data-action="pageNext">后页</button></div><div class="mw-status" data-slot="status" role="status"></div>`;
    const slot=name=>host.querySelector(`[data-slot="${name}"]`),input=name=>host.querySelector(`[data-input="${name}"]`);
    const status=value=>slot('status').textContent=value;
    function download(value,name,type){const url=URL.createObjectURL(new Blob([value],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    function stop(){playing=false;cancelAnimationFrame(frame);host.querySelector('[data-action="play"]').textContent='播放';}
    function play(until=config.to){if(!filtered.length&&!scene.combatReplay)return;playing=true;last=performance.now();host.querySelector('[data-action="play"]').textContent='暂停';const end=Math.min(duration,until),tick=now=>{if(!host.isConnected){stop();return;}cursor=Math.min(end,cursor+(now-last)*Number(input('speed').value));last=now;selected=filtered.findLast(x=>x.timeMs<=cursor)||filtered[0];renderFrame();if(cursor>=end)stop();else frame=requestAnimationFrame(tick);};frame=requestAnimationFrame(tick);}
    function select(e){stop();selected=e||null;cursor=Number(e?.timeMs||cursor);renderFrame();renderList();}
    function project(point){if(adapter.project)return adapter.project(point);const b=config.calibration;if(!b||b.maxX<=b.minX||b.maxY<=b.minY)return null;return {x:100*(point.x-b.minX)/(b.maxX-b.minX),y:100*(b.maxY-point.y)/(b.maxY-b.minY)};}
    function map(){if(adapter.renderMap)return adapter.renderMap(selected,filtered,cursor,config)||'<p>当前没有可绘制的快照。</p>';
      const nearby=filtered.filter(e=>Math.abs(e.timeMs-cursor)<=config.windowMs);
      const candidates=nearby.flatMap(e=>(e.points||[]).map(p=>({e,p,q:p.position?project(p.position):null}))).filter(x=>x.q&&x.q.x>=0&&x.q.x<=100&&x.q.y>=0&&x.q.y<=100),closest=new Map();
      for(const candidate of candidates){const key=JSON.stringify([candidate.e.actorID??candidate.e.actor,candidate.e.layer,candidate.p.label]),previous=closest.get(key);if(!previous||candidate.e===selected||(previous.e!==selected&&Math.abs(candidate.e.timeMs-cursor)<Math.abs(previous.e.timeMs-cursor)))closest.set(key,candidate);}
      const points=[...closest.values()];
      return `<div class="mw-map ${config.projection==='relative'?'mw-relative':''}">${scene.arenaImage?`<img src="${esc(scene.arenaImage)}" alt="首领场地图">`:''}<svg viewBox="0 0 100 56" aria-label="事件位置">${projectGuides(selected,project).map(g=>`<line x1="${g.x1}" y1="${g.y1}" x2="${g.x2}" y2="${g.y2}" stroke="#fbbf24" stroke-width=".3" stroke-dasharray="1.2 .7"><title>${esc(g.label)}</title></line>`).join('')}${points.map(({e,p,q})=>`<g data-event="${esc(e.id)}" role="button" tabindex="0" aria-label="${esc(p.label||e.label)}"><title>${esc(time(e.timeMs)+' '+e.label+' '+e.evidence)}</title><circle cx="${q.x}" cy="${q.y*.56}" r="${selected?.id===e.id?1.2:.8}" class="${e.problem?'mw-problem':''}" style="fill:${e.problem?'#fb7185':/^#[\da-f]{3,8}$/i.test(p.color||'')?p.color:'#a2ead3'}"></circle><text x="${q.x+1.3}" y="${q.y*.56+.5}">${adapter.hidePointLabels||host.classList.contains('mw-video')?'':esc(p.label||e.actor||e.label)}</text></g>`).join('')}</svg>${!points.length?`<div class="mw-map-note">${config.calibration||adapter.project?'该时间窗没有已知位置':'坐标尚未校准 · 可在下方设置场地边界'}</div>`:''}</div><div class="mw-map-caption">${config.projection==='relative'?'相对坐标示意 · 与场地图未标定。':''}±${config.windowMs/1000} 秒内每个单位、机制的最近位置快照；全部事件保留在证据表。</div>`;}
    function matrix(){const data=aggregate(filtered,config.rowKey,config.colKey,config.metric);return `<div class="mw-table-wrap"><table><thead><tr><th>${fields[config.rowKey]}</th>${data.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${data.rows.map(r=>`<tr><th>${esc(r)}</th>${data.columns.map(c=>`<td>${(data.values.get(JSON.stringify([r,c]))||0).toLocaleString('zh-CN')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
    function renderFrame(){input('time').value=String(cursor);slot('clock').textContent=time(cursor);slot('tracks').style.setProperty('--cursor',`${100*cursor/duration}%`);
      if(config.view==='map'){patchMap(slot('stage'),map());if(slot('stage').firstElementChild)slot('stage').firstElementChild.style.width=`${config.zoom*100}%`;
        const fieldForStatus=slot('stage').querySelector('.field-map,.replay-map,.mw-map,.brood-map,[data-replay-field]');if(fieldForStatus){let hud=fieldForStatus.querySelector('[data-managed="boss-status"]');if(!hud){hud=document.createElement('div');hud.setAttribute('data-managed','boss-status');fieldForStatus.append(hud);}patchMap(hud,bossStatus(scene.combatReplay,cursor));}
        if(fieldForStatus&&scene.combatReplay){
          let bars=fieldForStatus.querySelector('[data-managed="boss-casts"]');if(!bars){bars=document.createElementNS('http://www.w3.org/2000/svg','svg');bars.setAttribute('data-managed','boss-casts');bars.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:8';fieldForStatus.append(bars);}
          const w=fieldForStatus.clientWidth||800,h=fieldForStatus.clientHeight||450;bars.setAttribute('viewBox',`0 0 ${w} ${h}`);
          patchMap(bars,(scene.combatReplay.bosses||[]).map(b=>{const unit=scene.combatReplay.units?.find(u=>u.actorID===b.actorID),point=unit&&trackPosition(unit,cursor,scene.combatReplay.interpolateMaxGapMs),q=adapter.bossPosition?adapter.bossPosition(b,cursor):point&&project(point);return q?castBar(b,cursor,{x:q.x*w/100,y:q.y*h/100}):'';}).join(''));
        }
        if(scene.combatReplay&&!adapter.handlesPlayers){
          const field=slot('stage').querySelector('.field-map,.replay-map,.mw-map,.brood-map,[data-replay-field]');
          if(field){let overlay=field.querySelector('[data-managed="players"]');if(!overlay){overlay=document.createElementNS('http://www.w3.org/2000/svg','svg');overlay.setAttribute('data-managed','players');overlay.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none';field.append(overlay);}
            const w=field.clientWidth||800,h=field.clientHeight||450;overlay.setAttribute('viewBox',`0 0 ${w} ${h}`);
            patchMap(overlay,(scene.combatReplay.units||[]).filter(u=>u.kind==='player'&&(!config.actor||u.name===config.actor)).map(u=>{const life=lifeState(u,cursor),pos=trackPosition(u,life.positionTime,scene.combatReplay.interpolateMaxGapMs),q=pos&&project(pos);return q?avatar(u,{x:q.x*w/100,y:q.y*h/100,stale:pos.stale},11,false,life.dead,life.opacity):'';}).join(''));
          }
        }
      }
      if(selected){slot('detail').innerHTML=`<div class="mw-eyebrow">选中事件 · ${time(selected.timeMs)}</div><h3>${esc(selected.label)}</h3><p>${esc(selected.actor||'团队事件')}</p><dl><dt>分组</dt><dd>${esc(selected.group||'—')}</dd><dt>结果</dt><dd>${esc(selected.outcome||'已记录')}</dd><dt>类型</dt><dd>${esc(selected.kind||'—')}</dd><dt>伤害</dt><dd>${Number(selected.amount||0).toLocaleString('zh-CN')}</dd></dl><p class="mw-note">${esc(selected.evidence||'日志事件')}</p>${selected.detail?`<p>${esc(selected.detail)}</p>`:''}`;}else slot('detail').innerHTML='<p>当前筛选没有事件。</p>';
    }
    function renderList(){const pages=Math.max(1,Math.ceil(filtered.length/100));page=Math.min(page,pages-1);slot('page').textContent=`${page+1} / ${pages}`;
      const rows=filtered.slice(page*100,page*100+100),cell=(e,k)=>k==='timeMs'?`<button data-event="${esc(e.id)}">${time(e.timeMs)}</button>`:k==='points'?((e.points||[]).some(p=>p.position)?(e.points.some(p=>p.position?.sampleOffsetMs!=null)?'相邻快照':'事件坐标'):'缺失 / 未提供'):esc(e[k]??'—');slot('list').innerHTML=`<div class="mw-table-wrap"><table><thead><tr>${config.columns.map(k=>`<th>${columns[k]}</th>`).join('')}</tr></thead><tbody>${rows.map(e=>`<tr data-event="${esc(e.id)}" class="${selected?.id===e.id?'mw-selected':''}">${config.columns.map(k=>`<td>${cell(e,k)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    }
    function render(){stop();filtered=filterEvents(events,config);if(!filtered.includes(selected)){selected=filtered[0]||null;cursor=Number(selected?.timeMs||config.from);}page=0;
      slot('count').textContent=`${filtered.length} / ${events.length} 条事件`;slot('tracks').innerHTML=layers.filter(l=>filtered.some(e=>e.layer===l)).map(l=>`<div class="mw-track"><span>${esc(l)}</span><div>${filtered.filter(e=>e.layer===l).map(e=>`<button class="${e.problem?'mw-bad':''}" data-event="${esc(e.id)}" style="left:${100*e.timeMs/duration}%" title="${esc(time(e.timeMs)+' '+e.label+' '+(e.actor||''))}" aria-label="${esc(time(e.timeMs)+' '+e.label)}"></button>`).join('')}</div></div>`).join('');
      host.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===config.view));slot('matrixOptions').hidden=config.view!=='matrix';slot('stage').hidden=config.view==='table';slot('detail').hidden=config.view!=='map';slot('stage').classList.toggle('mw-map-stage',config.view==='map');if(config.view==='matrix')slot('stage').innerHTML=matrix();renderFrame();renderList();
    }
    function sync(){host.querySelectorAll('[data-column]').forEach(e=>e.checked=config.columns.includes(e.dataset.column));slot('calibrationStatus').textContent=config.projection==='relative'?'相对坐标示意 · 与场地图未标定':config.calibration?'使用自定义校准':'';host.querySelectorAll('[data-config]').forEach(e=>{const k=e.dataset.config;if(e.type==='checkbox')e.checked=config[k];else e.value=['from','to','windowMs'].includes(k)?config[k]/1000:config[k];});host.querySelectorAll('[data-layer]').forEach(e=>e.checked=!config.layers.length||config.layers.includes(e.dataset.layer));if(config.calibration)host.querySelectorAll('[data-bound]').forEach(e=>e.value=config.calibration[e.dataset.bound]);render();}
    host.addEventListener('change',e=>{if(e.target.dataset.column){const selectedColumns=[...host.querySelectorAll('[data-column]:checked')].map(x=>x.dataset.column);if(selectedColumns.length){config.columns=selectedColumns;renderList();}else{e.target.checked=true;status('至少保留一列。');}}if(e.target===input('deathCutoff')){config.to=e.target.value?Number(e.target.value):duration;sync();}if(e.target.dataset.config){const k=e.target.dataset.config;config[k]=e.target.type==='checkbox'?e.target.checked:['from','to','windowMs'].includes(k)?Number(e.target.value)*1000:e.target.value;config=cleanConfig(config,duration,layers);render();}
      if(e.target.dataset.layer){const checked=[...host.querySelectorAll('[data-layer]:checked')].map(x=>x.dataset.layer);config.layers=checked.length?checked:['__none__'];render();}});
    host.addEventListener('input',e=>{if(e.target.dataset.config==='query'){config.query=e.target.value;render();}if(e.target===input('time')){stop();cursor=Number(e.target.value);selected=filtered.findLast(x=>x.timeMs<=cursor)||filtered[0]||null;renderFrame();}});
    host.addEventListener('click',e=>{const eventNode=e.target.closest('[data-event]');if(eventNode){select(filtered.find(x=>String(x.id)===eventNode.dataset.event));return;}
      const view=e.target.closest('[data-view]');if(view){config.view=view.dataset.view;render();return;}const action=e.target.closest('[data-action]')?.dataset.action;
      if(action==='play'){if(playing){stop();return;}if(cursor>=config.to)cursor=config.from;play();}
      if(action==='next'||action==='prev'||action==='problem'){const eligible=action==='problem'?filtered.filter(x=>x.problem):filtered,index=eligible.indexOf(selected);const next=index>=0?eligible[index+(action==='prev'?-1:1)]:action==='prev'?[...eligible].reverse().find(x=>x.timeMs<=cursor):eligible.find(x=>x.timeMs>=cursor);if(next)select(next);else status('没有更多匹配事件。');}
      if(action==='focus'){const point=selected?.points?.find(p=>p.position)?.position,q=point?project(point):null,stage=slot('stage');if(q&&stage.firstElementChild){stage.scrollLeft=Math.max(0,q.x/100*stage.firstElementChild.offsetWidth-stage.clientWidth/2);stage.scrollTop=Math.max(0,q.y/100*stage.firstElementChild.offsetHeight-stage.clientHeight/2);}else status('选中事件没有可定位的坐标。');}if(action==='layers'){config.layers=[];sync();}
      if(action==='pagePrev'||action==='pageNext'){page=Math.max(0,page+(action==='pagePrev'?-1:1));renderList();}
      const preset=()=>JSON.stringify({schema:'mythic-view-v1',sceneKey:scene.key,config},null,2);
      if(action==='save'){try{localStorage.setItem(storageKey,preset());status('视图已保存在当前浏览器。');}catch(_){status('浏览器无法保存，可导出视图文件。');}}
      if(action==='restore'){try{const data=JSON.parse(localStorage.getItem(storageKey)||'null');if(!data)throw Error('没有保存的视图');config=cleanConfig(data.config||{},duration,layers);sync();status('已恢复视图。');}catch(error){status(error.message);}}
      if(action==='export')download(preset(),'mechanic-view.json','application/json');
      if(action==='csv'){const safe=value=>'"'+(typeof value==='number'?String(value):String(value??'').replace(/^[=+@-]/,"'$&")).replaceAll('"','""')+'"';const keys=config.columns.filter(k=>k!=='points');download('\uFEFF'+[keys,...filtered.map(row=>keys.map(k=>row[k]))].map(row=>row.map(safe).join(',')).join('\r\n'),'mechanic-evidence.csv','text/csv;charset=utf-8');}
      if(action==='calibrate'){const b=Object.fromEntries([...host.querySelectorAll('[data-bound]')].map(x=>[x.dataset.bound,Number(x.value)]));if(b.maxX<=b.minX||b.maxY<=b.minY){status('边界必须满足右 > 左、上 > 下。');return;}config.calibration=b;config.projection='calibrated';slot('calibrationStatus').textContent='使用自定义校准';renderFrame();}
      if(action==='relative'){const bounds=relativeBounds();if(!bounds){status('日志没有可用坐标。');return;}config.calibration=bounds;config.projection='relative';sync();}
    });
    input('preset').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>100000)throw Error('视图文件过大');const data=JSON.parse(await file.text());if(data.schema!=='mythic-view-v1'||data.sceneKey!==scene.key)throw Error('视图版本或首领不匹配');config=cleanConfig(data.config||{},duration,layers);sync();status('已导入视图。');}catch(error){status(error.message);}finally{e.target.value='';}};
    host._workbench={destroy:stop,refreshMap:renderFrame,seek(timeMs){stop();cursor=Math.max(0,Math.min(duration,Number(timeMs)||0));selected=filtered.findLast(e=>e.timeMs<=cursor)||filtered[0];renderFrame();},playRange(from,to){stop();config.view='map';sync();cursor=Math.max(0,Math.min(duration,from));selected=filtered.findLast(e=>e.timeMs<=cursor)||filtered[0];renderFrame();play(Math.max(cursor,Math.min(duration,to)));},focusEvent(id){const event=events.find(e=>e.id===String(id));if(event){config.group=event.group;selected=event;cursor=event.timeMs;sync();}}};sync();return host._workbench;
  }
  global.MechanicWorkbench={mount,filterEvents,aggregate,cleanConfig,projectGuides,trackPosition,lifeState,avatar,patchMap,bossStatus,activeCast,castBar,escape:esc};
})(typeof window==='undefined'?globalThis:window);
