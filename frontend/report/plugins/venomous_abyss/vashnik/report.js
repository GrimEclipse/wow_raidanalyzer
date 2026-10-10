(() => {
  const state={payload:null,pulls:[],pull:0,tab:'survival'},$=id=>document.getElementById(id),esc=window.MechanicWorkbench.escape;
  const current=()=>state.pulls[state.pull]||{},mechanics=()=>current().vashnik||{};
  const person=row=>`<span class="player" style="color:${/^#[\da-f]{3,8}$/i.test(row.classColor||'')?row.classColor:'#fff'}">${esc(row.player||row.name||'未知')}</span>`,names=rows=>(rows||[]).map(person).join('、')||'—';
  const table=(headers,rows)=>`<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${v??'—'}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  function renderWaves(data){
    const rounds=data.plagueWaves?.rounds||[],explosions=data.eventScene?.totemReplay?.explosions||[];
    return `<section class="glass-panel panel"><h2>泡沫清场与漏清复核</h2>${table(['批次','痛饮 / 用途','放波时间','点名玩家','点名时图腾','已清除','剩余','结果'],rounds.map(r=>[
      `<button class="cosmic-button" data-wave-round="${r.index}">#${r.index} ↗</button>`,r.cycleIndex?`痛饮 ${r.cycleIndex}，${r.purpose||'清场'}`:'首波',esc(r.time),names(r.players),
      r.totemResult?.beforeKeys?.length??'—',r.totemResult?.clearedKeys?.length??'—',r.totemResult?.remainingKeys?.length??'—',
      r.explosionReview?.length?'<span class="badge bad">本周期恶念爆炸</span>':'—'
    ]))}<h3>恶念爆炸，${explosions.length} 次</h3>${explosions.length?table(['时间','痛饮周期','泡沫批次','关联点名玩家','未清区域'],explosions.map(r=>[
      esc(r.time),r.cycleIndex,esc(r.waveRoundIndices.join('、')),esc(r.players.join('、')),esc(r.unclearedRegion)
    ])):'<p class="hint">本场没有记录到恶念完成施法。</p>'}<p class="hint">清场统计从本批点名开始，到最后一次放波后的结果窗口结束。点名玩家供共同复核；不单凭图腾死亡时间归责个人。</p>
    <details><summary>光柱到位参考</summary><p class="hint">${esc(data.plagueWaves?.pillarRule||'')} ${esc(data.plagueWaves?.markerNote||'')}</p>${table(['批次','玩家','结果','最近已知光柱','距离'],(data.plagueWaves?.records||[]).filter(r=>r.checked).map(r=>[
      `#${r.roundIndex}`,person(r),esc(r.pillarOutcome),esc(r.nearestPillar?.name||'—'),r.distanceYards==null?'—':`${r.distanceYards} 码`
    ]))}</details></section>`;
  }
  function mountWorkspace(data,video=false){
    const scene=data.eventScene||{key:'vashnik',events:[],note:'旧报告没有逐事件坐标，重新分析可生成机制工作台。'},rounds=scene.pillarRounds||[];
    $('content').innerHTML=`<div class="field-toolbar"><label>场地范围 <select id="fieldScope"><option value="combat">作战区</option><option value="full">完整场地</option></select></label><label>点名批次 <select id="waveRound"><option value="0">跟随时间轴</option>${rounds.map(r=>`<option value="${r.index}">#${r.index}，${esc(r.time)}${r.explosionReview?.length?'，\u6076\u5ff5\u7206\u70b8':''}</option>`).join('')}</select></label><button class="cosmic-button" id="wavePlay">播放本批推波</button><button class="cosmic-button" id="waveResult">查看本批结果</button></div><div id="vashnikWorkbench"></div>`;
    const scope=$('fieldScope'),roundSelect=$('waveRound'),handle=window.MechanicWorkbench.mount($('vashnikWorkbench'),scene,scene.arenaProjection?.matrix?window.VashnikFieldAdapter(scene,scope,roundSelect,video):{});
    scope.onchange=()=>handle.refreshMap();roundSelect.onchange=()=>{const r=rounds.find(r=>r.index===Number(roundSelect.value));if(r)handle.seek(r.timeMs-1000);else handle.refreshMap();};
    const choose=()=>{const r=rounds.find(r=>r.index===Number(roundSelect.value))||rounds.findLast(r=>r.applicationTimeMs<=Number($('vashnikWorkbench').querySelector('[data-input="time"]').value))||rounds[0];if(r)roundSelect.value=String(r.index);return r;};
    $('wavePlay').onclick=()=>{const r=choose();if(r)handle.playRange(Math.min(...r.players.filter(p=>p.ending!=='death').map(p=>p.timeMs),r.timeMs)-1000,r.totemResult?.resultTimeMs??r.timeMs+8000);};
    $('waveResult').onclick=()=>{const r=choose();if(r)handle.seek(r.totemResult?.resultTimeMs??r.timeMs+8000);};
    if(state.focusEventID!=null){const r=rounds.find(r=>r.players.some(p=>p.eventID===state.focusEventID));if(r)roundSelect.value=String(r.index);handle.focusEvent(state.focusEventID);state.focusEventID=null;}
  }
  function renderContent(){const data=mechanics();if(state.tab==='explore'||state.tab==='replay'){mountWorkspace(data,state.tab==='replay');return;}
    if(state.tab==='infection')$('content').innerHTML=`<section class="glass-panel panel"><h2>感染点名与接圈证据</h2><p class="hint">${data.adaptiveInfection?.groupBasis==='observed-aura-batch'?'日志未记录旧版感染施法，按相邻光环应用汇成记录批次；批次间隔可在分析配置调整。':'以实际感染施法划分统计窗口。'} 接圈来自已确认法术命中，不直接判定失误。</p>${table(['轮次 / 批次','开始','结束','点名 / 类型','接圈记录','接圈人数'],(data.adaptiveInfection?.rounds||[]).map(r=>[`#${r.index}`,esc(r.time),esc(r.endTime),(r.infectionTargets||[]).map(p=>`${person(p)}，${esc(p.infection)}`).join('<br>'),names(r.soakers),r.soakerCount]))}</section>`;
    else if(state.tab==='waves')$('content').innerHTML=renderWaves(data);
    else if(state.tab==='avoidable')$('content').innerHTML=`<section class="glass-panel panel"><h2>波浪与场地伤害证据</h2><p class="hint">实际受击记录供复核。方向参考线不等于实测轨迹；缺少图腾交点与明确目标时，不自动判定谁把波浪引错。</p>${table(['玩家','机制','次数','伤害','发生时间'],(data.avoidable?.players||[]).map(r=>[person(r),esc(r.spellName),r.hitCount,Number(r.totalDamage||0).toLocaleString('zh-CN'),(r.events||[]).map(e=>esc(e.time)).join('、')]))}</section>`;
    else $('content').innerHTML=`<section class="glass-panel panel"><h2>死亡与战复</h2>${table(['时间','玩家','事件','原因 / 技能'],(current().survival?.timeline||[]).map(r=>[esc(r.time),person(r),r.kind==='combat_res'?'战复':'死亡',esc(r.ability||r.spellName||r.source||'未知')]))}</section>`;
    $('content').querySelectorAll('[data-wave-round]').forEach(button=>button.onclick=()=>{const round=data.plagueWaves.rounds.find(r=>r.index===Number(button.dataset.waveRound));state.focusEventID=round?.players[0]?.eventID;state.tab='replay';render();});
  }
  function render(){const pull=current();$('title').textContent=`瓦什尼克，Fight ${pull.fightID||'—'}`;$('meta').textContent=`${pull.difficultyName||''}，${pull.date||''}，${pull.duration||''}`;$('wclLink').href=pull.wclDeepLink||'#';$('stats').innerHTML=[['结果',pull.isKill?'击杀':'开荒'],['泡沫批次',mechanics().plagueWaves?.rounds?.length||0],['结束存活',`${pull.survival?.survivorCount||0}/${pull.survival?.rosterCount||0}`],['死亡',pull.survival?.deathCount||0]].map(([label,value])=>`<div class="stat"><strong>${esc(value)}</strong><span>${label}</span></div>`).join('');
    const definitions=[...(state.payload?.meta?.tabDefinitions||[{key:'survival',label:'死亡与战复'}])].sort((a,b)=>(a.key==='survival'?-2:a.key==='explore'?2:0)-(b.key==='survival'?-2:b.key==='explore'?2:0));if(state.payload?.meta?.analysisConfig?.fullReplayEnabled!==false&&!definitions.some(d=>d.key==='replay'))definitions.splice(1,0,{key:'replay',label:'场地回放'});if(!definitions.some(d=>d.key===state.tab))state.tab=definitions[0]?.key||'survival';$('tabs').innerHTML=definitions.map(d=>`<button class="cosmic-button ${d.key===state.tab?'active':''}" data-tab="${esc(d.key)}">${esc(d.label)}</button>`).join('');$('tabs').querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{state.tab=b.dataset.tab;render();});renderContent();}
  function load(payload){state.payload=payload;state.pulls=payload.data?.page1_wipeAnalysis||[];state.tab=new URLSearchParams(location.search).get('tab')||'survival';const requested=Number(new URLSearchParams(location.search).get('fight')),index=state.pulls.findIndex(r=>Number(r.fightID)===requested);state.pull=Math.max(0,index);$('pullSelect').innerHTML=state.pulls.map((p,i)=>`<option value="${i}">Fight ${p.fightID}，${esc(p.date)}，${p.isKill?'击杀':'开荒'}</option>`).join('');$('pullSelect').value=String(state.pull);render();}
  $('pullSelect').onchange=e=>{state.pull=Number(e.target.value);render();};$('fileInput').onchange=async e=>{try{load(await window.MythicReportRuntime.readLocalFile(e.target.files[0]));}catch(error){$('error').textContent=error.message;}finally{e.target.value='';}};
  const path=new URLSearchParams(location.search).get('json');if(path){$('overviewLink').href=`/frontend/report/overview.html?json=${encodeURIComponent(path)}`;window.MythicReportRuntime.loadPayload(path).then(load).catch(error=>$('error').textContent=error.message);}else $('error').textContent='请导入分析 JSON 或从报告库进入。';
})();
