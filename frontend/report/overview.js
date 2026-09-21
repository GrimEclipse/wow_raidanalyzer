const metricSummaryViews={};
const metricPlayerFilters={};
const state={payload:null,descriptor:null,pulls:[],filter:"all",difficulty:"all",separate:true,sortAsc:true,sourcePath:"",view:"pulls"};
const $=id=>document.getElementById(id);const esc=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const safeColor=value=>/^#[0-9a-f]{6}$/i.test(String(value||""))?String(value):"#e5e7eb";
function pullsOf(payload){const value=payload?.data?.page1_wipeAnalysis;if(Array.isArray(value))return value;if(value&&typeof value==="object")return[value];return Array.isArray(payload?.data?.nakzaliPulls)?payload.data.nakzaliPulls:[]}
function difficultyKey(pull){return pull.difficultyKey||({3:"normal",4:"heroic",5:"mythic"}[Number(pull.difficulty)]||"unknown")}
function difficultyName(pull){return pull.difficultyName||({3:"普通",4:"英雄",5:"史诗"}[Number(pull.difficulty)]||"未知难度")}
function orderedRows(){return state.pulls.map((pull,index)=>({pull,index})).filter(row=>(state.filter!=="wipes"||!row.pull.isKill)&&(state.difficulty==="all"||difficultyKey(row.pull)===state.difficulty)).sort((a,b)=>String(a.pull.startTimeIso||`${a.pull.date}-${a.pull.fightID}`).localeCompare(String(b.pull.startTimeIso||`${b.pull.date}-${b.pull.fightID}`))*(state.sortAsc?1:-1))}
function phaseKey(pull){return pull.isKill?"击杀":pull.wipePhase||pull.fightPhase||"未分类"}function phaseRank(key){if(key.includes("击杀"))return-1;if(/P1|阶段一|一阶段|第一/i.test(key))return 10;if(/转场|间歇|仪式|静滞/i.test(key))return 20;if(/P2|阶段二|二阶段|第二/i.test(key))return 30;if(/P3|阶段三|三阶段|第三/i.test(key))return 40;if(/狂暴|最终/i.test(key))return 90;return 50}
function pullPhaseRank(pull){return pull.isKill?-1:pull.phaseOrder??phaseRank(phaseKey(pull))}
function completionProgress(pull){
  if(pull.isKill)return 100;
  const remaining=pull.fightPercentage??pull.bossPercentage;
  if(remaining===undefined||remaining===null||remaining==='')return 0;
  const value=Number(remaining);
  return Number.isFinite(value)?Math.max(0,Math.min(100,100-value)):0;
}
function phaseColor(pull){
  const progress=completionProgress(pull);
  return progress>=99?'#e268a8':progress>=95?'#ff8000':progress>=75?'#a335ee':progress>=50?'#0070ff':progress>=25?'#1eff00':'#999999';
}
function totalTime(rows){const total=Math.round(rows.reduce((sum,row)=>sum+Number(row.pull.durationMs||0),0)/1000);return`${Math.floor(total/60)}:${String(total%60).padStart(2,"0")}`}
function pullTile(row){const pull=row.pull,progress=completionProgress(pull);return`<button class="pull-tile ${pull.isKill?"kill-tile":""}" style="--progress:${progress}%;--phase-color:${phaseColor(pull)}" data-pull="${row.index}" type="button"><div class="pull-percent">${pull.isKill?"KILL":`${Number(pull.bossPercentage||0).toFixed(0)}%`}<small>${esc(pull.isKill?"完成":phaseKey(pull))}</small></div><div class="pull-copy"><b>Pull ${esc(pull.fightID??pull.id??row.index+1)}，${esc(pull.duration||"")}</b><small>${esc(difficultyName(pull))}，${esc(pull.startClock||pull.date||"")}</small></div></button>`}
function groupRows(items){const rank={normal:0,heroic:1,mythic:2,unknown:3};if(!state.separate){if(state.difficulty!=="all")return[["全部 Pull",items]];return[...new Set(items.map(row=>difficultyKey(row.pull)))].sort((a,b)=>(rank[a]??9)-(rank[b]??9)).map(key=>[`${difficultyName(items.find(row=>difficultyKey(row.pull)===key).pull)}，全部 Pull`,items.filter(row=>difficultyKey(row.pull)===key)])}const keyOf=row=>`${difficultyKey(row.pull)}::${phaseKey(row.pull)}`;return[...new Set(items.map(keyOf))].sort((a,b)=>{const[da,pa]=a.split("::"),[db,pb]=b.split("::");return(rank[da]??9)-(rank[db]??9)||pullPhaseRank(items.find(row=>keyOf(row)===a).pull)-pullPhaseRank(items.find(row=>keyOf(row)===b).pull)}).map(key=>{const[diff,phase]=key.split("::"),sample=items.find(row=>difficultyKey(row.pull)===diff);return[`${difficultyName(sample.pull)}，${phase}`,items.filter(row=>keyOf(row)===key)]})}
function openPull(index){const pull=state.pulls[index];if(!pull||!state.descriptor)return;location.href=window.MythicReportRuntime.detailUrl(state.descriptor,state.sourcePath,pull.fightID??pull.id??index+1);}
function renderFilteredSummary(metric, players) {
  const filter = metric.summaryFilter;
  if (!filter) return renderPlayerSummary(metric, players);
  const current = metricPlayerFilters[metric.key] || {enabled:false, threshold:filter.defaultThreshold ?? 10};
  const rows = current.enabled ? players.filter(row=>Number(row[filter.key]) < current.threshold && (!filter.eligibilityKey || row[filter.eligibilityKey] === true)) : players;
  const total = rows.reduce((sum,row)=>sum+Number(row[filter.totalKey] || 0),0);
  return `<div class="metric-filter"><label><input type="checkbox" data-player-filter="${esc(metric.key)}" ${current.enabled?'checked':''}> ${esc(filter.label)}</label><input type="number" min="0" step="1" aria-label="筛选次数阈值" data-player-threshold="${esc(metric.key)}" value="${esc(current.threshold)}"> 次</div>${current.enabled?`<p class="metric-filter-result">${esc(filter.description || "")} 符合条件 ${rows.length} 人，${esc(filter.totalLabel)} ${total} 次</p>`:''}${rows.length?renderPlayerSummary(metric,rows):'<div class="metric-empty">没有符合筛选条件的玩家。</div>'}`;
}
function bindPlayerFilters(root, metrics) {
  root.querySelectorAll('[data-player-filter],[data-player-threshold]').forEach(input=>input.onchange=()=>{
    const key=input.dataset.playerFilter || input.dataset.playerThreshold;
    const metric=metrics.find(row=>row.key===key);
    const current=metricPlayerFilters[key] || {enabled:false,threshold:metric.summaryFilter.defaultThreshold??10};
    if(input.dataset.playerFilter) current.enabled=input.checked;
    else {
      if(input.value==='' || !input.checkValidity()) {input.reportValidity();return;}
      current.threshold=Number(input.value);
    }
    metricPlayerFilters[key]=current;
    renderMechanicOverview();
  });
}
function renderPlayerSummary(metric, players) {
  if (!players.length) return '<div class="metric-empty">暂无可确认玩家。</div>';
  const columns = metric.summaryColumns || [];
  const count = row => row.countBreakdown?.length
    ? `<button class="count-breakdown" type="button" data-count-breakdown="${esc(JSON.stringify(row.countBreakdown))}" data-breakdown-title="${esc(metric.countBreakdownLabel || '次数明细')}" aria-label="${esc(row.player)} ${esc(row.count)} 次，查看明细">${esc(row.count)} 次</button>`
    : `<b>${esc(row.countLabel ?? `${row.count ?? 0} 次`)}</b>`;
  if (columns.length) return `<table class="metric-player-table"><thead><tr><th>玩家</th>${columns.map(c=>`<th>${esc(c.label)}</th>`).join('')}</tr></thead><tbody>${players.map(row=>`<tr><td style="color:${safeColor(row.classColor)}">${esc(row.player || '未知玩家')}</td>${columns.map(c=>`<td>${esc(row[c.key] ?? 0)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  return players.map(row=>`<div class="metric-player"><span style="color:${safeColor(row.classColor)}">${esc(row.player || '未知玩家')}</span>${count(row)}</div>`).join('');
}
function bindCountBreakdowns(root) {
  let popup = document.getElementById('countBreakdownPopup');
  if (!popup) { popup = document.createElement('div'); popup.id = 'countBreakdownPopup'; popup.className = 'count-breakdown-popup'; popup.setAttribute('role','tooltip'); document.body.appendChild(popup); }
  popup.hidden = true;
  const hide = () => { popup.hidden = true; };
  root.querySelectorAll('[data-count-breakdown]').forEach(button => {
    const show = () => {
      const rows = JSON.parse(button.dataset.countBreakdown);
      popup.innerHTML = `<strong>${esc(button.dataset.breakdownTitle)}</strong><table><tbody>${rows.map(row=>`<tr><td>${esc(row.label)}</td><td>${esc(row.count)} 次</td></tr>`).join('')}</tbody></table>`;
      popup.hidden = false;
      const rect = button.getBoundingClientRect(), width = popup.offsetWidth, height = popup.offsetHeight;
      popup.style.left = `${Math.max(8, rect.right + width + 12 < innerWidth ? rect.right + 8 : rect.left - width - 8)}px`;
      popup.style.top = `${Math.max(8, Math.min(rect.top, innerHeight - height - 8))}px`;
    };
    button.setAttribute('aria-describedby', popup.id);
    button.onmouseenter = show; button.onmouseleave = hide;
    button.onfocus = show; button.onblur = hide;
    button.onclick = show; button.onkeydown = event => { if (event.key === 'Escape') hide(); };
  });
}
function renderMechanicOverview(){const root=$("mechanicOverview"),overview=state.payload?.data?.mechanicOverview;if(!root)return;if(!overview||!Array.isArray(overview.metrics)){root.innerHTML="";return}root.innerHTML=`<section class="mechanic-summary"><div class="mechanic-head"><div><div class="eyebrow">整夜统计</div><h2>${esc(overview.title||"机制一览")}</h2></div><p>${esc(overview.subtitle||"")}</p></div><div class="metric-grid">${overview.metrics.map(metric=>{const events=Array.isArray(metric.events)?metric.events:[],views=Array.isArray(metric.summaryViews)?metric.summaryViews:[],selected=views.find(v=>v.key===metricSummaryViews[metric.key])||views[0],players=selected?.rows||(Array.isArray(metric.players)?metric.players:[]);return`<article class="metric-card tone-${esc(metric.tone||"neutral")}"><div class="metric-title"><span class="metric-value">${esc(metric.value??0)}<small>${esc(metric.unit||"")}</small></span><span class="metric-label">${esc(metric.label||metric.key||"机制")}</span></div><p class="metric-description">${esc(metric.description||"")}</p><div class="metric-player-summary"><h3>${esc(selected?.label||"玩家汇总")}</h3>${views.length?`<div>${views.map(v=>`<button type="button" data-summary-metric="${esc(metric.key)}" data-summary-view="${esc(v.key)}" aria-pressed="${v.key===selected.key}">${esc(v.label)}</button>`).join("")}</div>`:""}${renderFilteredSummary(metric,players)}</div><details class="metric-records"><summary>${events.length?`逐条记录（${events.length}）`:`逐条记录（0）`}</summary>${events.length?`<div class="metric-events">${events.map(event=>`<button type="button" class="metric-event" data-mechanic-report="${esc(event.reportID||"")}" data-mechanic-fight="${esc(event.fightID)}"><span>Fight ${esc(event.fightID)}，${esc(event.time||"")}</span><b>${esc(event.text||"")}</b></button>`).join("")}</div>`:'<div class="metric-empty">本次日志没有命中该条件。</div>'}</details></article>`}).join("")}</div></section>`;bindCountBreakdowns(root);bindPlayerFilters(root,overview.metrics);root.querySelectorAll("[data-summary-metric]").forEach(button=>button.onclick=()=>{metricSummaryViews[button.dataset.summaryMetric]=button.dataset.summaryView;renderMechanicOverview()});root.querySelectorAll("[data-mechanic-fight]").forEach(button=>button.onclick=()=>{const reportID=button.dataset.mechanicReport,fightID=Number(button.dataset.mechanicFight),index=state.pulls.findIndex(pull=>(!reportID||pull.reportID===reportID)&&Number(pull.fightID??pull.id)===fightID);if(index>=0)openPull(index)})}
function setOverviewTab(view){state.view=view==="mechanics"?"mechanics":"pulls";const mechanics=state.view==="mechanics";$("pullsPanel").hidden=mechanics;$("mechanicsPanel").hidden=!mechanics;$("pullsTab").classList.toggle("active",!mechanics);$("mechanicsTab").classList.toggle("active",mechanics);$("pullsTab").setAttribute("aria-selected",String(!mechanics));$("mechanicsTab").setAttribute("aria-selected",String(mechanics))}
function render(){const items=orderedRows(),scope=state.pulls.filter(pull=>state.difficulty==="all"||difficultyKey(pull)===state.difficulty),kills=scope.filter(pull=>pull.isKill).length,wipes=scope.length-kills,last=[...scope].sort((a,b)=>String(a.startTimeIso||"").localeCompare(String(b.startTimeIso||""))).slice(-1)[0];$("wipesFilter").textContent=`全部灭团 (${wipes})`;$("allFilter").textContent=`全部战斗 (${kills} 击杀, ${wipes} 灭团)`;$("wipesFilter").classList.toggle("active",state.filter==="wipes");$("allFilter").classList.toggle("active",state.filter==="all");$("lastPull").innerHTML=last?`最后一场，${esc(difficultyName(last))}，<span class="${last.isKill?"kill":"wipe"}">${last.isKill?"击杀":`${Number(last.bossPercentage||0).toFixed(2)}%`}</span>，${esc(last.duration||"")}，${esc(last.startClock||"")}`:"没有可显示的 Pull";renderMechanicOverview();$("pullBoard").innerHTML=items.length?groupRows(items).map(([key,rows])=>`<section class="phase-group"><div class="phase-heading"><h2>${esc(key)}</h2><span class="phase-total">${rows.filter(row=>!row.pull.isKill).length} 次灭团，${totalTime(rows)}</span></div><div class="pull-tiles">${rows.map(pullTile).join("")}</div></section>`).join(""):'<div class="empty">当前筛选没有战斗。</div>';document.querySelectorAll("[data-pull]").forEach(button=>button.onclick=()=>openPull(Number(button.dataset.pull)))}
function renderDifficultyOptions(){const rank={normal:0,heroic:1,mythic:2,unknown:3},rows=[...new Map(state.pulls.map(pull=>[difficultyKey(pull),difficultyName(pull)])).entries()].sort((a,b)=>(rank[a[0]]??9)-(rank[b[0]]??9));$("difficultyFilter").innerHTML='<option value="all">全部难度（分组展示）</option>'+rows.map(([key,name])=>`<option value="${esc(key)}">${esc(name)}</option>`).join("")}
async function bindPayload(payload){state.payload=payload;state.descriptor=await window.MythicReportRuntime.loadDescriptor(state.payload);state.pulls=pullsOf(state.payload);state.difficulty="all";const identity=window.MythicReportRuntime.identityOf(state.payload);$("bossName").textContent=identity.bossName||"全场战斗概览";$("raidName").textContent=[identity.version,state.payload.meta?.raidName||identity.raidKey].filter(Boolean).join("，");document.title=`${identity.bossName}，全场战斗概览`;renderDifficultyOptions();render();$("error").textContent=""}
async function load(){if(!state.sourcePath)throw new Error("公共概览需要从已生成或已导入的整场 JSON 进入。");await bindPayload(await window.MythicReportRuntime.loadPayload(state.sourcePath))}
function downloadJson(){if(!state.payload)return;const identity=window.MythicReportRuntime.identityOf(state.payload),stamp=new Date().toISOString().slice(0,10),safeBoss=String(identity.bossName||identity.bossKey||"wcl").replace(/[\\/:*?"<>|\s]+/g,"-");const blob=new Blob([JSON.stringify(state.payload,null,2)],{type:"application/json;charset=utf-8"}),url=URL.createObjectURL(blob),anchor=document.createElement("a");anchor.href=url;anchor.download=`${safeBoss}-${stamp}.json`;document.body.appendChild(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),0)}
async function importJson(event){const file=event.target.files?.[0];if(!file)return;try{const payload=JSON.parse(await file.text());state.sourcePath=await window.MythicReportRuntime.storePayload(payload,{label:file.name});const url=new URL(location.href);url.searchParams.set("json",state.sourcePath);history.replaceState(null,"",url);await bindPayload(payload)}catch(error){$("error").textContent=`无法导入 JSON：${error.message}`}finally{event.target.value=""}}
$("wipesFilter").onclick=()=>{state.filter="wipes";render()};$("allFilter").onclick=()=>{state.filter="all";render()};$("difficultyFilter").onchange=event=>{state.difficulty=event.target.value;render()};$("separatePhases").onchange=event=>{state.separate=event.target.checked;render()};$("sortButton").onclick=()=>{state.sortAsc=!state.sortAsc;$("sortButton").textContent=state.sortAsc?"时间正序":"时间倒序";render()};state.sourcePath=new URLSearchParams(location.search).get("json")||"";load().catch(error=>$("error").textContent=error.message);
$("pullsTab").onclick=()=>setOverviewTab("pulls");$("mechanicsTab").onclick=()=>setOverviewTab("mechanics");
$("downloadJson").onclick=downloadJson;$("importJson").onchange=importJson;
