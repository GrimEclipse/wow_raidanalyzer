(() => {
  const state={payload:null,pulls:[],pull:0,tab:"survival",sourcePath:""};
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const num=value=>Number(value||0).toLocaleString("zh-CN");
  const current=()=>state.pulls[state.pull]||null;
  const mechanics=()=>current()?.nymrissa_wavecaller||{};
  const player=row=>`<span class="player" style="color:${esc(row?.classColor||'#fff')}">${esc(row?.player||row?.name||'—')}</span>`;
  const players=rows=>(rows||[]).map(player).join("、")||"—";
  const spell=(id,name)=>{const spellID=Number(id||0),label=name||(spellID?`法术 ${spellID}`:"—");return !spellID||[1,3,4,5,6,7,8].includes(spellID)?esc(label):`<a class="spell" href="https://www.wowhead.com/cn/spell=${spellID}" data-wowhead="domain=cn&amp;spell=${spellID}" target="_blank" rel="noreferrer">${esc(label)}</a>`;};
  const badge=(kind,text)=>`<span class="badge ${kind}">${esc(text)}</span>`;
  function table(headers,rows){return rows?.length?`<div class="table-wrap"><table><thead><tr>${headers.map(item=>`<th>${esc(item)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell??'—'}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`:'<div class="empty">这场战斗没有对应记录。</div>'}
  function renderStats(){
    const pull=current(),survival=pull?.survival||{},checks=mechanics().checks||{},rainTouches=mechanics().rainOrbTouches||{};
    $("title").textContent=`尼姆瑞莎·唤潮者，Fight ${pull?.fightID||'—'}`;
    $("meta").textContent=`${pull?.difficultyName||'未知难度'}，${pull?.isKill?'击杀':`Boss 剩余 ${Number(pull?.bossPercentage||0).toFixed(2)}%`}，${pull?.date||''} ${pull?.startClock||''}`;
    $("wclLink").href=pull?.wclDeepLink||"#";
    const items=[
      ["战斗时长",pull?.duration||"—"],
      ["结果",pull?.isKill?"KILL":`${Number(pull?.bossPercentage||0).toFixed(2)}%`],
      ["雨中踩球",rainTouches.count??checks.rainTouchCount??0],
      ["激荡漩涡中招",checks.surgeHitPlayers??0],
      ["超时自爆",checks.timeoutBursts??0],
      ["阵亡",survival.deathCount||0],
    ];
    $("stats").innerHTML=items.map(([label,value])=>`<div class="stat"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join("");
  }
  function renderTabs(){const definitions=state.payload?.meta?.tabDefinitions||[{key:"survival",label:"死亡与战复"}];if(!definitions.some(row=>row.key===state.tab))state.tab=definitions[0].key;$("tabs").innerHTML=definitions.map(row=>`<button class="cosmic-button ${row.key===state.tab?'active':''}" data-tab="${esc(row.key)}">${esc(row.label)}</button>`).join("");document.querySelectorAll("[data-tab]").forEach(button=>button.onclick=()=>{state.tab=button.dataset.tab;renderTabs();renderContent()})}
  function renderSurvival(){const data=current()?.survival||{};return`<section class="glass-panel panel"><h2>死亡与战复时间线</h2><p class="hint">按时间排列实际死亡和战复记录。死亡技能可悬停查看 Wowhead 说明。</p>${table(["时间","事件","玩家","原因 / 技能"],(data.timeline||[]).map(row=>[esc(row.time),row.kind==='combat_res'?'<span class="badge good">战复</span>':'<span class="badge bad">死亡</span>',player(row),row.kind==='combat_res'?`${esc(row.source)} 使用 ${spell(row.abilityID,row.ability)}`:row.deathCause==='fall'?'跌落':spell(row.abilityID,row.ability)]))}</section>`}
  function renderRain(){const data=mechanics().abyssalRain||{};const channelSec=((data.channelMs||4000)/1000).toFixed(0);return`<section class="glass-panel panel"><h2>${spell(1260837,'深渊之雨')}</h2><p class="hint">${esc(data.note||`正读条结束后引导约 ${channelSec} 秒；下列按引导窗统计承伤。`)}</p>${table(["轮次","读条完成","引导结束","命中次数","总伤害"],(data.rounds||[]).map(row=>[`#${row.index}`,esc(row.time),esc(row.channelEndTime||'—'),num(row.hitCount),num(row.totalDamage)]))}</section><section class="glass-panel panel"><h2>${spell(1277386,'浸湿')}最高层数</h2><p class="hint">浸湿会随战斗推进叠加，可用于解释后续团队伤害为什么越来越高。</p>${table(["玩家","最高层数","最后记录"],(data.drenched||[]).map(row=>[player(row),`<span class="badge">${row.maxStack} 层</span>`,esc(row.lastTime)]))}</section>`}
  function outcomeBadge(row){
    if(row.timedOut)return badge("warn","超时自爆");
    if(row.triggerUnderAbyssalRain)return badge("bad","雨中踩球触发");
    return badge("good","踩球触发");
  }
  function touchBadge(row){
    if(row.underAbyssalRain)return badge("bad","深渊之雨引导期间踩球");
    if(row.role==="tank")return badge("good","坦克踩球");
    if(row.role==="unknown"||!row.role)return badge("","踩球");
    return badge("warn","非坦克踩球");
  }
  function renderRainOrbTouches(){
    const data=mechanics().rainOrbTouches||{};
    const rows=data.players||mechanics().orbReview?.rainTouches||[];
    return `<section class="glass-panel panel alert"><h2>深渊之雨引导期间踩球</h2>
      <p class="hint">${esc(data.note||FROST_HINT())} 共 ${num(rows.length)} 次。</p>
      ${table(["时间","玩家","角色"],rows.map(row=>[esc(row.time),player(row),row.role==='tank'?'坦克':row.role==='unknown'||!row.role?'未知':'非坦克']))}
    </section>`;
  }
  function FROST_HINT(){return mechanics().frostBarrage?.policy?.rainTouchRule||'深渊之雨 DoT 持续期间踩球，高概率连带减员。'}
  function renderFrost(){
    const data=mechanics().frostBarrage||{};
    const review=mechanics().orbReview||data.orbReview||{};
    const policy=data.policy||review.policy||{};
    const rounds=data.rounds||[];
    const touches=review.touches||[];
    const bursts=review.bursts||[];
    return `
      ${renderRainOrbTouches()}
      <section class="glass-panel panel"><h2>冰霜与冰球轮次</h2>
        <p class="hint">${esc(policy.handlerRule||'')} ${esc(policy.evidenceRule||'')}</p>
        ${table(["轮次","时间","施法","被点名","踩球","雨中踩球","踩球触发","超时自爆","爆发命中 / 伤害"],rounds.map(row=>[`#${row.index}`,esc(row.time),spell(row.spellID||1257614,row.spellName||'冰霜弹幕'),players(row.targets),num((row.touches||[]).length||row.orbHitCount||0),Number(row.rainTouchCount||0)?badge("bad",String(row.rainTouchCount)):"0",num(row.touchBurstCount||0),Number(row.timeoutBurstCount||0)?badge("warn",String(row.timeoutBurstCount)):"0",`${num(row.burstHitCount)} / ${num(row.burstDamage)}`]))}
      </section>
      <section class="glass-panel panel"><h2>踩球接触</h2>
        <p class="hint">Frost Orb 光环首次应用 = 踩球，不是 DoT 跳伤。</p>
        ${table(["时间","玩家","角色","结算"],touches.map(row=>[esc(row.time),player(row),row.role==='tank'?'坦克':row.role==='unknown'||!row.role?'未知':'非坦克',touchBadge(row)]))}
      </section>
      <section class="glass-panel panel"><h2>冰球结算：踩球触发 vs 超时自爆</h2>
        <p class="hint">${esc(review.note||'')}</p>
        ${table(["#","时间","结果","触发玩家","命中","伤害"],bursts.map(row=>[`#${row.index||''}`,esc(row.time),outcomeBadge(row),row.triggered?`${player({player:row.triggerPlayer,classColor:row.triggerClassColor})}${row.triggerUnderAbyssalRain?` ${badge("bad","雨中")}`:''}`:badge("warn","场地球自动爆炸"),num(row.hitCount),num(row.totalDamage)]))}
      </section>`;
  }
  function renderSurgingVortex(){
    const data=mechanics().surgingVortex||{};
    const rounds=data.rounds||[];
    return `<section class="glass-panel panel alert"><h2>${spell(1258673,'激荡漩涡')} · 八向涌入</h2>
      <p class="hint">${esc(data.note||'场外预兆→读条完成约 3 秒涌到中心→随后嘭！。八向只有一个安全点。')}</p>
      ${table(["轮次","预兆","读条完成","涌入中心","安全方向","中招","中招玩家"],rounds.map(row=>[`#${row.index}`,esc(row.time),esc(row.castEndTime||'—'),esc(row.arrivalTime||'—'),row.safeDirection?badge("good",row.safeDirection):'—',row.playerCount?badge("bad",String(row.playerCount)):badge("good","0"),(row.players||[]).map(p=>`${player(p)}${p.direction?`（${esc(p.direction)}）`:''}`).join("、")||'—']))}
      <h3>玩家汇总</h3>
      ${table(["玩家","命中","总伤害","时间"],(data.players||[]).map(row=>[player(row),num(row.hitCount),num(row.totalDamage),(row.times||[]).map(esc).join("、")]))}
    </section>`;
  }
  function renderMurlocs(){
    const data=mechanics().murlocs||{};
    const rounds=data.rounds||[];
    return `<section class="glass-panel panel"><h2>大鱼人（泡鳍霜鳞）</h2>
      <p class="hint">${esc(data.note||'大鱼人会给附近减伤，应优先处理。场地推演不再绘制小鱼人。')}</p>
      ${table(["轮次","时间","大鱼人","击杀"],rounds.map(row=>[`#${row.index}`,esc(row.time),num(row.bigCount),num(row.killedBig)]))}
    </section>`;
  }
  function renderTransition(){
    const rows=mechanics().transitions||[];
    const bubbles=mechanics().alluringBubbles||mechanics().fieldReplay?.bubbles||[];
    return `${renderSurgingVortex()}${renderMurlocs()}
      <section class="glass-panel panel"><h2>${spell(1284015,'诱人水泡')} → ${spell(1258150,'嘭！')}</h2>
        <p class="hint">诱人水泡固定出现在场地中心约 10 码，直到嘭！。不跟 Boss 瞬时坐标。</p>
        ${table(["轮次","水泡开始","嘭！","时长"],bubbles.map(row=>[`#${row.index}`,esc(row.time),row.popTime?esc(row.popTime):'—',row.popTimeMs!=null?`${((row.popTimeMs-row.startTimeMs)/1000).toFixed(1)}s`:esc(row.endTime)]))}
      </section>
      <section class="glass-panel panel"><h2>鱼人转场压力</h2>
        <p class="hint">鱼人波次与脉动潮汐伤害用来定位转火慢；不把缺失的击杀归属算到个人。</p>
        ${table(["轮次","开始时间","鱼人波次","脉动命中","脉动伤害"],rows.map(row=>[`#${row.index}`,esc(row.time),num(row.addWaveCount),row.pulsingHitCount?`<span class="badge bad">${num(row.pulsingHitCount)}</span>`:'<span class="badge good">0</span>',num(row.pulsingDamage)]))}
      </section>`;
  }
  function damageTable(rows){return table(["玩家","技能","次数","总伤害","时间"],(rows||[]).map(row=>[player(row),spell(row.spellID,row.spellName),row.hitCount,num(row.totalDamage),(row.events||[]).map(event=>esc(event.time)).join("、")]))}
  function renderPressure(){const data=mechanics(),enrage=data.enrage||{};return`${enrage.triggered?`<section class="glass-panel panel alert"><h2>已进入 ${spell(1295086,'无尽潮汐')}</h2><p class="hint">首次记录：${esc(enrage.time)}。</p></section>`:`<section class="glass-panel panel ok"><h2>未记录无尽潮汐</h2><p class="hint">本场没有进入已知硬狂暴施法。</p></section>`}<section class="glass-panel panel"><h2>场地伤害记录</h2>${damageTable(data.hazardHits)}</section><section class="glass-panel panel"><h2>对坦压力</h2>${damageTable(data.tankPressure)}</section>`}
  function renderReplay(){
    const data=mechanics();
    setTimeout(()=>{
      if(state.tab!=='replay')return;
      const host=$('nymrissaReplay');
      if(!host)return;
      if(window.NymrissaReplay?.mount) window.NymrissaReplay.mount(host,data,current()?.durationMs);
      else host.innerHTML='<div class="empty">场地推演脚本未加载。</div>';
    },0);
    return `<section class="glass-panel panel"><h2>场地推演</h2>
      <p class="hint">${esc(data.fieldReplay?.note||'诱人水泡期间中央约 10 码水泡圈，持续到嘭！。可跳到激荡漩涡与雨中踩球节点。')}</p>
      <div id="nymrissaReplay"></div>
    </section>
    ${renderRainOrbTouches()}
    ${renderSurgingVortex()}`;
  }
  function renderContent(){
    const renderers={survival:renderSurvival,replay:renderReplay,rain:renderRain,frost:renderFrost,transition:renderTransition,pressure:renderPressure};
    $("content").innerHTML=(renderers[state.tab]||renderSurvival)();
  }
  function render(){renderStats();renderTabs();renderContent()}
  function load(payload){state.payload=payload;state.pulls=[...(payload.data?.page1_wipeAnalysis||[])].sort((left,right)=>String(right.startTimeIso||"").localeCompare(String(left.startTimeIso||"")));const requested=Number(new URLSearchParams(location.search).get("fight"));const index=state.pulls.findIndex(row=>Number(row.fightID)===requested);state.pull=index>=0?index:0;state.tab=new URLSearchParams(location.search).get("tab")||(payload.meta?.tabDefinitions||[])[0]?.key||"survival";$("pullSelect").innerHTML=state.pulls.map((row,index)=>`<option value="${index}">Fight ${row.fightID}，${esc(row.date||'')} ${esc(row.startClock||'')}，${row.isKill?'KILL':`${Number(row.bossPercentage||0).toFixed(2)}%`}</option>`).join("");$("pullSelect").value=String(state.pull);$("error").textContent=state.pulls.length?'':'分析结果中没有尼姆瑞莎战斗。';render()}
  $("pullSelect").onchange=event=>{state.pull=Number(event.target.value);state.tab=(state.payload?.meta?.tabDefinitions||[])[0]?.key||"survival";render()};
  $("fileInput").onchange=async event=>{try{load(await window.MythicReportRuntime.readLocalFile(event.target.files[0]))}catch(error){$("error").textContent=`无法载入：${error.message}`}finally{event.target.value=""}};
  const path=new URLSearchParams(location.search).get("json");state.sourcePath=path||"";if(path)$("overviewLink").href=`/frontend/report/overview.html?json=${encodeURIComponent(path)}`;if(path)window.MythicReportRuntime.loadPayload(path).then(load).catch(error=>$("error").textContent=error.message);else $("error").textContent="请从全场概览进入，或导入分析 JSON。";
})();
