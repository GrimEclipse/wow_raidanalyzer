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
    if(cursor<a[0])return null;
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
    return !lifeState(b,cursor).dead&&(b.casts||[]).findLast(c=>(['completed','interrupted'].includes(c.outcome)||c.outcome==='unconfirmed'&&c.durationMs>0)&&c.startTimeMs<=cursor&&c.endTimeMs>cursor)||null;
  }
  function castDisplay(b,cursor){
    if(lifeState(b,cursor).dead)return null;
    const active=activeCast(b,cursor),cast=active||(b.casts||[]).findLast(c=>c.outcome==='interrupted'&&c.endTimeMs<=cursor&&cursor-c.endTimeMs<(c.interruptFeedbackMs||0));
    if(!cast)return null;
    const interrupted=!active,timeMs=interrupted?cast.endTimeMs:cursor,duration=cast.durationMs||(cast.expectedEndTimeMs??cast.endTimeMs)-cast.startTimeMs;
    return {cast,interrupted,progress:Math.max(0,Math.min(1,(timeMs-cast.startTimeMs)/(duration||1))),remainingMs:Math.max(0,(cast.expectedEndTimeMs??cast.endTimeMs)-cursor)};
  }
  function castBar(b,cursor,q,width=124){
    const display=castDisplay(b,cursor);if(!display||!q)return '';
    const {cast,progress,interrupted}=display,fill=cast.phase==='channel'?1-progress:progress,color=interrupted?'#fa6b80':cast.phase==='channel'?'#78cee6':'#efbd6a';
    return `<g data-key="castbar:${b.actorID}" data-interrupted="${interrupted}" transform="translate(${q.x-width/2} ${q.y-44})" pointer-events="none"><rect width="${width}" height="19" rx="4" fill="#09111fe8" stroke="${color}" stroke-width="1"/><rect x="2" y="2" width="${(width-4)*fill}" height="15" rx="2" fill="${color}" opacity=".55"/><text x="${width/2}" y="13" text-anchor="middle" style="font:10px system-ui;fill:#fff;stroke:#09111f;stroke-width:2px;paint-order:stroke">${esc(cast.spellName||'施法')}${interrupted?' 已打断':''}</text>${interrupted&&cast.interruptIcon?`<image href="${esc(cast.interruptIcon)}" x="${width+3}" width="16" height="16"/>`:''}</g>`;
  }
  function bossStatus(replay,cursor){
    return `<div class="mw-boss-status" aria-label="首领血量与施法">${(replay?.bosses||[]).map(b=>{
      const dead=lifeState(b,cursor).dead,hp=(b.health||[]).findLast(p=>p[0]<=cursor),percent=dead?0:hp?Math.max(0,Math.min(100,hp[1]/hp[2]*100)):null;
      const display=castDisplay(b,cursor),cast=display?.cast,progress=(display?.progress||0)*100;
      const energy=(b.energy||[]).findLast(p=>p[0]<=cursor),power=b.energy?.length?`<div class="mw-energy"><span>能量 ${energy?Math.round(energy[1])+'/'+Math.round(energy[2]):'—'}</span><i style="width:${energy?Math.max(0,Math.min(100,energy[1]/energy[2]*100)):0}%"></i></div>`:'';
      return `<div class="mw-boss-card ${b.energy?.length?'mw-has-energy':''}" data-key="boss-status:${b.actorID}"><div><b>${esc(b.name)}</b><span>${percent==null?'血量未记录':percent.toFixed(1)+'%'}</span></div><div class="mw-health"><i style="width:${percent??0}%"></i></div>${power}<div class="mw-cast ${cast?'active':''}"><i style="width:${cast?.phase==='channel'?100-progress:progress}%;${display?.interrupted?'background:#fa6b80':''}"></i><span>${cast?`${cast.phase==='channel'?'引导 ':''}${esc(cast.spellName||'施法')} ${display.interrupted?'已打断':(display.remainingMs/1000).toFixed(1)+'s'}`:''}</span></div></div>`;
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
    let config=cleanConfig({},duration,layers),selected=events[0]||null,cursor=Number(selected?.timeMs||0),recordStartMs=cursor,playing=false,frame=0,scrubFrame=0,last=0,page=0,filtered=[],videoRecording=false,videoCancelled=false,videoCapture=null;
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
      <div class="mw-transport"><button data-action="play" aria-label="播放事件时间轴">播放</button><button data-action="prev">上一事件</button><button data-action="next">下一事件</button><button data-action="problem">下一问题</button><select data-input="speed" aria-label="播放速度"><option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option><option value="8">8×</option></select><output data-slot="clock"></output><button data-action="recordOpen">录制片段</button><span data-slot="recordProgress" role="status" hidden></span><button data-action="recordCancel" hidden>取消录制</button><span data-slot="count"></span></div>
      <input class="mw-scrub" data-input="time" type="range" min="0" max="${duration}" step="100" value="${cursor}" aria-label="战斗时间"><div class="mw-tracks" data-slot="tracks"></div>
      <dialog class="mw-record-dialog" data-slot="recordDialog" aria-label="录制场地片段"><div class="mw-record-head"><h3>录制场地片段</h3><button type="button" data-action="recordClose" aria-label="关闭录制对话框">关闭</button></div><p>打开对话框时会固定当前回放时间为起点。填写持续时长，最长 40 秒。MP4 采用 30 帧/秒，WebM 最高 60 帧/秒。</p><p>如需调整起点，关闭窗口并移动时间轴，再重新打开。</p><p data-slot="recordCurrent"></p><div class="mw-record-fields"><label>持续时长（秒）<input data-input="recordDuration" type="number" min=".1" max="40" step=".1" value="10"></label></div><div class="mw-video-export"><label>文件格式<select data-input="videoFormat"><option value="mp4" selected>MP4（兼容性更好）</option><option value="webm">WebM</option></select></label><label data-slot="mp4BitrateRow">MP4 码率<select data-input="mp4Bitrate"><option value="8000000" selected>高清，约 8 Mbps</option><option value="5000000">均衡，约 5 Mbps</option><option value="3000000">小文件，约 3 Mbps</option></select></label><label data-slot="webmQualityRow" hidden>WebM 画质<select data-input="videoQuality"><option value="native" selected>原始画质，最高 60 帧/秒，约 8 Mbps</option><option value="720-60">1280×720，60 帧/秒，约 5 Mbps</option><option value="1080-60">1920×1080，60 帧/秒，约 8 Mbps</option><option value="1080-30">1920×1080，30 帧/秒，约 5 Mbps</option><option value="720-30">1280×720，30 帧/秒，约 3 Mbps</option></select></label><button type="button" data-action="videoRecord">开始录制</button><small>浏览器会询问共享内容，请选择当前标签页。录制期间可在其他窗口或应用中工作。请勿最小化录制窗口，也不要在录制窗口切换标签页。按 Esc 可取消。</small></div><p data-slot="recordStatus" role="status">录制时会在此显示进度。</p></dialog>
      <div class="mw-views"><label>地图缩放<select data-config="zoom"><option value="1">1×</option><option value="1.5">1.5×</option><option value="2">2×</option><option value="3">3×</option></select></label><button data-action="focus">定位选中事件</button><button data-view="map">场地快照</button><button data-view="matrix">自定义矩阵</button><button data-view="table">证据表</button></div>
      <div class="mw-matrix-options" data-slot="matrixOptions" hidden><label>行<select data-config="rowKey">${fieldOptions}</select></label><label>列<select data-config="colKey">${fieldOptions}</select></label><label>数值<select data-config="metric"><option value="count">事件次数</option><option value="amount">伤害总量</option><option value="problems">标记问题数</option><option value="maxStack">最高光环层数</option></select></label></div>
      <div class="mw-layout"><section data-slot="stage" class="mw-stage"></section><aside data-slot="detail" class="mw-detail"></aside></div>
      <details class="mw-calibration" ${adapter.renderMap||adapter.project?'hidden':''}><summary>场地坐标校准</summary><p>输入与图片边界对应的 WCL 坐标。相对坐标视图展示事件间的位置关系；手动边界校准仅适用于图片与坐标轴同向的场地。</p>${['minX','maxX','minY','maxY'].map((k,i)=>`<label>${['左 X','右 X','下 Y','上 Y'][i]}<input type="number" data-bound="${k}" step="any"></label>`).join('')}<button data-action="calibrate">应用校准</button><button data-action="relative">相对坐标示意</button><span data-slot="calibrationStatus"></span></details>
      <details class="mw-columns"><summary>自定义证据表列</summary>${Object.entries(columns).map(([key,label])=>`<label><input type="checkbox" data-column="${key}" ${defaultColumns.includes(key)?'checked':''}>${label}</label>`).join('')}</details><div class="mw-evidence" data-slot="list"></div><div class="mw-pages"><button data-action="pagePrev">前页</button><span data-slot="page"></span><button data-action="pageNext">后页</button></div><div class="mw-status" data-slot="status" role="status"></div>`;
    const slot=name=>host.querySelector(`[data-slot="${name}"]`),input=name=>host.querySelector(`[data-input="${name}"]`);
    const status=value=>slot('status').textContent=value;
    const webmMimes=['video/webm;codecs=vp8','video/webm;codecs=vp9','video/webm'];
    const supportedWebmMime=()=>global.MediaRecorder?.isTypeSupported&&webmMimes.find(type=>MediaRecorder.isTypeSupported(type));
    const canRecordMp4=Boolean(global.VideoEncoder&&global.MediaStreamTrackProcessor);
    if(!canRecordMp4){input('videoFormat').querySelector('[value="mp4"]').disabled=true;input('videoFormat').value='webm';slot('recordStatus').textContent='当前浏览器不支持 MP4 视频编码，请使用 WebM。';}
    function syncRecordingFormat(){const mp4=input('videoFormat').value==='mp4';slot('mp4BitrateRow').hidden=!mp4;slot('webmQualityRow').hidden=mp4;}
    syncRecordingFormat();
    function download(value,name,type){const url=URL.createObjectURL(new Blob([value],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    async function recordSelectionVideo(){
      if(videoRecording)return;
      const message=slot('recordStatus'),progress=slot('recordProgress'),cancel=host.querySelector('[data-action="recordCancel"]');
      const from=recordStartMs,seconds=Number(input('recordDuration').value),to=from+seconds*1000;
      if(!input('recordDuration').value||!Number.isFinite(seconds)||seconds<.1||seconds>40){message.textContent='请填写 0.1 到 40 秒的持续时长。';return;}
      if(from<0||from>=duration||to>duration){message.textContent='所选时长超出战斗结束时间，请缩短录制时长。';return;}
      if(!navigator.mediaDevices?.getDisplayMedia){message.textContent='当前浏览器不支持标签页录制，请使用较新的 Chrome 或 Edge。';return;}
      const format=input('videoFormat').value,mime=format==='webm'?supportedWebmMime():null;
      if(format==='mp4'&&!canRecordMp4||format==='webm'&&!mime){message.textContent=`当前浏览器不支持录制 ${format.toUpperCase()}。`;return;}
      const previous={cursor,selected,view:config.view,speed:input('speed').value};
      const quality=format==='mp4'?'native':input('videoQuality').value,option=format==='mp4'?{fps:30,bitrate:Number(input('mp4Bitrate').value)}:{native:{fps:60,bitrate:8000000},'720-60':{width:1280,height:720,fps:60,bitrate:5000000},'1080-60':{width:1920,height:1080,fps:60,bitrate:8000000},'1080-30':{width:1920,height:1080,fps:30,bitrate:5000000},'720-30':{width:1280,height:720,fps:30,bitrate:3000000}}[quality];
      let source=null,output=null,video=null,drawFrame=0,recorder=null,mp4Output=null,mp4Source=null,mp4Finalized=false,encodingError=null,encodedFrames=0;
      videoRecording=true;videoCancelled=false;
      try{
        // Keep this call in the click gesture; browsers reject a delayed screen-share request.
        source=await navigator.mediaDevices.getDisplayMedia({video:{frameRate:option.fps},audio:false,preferCurrentTab:true,selfBrowserSurface:'include'});
        videoCapture=source;
        const track=source.getVideoTracks()[0];
        if(track?.getSettings().displaySurface&&track.getSettings().displaySurface!=='browser')throw Error('请在浏览器提示中选择当前标签页。');
        track.addEventListener('ended',()=>{videoCancelled=true;stop();},{once:true});
        slot('recordDialog').close();
        stop();config.view='map';render();input('speed').value='1';
        const field=slot('stage').querySelector('.field-map,.replay-map,.mw-map,.brood-map,[data-replay-field]');
        if(!field)throw Error('没有可录制的场地图。');
        field.scrollIntoView({block:'center',inline:'center'});
        await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
        const rect=field.getBoundingClientRect();
        if(format==='mp4'){
          host.style.setProperty('--mw-record-ratio',String(rect.width/rect.height));host.classList.add('mw-record-capture');
          await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
          output=source;
        }else{
          if(rect.left<0||rect.top<0||rect.right>innerWidth||rect.bottom>innerHeight)throw Error('场地图没有完整显示。请缩小页面比例后重试。');
          let cropped=false;
          if(quality==='native'&&global.CropTarget?.fromElement&&typeof track.cropTo==='function'){
            try{await track.cropTo(await global.CropTarget.fromElement(field));cropped=true;}catch(_){/* Fall back to canvas cropping. */}
          }
          if(cropped)output=source;
          else{
          video=document.createElement('video');video.muted=true;video.playsInline=true;video.srcObject=source;
          await new Promise((resolve,reject)=>{video.onloadedmetadata=resolve;video.onerror=()=>reject(Error('无法读取标签页画面。'));});
          await video.play();
          const canvas=document.createElement('canvas'),scaleX=video.videoWidth/innerWidth,scaleY=video.videoHeight/innerHeight;
          canvas.width=option.width||Math.min(1920,2*Math.max(1,Math.round(rect.width*scaleX/2)));
          canvas.height=option.height||2*Math.max(1,Math.round(canvas.width*rect.height/rect.width/2));
          const ctx=canvas.getContext('2d',{alpha:false});
          const draw=()=>{if(!videoRecording||videoCancelled)return;ctx.drawImage(video,rect.left*scaleX,rect.top*scaleY,rect.width*scaleX,rect.height*scaleY,0,0,canvas.width,canvas.height);drawFrame=requestAnimationFrame(draw);};
          draw();output=canvas.captureStream(option.fps);
          }
        }
        cursor=from;selected=filtered.findLast(e=>e.timeMs<=cursor)||null;renderFrame();
        let chunks=[],finished=null;
        if(format==='mp4'){
          const {Output,Mp4OutputFormat,BufferTarget,MediaStreamVideoTrackSource,Quality}=await import('/assets/vendor/mediabunny-1.65.0.min.mjs');
          mp4Output=new Output({format:new Mp4OutputFormat(),target:new BufferTarget()});
          mp4Source=new MediaStreamVideoTrackSource(output.getVideoTracks()[0],{codec:'avc',quality:new Quality({bitrate:option.bitrate}),keyFrameInterval:2,onEncodedPacket:()=>{encodedFrames++;}});
          mp4Source.errorPromise.catch(error=>{encodingError=error;stop();});
          mp4Output.addVideoTrack(mp4Source);await mp4Output.start();
        }else{
          recorder=new MediaRecorder(output,{mimeType:mime,videoBitsPerSecond:option.bitrate});
          finished=new Promise((resolve,reject)=>{recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};recorder.onstop=resolve;recorder.onerror=e=>reject(e.error||Error('视频编码失败。'));});
        }
        progress.hidden=false;cancel.hidden=false;if(recorder)recorder.start(1000);play(to);
        while(playing&&!videoCancelled){progress.textContent=`录制中 ${Math.max(0,(cursor-from)/1000).toFixed(1)} / ${((to-from)/1000).toFixed(1)} 秒`;await new Promise(resolve=>setTimeout(resolve,150));}
        stop();let blob;
        if(mp4Output){progress.textContent='正在完成 MP4 文件…';mp4Source.close();await mp4Output.finalize();mp4Finalized=true;if(encodingError)throw encodingError;if(!encodedFrames)throw Error('标签页未产生可录制画面，请保持当前标签页可见后重试。');blob=new Blob([mp4Output.target.buffer],{type:'video/mp4'});}
        else{if(recorder.state!=='inactive')recorder.stop();await finished;blob=new Blob(chunks,{type:recorder.mimeType||mime});}
        if(videoCancelled)throw Error('已取消录制。');
        const extension=format;if(!blob.size)throw Error('录制结果为空，请重试。');
        const url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;
        anchor.download=`${String(scene.key).replace(/[^\w-]/g,'_')}_${Number((from/1000).toFixed(1))}-${Number((to/1000).toFixed(1))}s.${extension}`;
        anchor.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
        message.textContent=`${extension.toUpperCase()} 已保存，${(blob.size/1048576).toFixed(1)} MiB。`;
      }catch(error){message.textContent=error.name==='NotAllowedError'?'已取消标签页共享。':error.message||'录制失败。';}
      finally{
        if(mp4Output&&!mp4Finalized)Promise.resolve(mp4Output.cancel()).catch(()=>{});
        host.classList.remove('mw-record-capture');host.style.removeProperty('--mw-record-ratio');
        stop();cancelAnimationFrame(drawFrame);output?.getTracks().forEach(track=>track.stop());source?.getTracks().forEach(track=>track.stop());
        if(video)video.srcObject=null;videoCapture=null;videoRecording=false;videoCancelled=false;progress.hidden=true;cancel.hidden=true;
        cursor=previous.cursor;selected=previous.selected;config.view=previous.view;input('speed').value=previous.speed;render();
        if(host.isConnected&&!slot('recordDialog').open)slot('recordDialog').showModal();
      }
    }
    function cancelRecording(){videoCancelled=true;stop();videoCapture?.getTracks().forEach(track=>track.stop());}
    function onRecordingKeydown(e){if(e.key==='Escape'&&videoRecording){e.preventDefault();cancelRecording();}}
    global.addEventListener('keydown',onRecordingKeydown);
    const playbackState=()=>({playing,timeMs:cursor,durationMs:duration,rate:Number(input('speed').value)});
    function stop(){playing=false;cancelAnimationFrame(frame);host.querySelector('[data-action="play"]').textContent='播放';adapter.onPlaybackState?.(playbackState());}
    function play(until=config.to){if(!filtered.length&&!scene.combatReplay)return;playing=true;last=performance.now();host.querySelector('[data-action="play"]').textContent='暂停';adapter.onPlaybackState?.(playbackState());const end=Math.min(duration,until),tick=now=>{if(!host.isConnected){stop();return;}cursor=Math.min(end,cursor+(now-last)*Number(input('speed').value));last=now;selected=filtered.findLast(x=>x.timeMs<=cursor)||null;renderFrame();if(cursor>=end)stop();else frame=requestAnimationFrame(tick);};frame=requestAnimationFrame(tick);}
    function select(e){stop();selected=e||null;cursor=Number(e?.timeMs??cursor);renderFrame();renderList();}
    function project(point){if(adapter.project)return adapter.project(point);const b=config.calibration;if(!b||b.maxX<=b.minX||b.maxY<=b.minY)return null;return {x:100*(point.x-b.minX)/(b.maxX-b.minX),y:100*(b.maxY-point.y)/(b.maxY-b.minY)};}
    function map(){if(adapter.renderMap)return adapter.renderMap(selected,filtered,cursor,config)||'<p>当前没有可绘制的快照。</p>';
      const nearby=filtered.filter(e=>e.timeMs<=cursor&&cursor-e.timeMs<=config.windowMs);
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
      adapter.onFrame?.(playbackState());
    }
    function renderList(){const pages=Math.max(1,Math.ceil(filtered.length/100));page=Math.min(page,pages-1);slot('page').textContent=`${page+1} / ${pages}`;
      const rows=filtered.slice(page*100,page*100+100),cell=(e,k)=>k==='timeMs'?`<button data-event="${esc(e.id)}">${time(e.timeMs)}</button>`:k==='points'?((e.points||[]).some(p=>p.position)?(e.points.some(p=>p.position?.sampleOffsetMs!=null)?'相邻快照':'事件坐标'):'缺失 / 未提供'):esc(e[k]??'—');slot('list').innerHTML=`<div class="mw-table-wrap"><table><thead><tr>${config.columns.map(k=>`<th>${columns[k]}</th>`).join('')}</tr></thead><tbody>${rows.map(e=>`<tr data-event="${esc(e.id)}" class="${selected?.id===e.id?'mw-selected':''}">${config.columns.map(k=>`<td>${cell(e,k)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    }
    function render(){stop();filtered=filterEvents(events,config);if(!filtered.includes(selected)){selected=filtered.findLast(e=>e.timeMs<=cursor)||null;}page=0;
      slot('count').textContent=`${filtered.length} / ${events.length} 条事件`;slot('tracks').innerHTML=layers.filter(l=>filtered.some(e=>e.layer===l)).map(l=>`<div class="mw-track"><span>${esc(l)}</span><div>${filtered.filter(e=>e.layer===l).map(e=>`<button class="${e.problem?'mw-bad':''}" data-event="${esc(e.id)}" style="left:${100*e.timeMs/duration}%" title="${esc(time(e.timeMs)+' '+e.label+' '+(e.actor||''))}" aria-label="${esc(time(e.timeMs)+' '+e.label)}"></button>`).join('')}</div></div>`).join('');
      host.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===config.view));slot('matrixOptions').hidden=config.view!=='matrix';slot('stage').hidden=config.view==='table';slot('detail').hidden=config.view!=='map';slot('stage').classList.toggle('mw-map-stage',config.view==='map');if(config.view==='matrix')slot('stage').innerHTML=matrix();renderFrame();renderList();
    }
    function sync(){host.querySelectorAll('[data-column]').forEach(e=>e.checked=config.columns.includes(e.dataset.column));slot('calibrationStatus').textContent=config.projection==='relative'?'相对坐标示意 · 与场地图未标定':config.calibration?'使用自定义校准':'';host.querySelectorAll('[data-config]').forEach(e=>{const k=e.dataset.config;if(e.type==='checkbox')e.checked=config[k];else e.value=['from','to','windowMs'].includes(k)?config[k]/1000:config[k];});host.querySelectorAll('[data-layer]').forEach(e=>e.checked=!config.layers.length||config.layers.includes(e.dataset.layer));if(config.calibration)host.querySelectorAll('[data-bound]').forEach(e=>e.value=config.calibration[e.dataset.bound]);render();}
    slot('recordDialog').addEventListener('cancel',e=>{if(videoRecording)e.preventDefault();});
    host.addEventListener('change',e=>{if(videoRecording)return;if(e.target===input('videoFormat'))syncRecordingFormat();if(e.target===input('time')){if(scrubFrame){cancelAnimationFrame(scrubFrame);scrubFrame=0;}cursor=Number(e.target.value);selected=filtered.findLast(x=>x.timeMs<=cursor)||null;renderFrame();}if(e.target.dataset.column){const selectedColumns=[...host.querySelectorAll('[data-column]:checked')].map(x=>x.dataset.column);if(selectedColumns.length){config.columns=selectedColumns;renderList();}else{e.target.checked=true;status('至少保留一列。');}}if(e.target===input('deathCutoff')){config.to=e.target.value?Number(e.target.value):duration;sync();}if(e.target.dataset.config){const k=e.target.dataset.config;config[k]=e.target.type==='checkbox'?e.target.checked:['from','to','windowMs'].includes(k)?Number(e.target.value)*1000:e.target.value;config=cleanConfig(config,duration,layers);render();}
      if(e.target.dataset.layer){const checked=[...host.querySelectorAll('[data-layer]:checked')].map(x=>x.dataset.layer);config.layers=checked.length?checked:['__none__'];render();}});
    host.addEventListener('pointerdown',e=>{if(e.target===input('time')&&playing)stop();});
    host.addEventListener('input',e=>{if(videoRecording)return;if(e.target.dataset.config==='query'){config.query=e.target.value;render();}if(e.target===input('time')){if(playing)stop();cursor=Number(e.target.value);selected=filtered.findLast(x=>x.timeMs<=cursor)||null;slot('clock').textContent=time(cursor);if(!scrubFrame)scrubFrame=requestAnimationFrame(()=>{scrubFrame=0;if(host.isConnected)renderFrame();});}});
    host.addEventListener('click',e=>{if(videoRecording&&e.target.closest('[data-action]')?.dataset.action!=='recordCancel')return;const eventNode=e.target.closest('[data-event]');if(eventNode){select(filtered.find(x=>String(x.id)===eventNode.dataset.event));return;}
      const view=e.target.closest('[data-view]');if(view){config.view=view.dataset.view;render();return;}const action=e.target.closest('[data-action]')?.dataset.action;
      if(action==='recordOpen'){stop();recordStartMs=cursor;const remaining=Math.floor(Math.min(40,Math.max(0,(duration-recordStartMs)/1000))*10)/10;slot('recordCurrent').textContent=`录制起点：${time(recordStartMs)}。剩余最多 ${remaining.toFixed(1)} 秒。`;input('recordDuration').max=String(remaining);if(Number(input('recordDuration').value)>remaining)input('recordDuration').value=remaining.toFixed(1);slot('recordDialog').showModal();return;}
      if(action==='recordClose'){slot('recordDialog').close();return;}
      if(action==='videoRecord'){void recordSelectionVideo();return;}
      if(action==='recordCancel'){cancelRecording();return;}
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
    host._workbench={destroy(){global.removeEventListener('keydown',onRecordingKeydown);cancelRecording();cancelAnimationFrame(scrubFrame);adapter.onDestroy?.();},refreshMap:renderFrame,seek(timeMs){stop();cursor=Math.max(0,Math.min(duration,Number(timeMs)||0));selected=filtered.findLast(e=>e.timeMs<=cursor)||null;renderFrame();},playRange(from,to){stop();config.view='map';sync();cursor=Math.max(0,Math.min(duration,from));selected=filtered.findLast(e=>e.timeMs<=cursor)||null;renderFrame();play(Math.max(cursor,Math.min(duration,to)));},focusEvent(id){const event=events.find(e=>e.id===String(id));if(event){config.group=event.group;selected=event;cursor=event.timeMs;sync();}}};sync();return host._workbench;
  }
  global.MechanicWorkbench={mount,filterEvents,aggregate,cleanConfig,projectGuides,trackPosition,lifeState,avatar,patchMap,bossStatus,activeCast,castDisplay,castBar,escape:esc};
})(typeof window==='undefined'?globalThis:window);
