/* Sszorak-only mechanic views. Data adjudication stays in the Boss module. */
const sszReplay={cursor:null,windowKey:'full',speed:1};
function sszClock(ms){const s=Math.max(0,ms)/1000;return `${Math.floor(s/60)}:${(s%60).toFixed(1).padStart(4,'0')}`}
function sszWindows(data){
  const duration=boss().combatReplay?.durationMs||current()?.durationMs||1;
  return [{key:'full',label:'完整战斗',start:0,end:duration},
    ...(data.rounds||[]).map(r=>({key:`dig:${r.index}`,label:`掘地固守 #${r.index} · ${r.time}`,start:r.timeMs,end:Math.min(duration,r.timeMs+Number(r.windowSec||r.durationSec||25)*1000)})),
    ...(data.crosswindWaves||[]).map(w=>({key:`cross:${w.index}`,label:`狂怒侧风 #${w.index} · ${w.applyTime}`,start:w.applyTimeMs,end:Math.min(duration,Math.max(w.applyTimeMs+12000,...(w.targets||[]).map(t=>(t.resolutionTimeMs??t.launchTimeMs??w.applyTimeMs)+1200)))}))];
}
function sszWindow(data){return sszWindows(data).find(w=>w.key===sszReplay.windowKey)||sszWindows(data)[0]}
function windAtFrame(round,timeMs){
  if(!round||timeMs<round.timeMs||timeMs>=round.timeMs+Number(round.durationSec||25)*1000)return null;
  const winds=round.winds||[],index=Math.floor((timeMs-round.timeMs)/(Number(round.durationSec||25)*1000/Math.max(1,winds.length)));
  return winds[index]||(!winds.length?round.wind:null);
}
function sszFallbackPlayers(data,cursor){
  const frames=(data.rounds||[]).flatMap(r=>r.frames||[]).sort((a,b)=>a.timeMs-b.timeMs);
  const left=frames.findLast(f=>f.timeMs<=cursor),right=frames.find(f=>f.timeMs>cursor);
  if(!left||cursor-left.timeMs>5000)return [];
  const next=new Map((right?.players||[]).map(p=>[p.playerID,p]));
  return (left.players||[]).map(p=>{const n=next.get(p.playerID),blend=right&&right.timeMs-left.timeMs<=5000?(cursor-left.timeMs)/(right.timeMs-left.timeMs):0;
    return {...p,position:lerpPoint(p.position,n?.position||p.position,blend)};});
}
function sszPlayerRows(data,cursor){
  const replay=boss().combatReplay,tracks=replay?.units?.filter(u=>u.kind==='player')||[];
  return tracks.length?tracks.map(u=>{const life=MechanicWorkbench.lifeState(u,cursor),point=MechanicWorkbench.trackPosition(u,life.positionTime,replay.interpolateMaxGapMs);return {playerID:u.actorID,player:u.name,icon:u.icon,classColor:u.color,key:u.key,position:point?{...point,y:point.y+Number(data.arena?.coordinateOffsetYards||0)*100}:null,dead:life.dead,opacity:life.opacity};}):sszFallbackPlayers(data,cursor);
}
function sszBossPosition(data,cursor){
  const replay=boss().combatReplay,bossID=replay?.bosses?.[0]?.actorID,unit=replay?.units?.find(u=>u.actorID===bossID);
  if(unit){const point=MechanicWorkbench.trackPosition(unit,cursor,replay.interpolateMaxGapMs);return point?{...point,y:point.y+Number(data.arena?.coordinateOffsetYards||0)*100}:null;}
  return data.bossCenter||null;
}
function sszAnimatedMap(data,cursor){
  if(!data.arena)return '<div class="empty">缺少场地坐标。</div>';
  const width=1000,height=562,project=p=>{const q=pct(p,data.arena);return q?{x:q.left*10,y:q.top*height/100}:null;};
  const rows=sszPlayerRows(data,cursor),byID=new Map(rows.map(p=>[p.playerID,p]));
  const round=(data.rounds||[]).find(r=>cursor>=r.timeMs&&cursor<r.timeMs+Number(r.durationSec||25)*1000),wind=windAtFrame(round,cursor);
  const placements=[...new Map((data.rounds||[]).flatMap(r=>r.placements||[]).map(p=>[p.placementKey,p])).values()];
  const cysts=placements.map(p=>{
    const q=project(p.position),end=p.consumedAtMs??p.activatedAtMs;
    if(!q||cursor<p.timeMs||end!=null&&cursor>=end+900)return '';
    const age=end==null?-1:cursor-end,pulse=age>=0,progress=Math.max(0,age/900),radius=pulse?12+progress*55:14;
    return `<g data-key="cyst:${esc(p.placementKey)}" opacity="${pulse?1-progress:1}"><title>腐蚀囊肿 · ${esc(p.player)}${pulse?' · 已激活':''}</title><circle cx="${q.x}" cy="${q.y}" r="${radius}" fill="${pulse?'#bfff68':'#55691f'}" fill-opacity="${pulse?.16:.8}" stroke="#ceff84" stroke-width="${pulse?3:2}"/>${pulse?'':`<text x="${q.x}" y="${q.y+4}" text-anchor="middle" fill="#f0ffc6" font-size="12">${esc(p.placementWave??p.slot??'')}</text>`}</g>`;
  }).join('');
  const targets=(data.crosswindWaves||[]).flatMap(w=>w.targets||[]),size=pctSize(6,data.arena),rings=targets.map(t=>{
    const end=t.resolutionTimeMs??(t.launchTimeMs??t.applyTimeMs)+10000;
    if(cursor<t.applyTimeMs||cursor>=end)return '';
    const p=byID.get(t.playerID)?.position||t.launchPosition||t.position,q=project(p);if(!q)return '';
    const flying=t.launchTimeMs!=null&&cursor>=t.launchTimeMs,color=t.directionGroup==='A'?'#7fdbff':'#edacff';
    const start=flying?project(t.launchPosition):null;
    return `<g data-key="cross:${t.playerID}:${t.applyTimeMs}"><title>${esc(t.player)} · ${flying?'侧风起飞':'侧风点名'}</title>${start?`<path d="M ${start.x} ${start.y} L ${q.x} ${q.y}" stroke="${color}" stroke-width="6" opacity=".25"/>`:''}<ellipse cx="${q.x}" cy="${q.y}" rx="${size.width*10}" ry="${size.height*height/100}" fill="${color}" fill-opacity=".07" stroke="${color}" stroke-width="2" stroke-dasharray="${flying?'':'5 5'}"/><g transform="translate(${q.x} ${q.y}) rotate(${Number(t.arrowAngleDegrees||0)})"><path d="M 20 0 L 48 0 m -9 -7 l 9 7 -9 7" fill="none" stroke="${color}" stroke-width="3"/></g></g>`;
  }).join('');
  const collisions=(data.crosswindWaves||[]).flatMap(w=>w.pairings||[]).map((p,i)=>{
    const age=cursor-p.timeMs;if(age<0||age>=800)return '';
    const l=byID.get(p.left.playerID)?.position,r=byID.get(p.right.playerID)?.position,q=project(lerpPoint(l,r,.5));if(!q)return '';
    return `<circle data-key="collision:${p.timeMs}:${i}" cx="${q.x}" cy="${q.y}" r="${12+age/800*50}" fill="#e3caff" fill-opacity="${.2*(1-age/800)}" stroke="#efd9ff" stroke-width="3" opacity="${1-age/800}"/>`;
  }).join('');
  const hits=(data.crosswindWaves||[]).flatMap(w=>w.collateralHits||[]).filter(h=>cursor>=h.timeMs&&cursor-h.timeMs<650);
  const actors=rows.filter(p=>p.position).map(p=>MechanicWorkbench.avatar({...p,name:p.player,color:p.classColor,key:p.key||p.playerID}, {...project(p.position),stale:p.position.stale},12,hits.some(h=>h.playerID===p.playerID),p.dead,p.opacity)).join('');
  const bossLife=MechanicWorkbench.lifeState(boss().combatReplay?.bosses?.[0]||{},cursor),center=project(sszBossPosition(data,bossLife.positionTime)),bossIcon=center&&bossLife.opacity?`<image data-key="boss" href="/${esc(String(data.bossIcon||'').replace(/^\//,''))}" x="${center.x-24}" y="${center.y-24}" width="48" height="48" opacity="${.8*bossLife.opacity}" style="${bossLife.dead?'filter:grayscale(1)':''}"/>`:'';
  const windFx=wind?`<g data-key="wind" transform="translate(500 281) rotate(${Number(wind.angleDegrees||0)})" opacity=".55">${[-160,-80,0,80,160].map((y,i)=>{const phase=((cursor-round.timeMs)/1200+i*.17)%1,x=-380+phase*760;return `<path d="M ${x-90} ${y} L ${x} ${y} m -12 -7 l 12 7 -12 7" fill="none" stroke="#c6f5fc" stroke-width="${i===2?3:2}" opacity="${Math.sin(phase*Math.PI)}"/>`;}).join('')}</g>`:'';
  return `<div data-key="field" class="replay-map ssz-map" style="background-image:url('/${esc(String(data.arenaImage||'').replace(/^\//,''))}')"><svg viewBox="0 0 ${width} ${height}" width="100%" height="100%" aria-label="斯索拉克场地回放"><g data-key="boss-layer">${bossIcon}</g><g data-key="cysts">${cysts}</g><g data-key="wind-layer">${windFx}</g><g data-key="targets">${rings}${collisions}</g><g data-key="players">${actors}</g></svg></div>`;
}
function updateReplayStage(){
  const data=boss().fieldReplay||{},w=sszWindow(data),cursor=sszReplay.cursor??w.start,stage=$('replayStage');
  if(stage){MechanicWorkbench.patchMap(stage,sszAnimatedMap(data,cursor));const field=stage.querySelector('.replay-map');let hud=field?.querySelector('[data-managed="boss-status"]');if(field&&!hud){hud=document.createElement('div');hud.setAttribute('data-managed','boss-status');field.append(hud);}if(hud)MechanicWorkbench.patchMap(hud,MechanicWorkbench.bossStatus(boss().combatReplay,cursor));}
  const round=(data.rounds||[]).find(r=>cursor>=r.timeMs&&cursor<r.timeMs+Number(r.durationSec||25)*1000),wind=windAtFrame(round,cursor);
  if($('replayStatus'))$('replayStatus').textContent=`${sszClock(cursor)} / ${sszClock(w.end)}${wind?' · 风向 '+(wind.directionLabel||'待确认'):''}`;
  if($('replayScrub'))$('replayScrub').value=String(cursor);
  if($('playReplay'))$('playReplay').textContent=state.timer?'暂停':'播放';
}
function bindReplay(data){
  const w=sszWindow(data);if(sszReplay.cursor==null||sszReplay.cursor<w.start||sszReplay.cursor>w.end)sszReplay.cursor=w.start;
  const play=()=>{if(state.timer){stopReplay();updateReplayStage();return;}if(sszReplay.cursor>=w.end)sszReplay.cursor=w.start;
    let last=performance.now();const tick=now=>{if(!$('replayStage')?.isConnected){stopReplay();return;}
      sszReplay.cursor=Math.min(w.end,sszReplay.cursor+(now-last)*sszReplay.speed);last=now;updateReplayStage();
      if(sszReplay.cursor>=w.end){stopReplay();updateReplayStage();}else state.timer=requestAnimationFrame(tick);};
    state.timer=requestAnimationFrame(tick);updateReplayStage();};
  $('playReplay').onclick=play;
  $('restartReplay').onclick=()=>{stopReplay();sszReplay.cursor=w.start;updateReplayStage();};
  $('replayScrub').oninput=e=>{stopReplay();sszReplay.cursor=Number(e.target.value);updateReplayStage();};
  $('sszSpeed').onchange=e=>sszReplay.speed=Number(e.target.value);
  $('sszWindow').onchange=e=>{stopReplay();sszReplay.windowKey=e.target.value;sszReplay.cursor=null;renderContent();};
  updateReplayStage();
}
function renderReplay(){
  const data=boss().fieldReplay||{},w=sszWindow(data),windows=sszWindows(data);
  setTimeout(()=>{if(state.tab==='replay')bindReplay(data);},0);
  return `<section class="panel"><div class="replay-tools"><select id="sszWindow" aria-label="回放片段">${windows.map(row=>`<option value="${row.key}" ${row.key===w.key?'selected':''}>${esc(row.label)}</option>`).join('')}</select><button id="playReplay" class="button">播放</button><button id="restartReplay" class="button">重新开始</button><select id="sszSpeed" aria-label="播放速度">${[1,2,4].map(speed=>`<option value="${speed}" ${speed===sszReplay.speed?'selected':''}>${speed}×</option>`).join('')}</select><output id="replayStatus"></output></div><label class="replay-scrub">战斗时间<input id="replayScrub" aria-label="战斗时间" type="range" min="${w.start}" max="${w.end}" step="100" value="${sszReplay.cursor??w.start}"></label><div id="replayStage"></div></section>`;
}
function renderSszorakTempest() {
  const data = boss().tempest;
  if (!data) return '<div class="empty">请重新分析日志以获取风暴施加与驱散次数。</div>';
  return `<h2>风暴施加与驱散</h2><p class="muted">施加包含首次施加、叠层与刷新；主动驱散按实际驱散者统计成功驱散事件，图腾等宠物归属主人。</p>
    ${table(['玩家', '被施加次数', '主动驱散次数'], (data.players || []).map(row => [player(row), row.applicationCount, row.dispelCount]))}
    <details><summary>主动驱散明细</summary>${table(['时间', '驱散者', '被驱散玩家', '驱散技能'], (data.dispels || []).map(row => [esc(row.time), player(row.dispeller), player(row), spellLink(row.dispelSpellID)]))}</details>`;
}

function renderSszorakFury() {
  const data = boss().serpentsFury;
  if (!data || data.enabled === false) return '<div class="empty">仅适用于启用印记分析的史诗战斗，请重新分析日志。</div>';
  const outside = rows => (rows || []).map(row => `${player(row)}（${row.distanceYards} 码）`).join('、') || '—';
  return `<section class="panel" data-analysis-option="serpentsFuryReviewEnabled"><h2>毒蛇之怒，战术集合点</h2>
    <p class="muted">印记需要至少 ${data.requiredPlayers} 人进入 ${data.radiusYards} 码范围触发。${esc(data.evidenceNote)}</p><p>已检查 ${data.checkCount || 0} 个集合点，实际怒不可遏 ${data.actualEnrageCount ?? data.enrageCount ?? 0} 次，豁免 ${data.exemptCount || 0} 次</p>
    ${table(['玩家', '未进圈次数'], (data.players || []).map(row => [player(row), row.count]))}
    ${(data.events || []).map(row => `<article class="card"><h3>第 ${row.round || '—'} 次，${esc(row.time)}，${esc(row.status)}</h3>
      <p>印记目标：${player(row.markTarget)}，战术板：${esc(row.plannedTime || row.time)}，Combo 漂移：${row.comboDriftMs > 0 ? '+' : ''}${row.comboDriftMs || 0}ms，结算前死亡：${row.deadCount} 人</p>
      ${row.exempt ? '' : `<p>圈外非治疗：${outside(row.outsidePlayers)}</p><p>圈内非治疗：${players(row.insidePlayers)}</p><p>坐标未确认：${players(row.unknownPlayers)}</p>`}
      <p class="muted">排除治疗：${players(row.excludedHealers)}</p></article>`).join('')}
    ${!(data.events || []).length ? '<div class="empty">本场尚未走到一个完整的战术集合点。</div>' : ''}</section>`;
}

function renderPredator(){const data=boss().apexPredator||{},rows=[];(data.sequence||[]).forEach((row,index,list)=>{if(index===0||row.cycle!==list[index-1].cycle)rows.push([`<tr><td colspan="6" class="cycle-divider"><strong>顶级掠食者 ${row.cycle}</strong></td></tr>`]);if(row.skill==='风暴')rows.push([esc(row.time),esc(row.skill),'—',players(row.affectedTargets),'—',players(row.deaths)]);else rows.push([esc(row.time),esc(row.skill),player({player:row.target,classColor:(row.participants||[]).find(p=>p.playerID===row.targetID)?.classColor||'#fff'}),players(row.participants),players(row.deaths),'—'])}) ;return`<section class="panel" data-analysis-option="predatorReviewEnabled"><h2>每轮剑技顺序</h2><table><thead><tr><th>时间</th><th>剑技</th><th>承受目标</th><th>${esc('影响目标 / 分摊')}</th><th>直接死亡</th><th>备注</th></tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></section><section class="panel" data-analysis-option="tempestReviewEnabled">${renderSszorakTempest()}</section>${(boss().fallDeaths||[]).length?`<section class="panel"><h2>跌落死亡</h2>${table(["时间","玩家","说明"],boss().fallDeaths.map(row=>[esc(row.time),player(row),esc(row.note)]))}</section>`:''}`}
function visiblePlacements(round,timeMs){return(round?.placements||[]).filter(row=>timeMs>=row.timeMs&&((row.activatedAtMs??row.consumedAtMs)==null||timeMs<(row.activatedAtMs??row.consumedAtMs)))}
function fieldMap(data,{round=null,wave=null,framePlayers:players=[],frameTimeMs=0,showWind=true}={}){const arena=data.arena;if(!arena)return'<div class="empty">缺少场地坐标。</div>';const actors=(players||[]).map(row=>{const p=pct(row.position,arena),tooltip=`${row.player||'未知玩家'}${row.positionReliable?'':'，坐标为临近采样'}`;return p?`<span class="actor ${row.positionReliable?'':'stale'}" data-report-tooltip="${esc(tooltip)}" aria-label="${esc(tooltip)}" style="left:${p.left}%;top:${p.top}%;--color:${row.classColor||'#fff'}">${specIcon(row)}</span>`:''}).join('');const cysts=(round?visiblePlacements(round,frameTimeMs):[]).map(row=>{const p=pct(row.position,arena),activation=row.activatedTime?`；预估激活 ${row.activatedTime}`:'',batch=row.placementWave??row.slot??'?';return p?`<span class="cyst ${row.placementOk===false?'bad':''}" title="${esc(`${row.player||'未知玩家'}，第 ${batch} 次放置${activation}`)}" style="left:${p.left}%;top:${p.top}%">${batch}</span>`:''}).join('');const boss=pct(sszBossPosition(data,frameTimeMs||wave?.launchTimeMs||wave?.applyTimeMs||round?.timeMs||0),arena);const bossDot=boss?`<span class="boss-center" title="斯索拉克 · 当前日志位置" style="left:${boss.left}%;top:${boss.top}%">${data.bossIcon?`<img src="${esc(data.bossIcon)}" alt="斯索拉克">`:''}</span>`:'';const currentWind=windAtFrame(round,frameTimeMs),wind=showWind&&currentWind?`<span class="wind-arrow map-wind" style="left:50%;top:50%;transform:translate(-50%,-50%) rotate(${currentWind.angleDegrees||0}deg)">→</span>`:'';const cross=(wave?.targets||[]).map(row=>{const p=pct(row.launchPosition||row.position,arena),size=pctSize(row.circleRadiusYards||6,arena),angle=Number(row.arrowAngleDegrees||0),tooltip=`${row.player}，${row.directionLabel||''}，${row.resolution||''}`;return p?`<span class="crosswind-target group-${esc(String(row.directionGroup||'').toLowerCase())}" data-report-tooltip="${esc(tooltip)}" aria-label="${esc(tooltip)}" style="left:${p.left}%;top:${p.top}%;width:${size.width*2}%;height:${size.height*2}%;--arrow-angle:${angle}deg;--color:${row.classColor||'#fff'}">${specIcon(row)}<i class="target-arrow" aria-hidden="true"></i></span>`:''}).join('');const waveArrow=wave?(wave.axes||[{label:wave.inferredDirection,angleDegrees:wave.arrowAngleDegrees}]).map(axis=>`<span class="crosswind-axis" title="${esc(axis.label)}" style="left:50%;top:50%;transform:translate(-50%,-50%) rotate(${axis.angleDegrees||0}deg)"></span>`).join(''):'';return`<div class="replay-map" style="background-image:url('${esc(data.arenaImage)}')">${bossDot}${cysts}${waveArrow}${cross}${actors}${wind}</div>`}
function mobilityUses(rows){return(rows||[]).map(row=>`${player(row.source)} ${spellLink(row.spellID,row.spellName)}（${esc(row.timingLabel)}）`).join('、')||'<span class="muted">未记录主动位移技能</span>'}
function renderCrosswindMap(data,wave){const directionGroups=(wave.directionGroups||[]).map(group=>`<div class="crosswind-group group-${esc(String(group.key||'').toLowerCase())}"><strong>${esc(group.label)}，${group.targetCount||0} 人</strong><div>${players(group.targets)}</div></div>`).join('');const pairRows=(wave.pairings||[]).map(pair=>[esc(pair.time),`${player(pair.left)} ↔ ${player(pair.right)}`,`${pair.leftAirborneMs==null?'—':(pair.leftAirborneMs/1000).toFixed(2)+'s'} / ${pair.rightAirborneMs==null?'—':(pair.rightAirborneMs/1000).toFixed(2)+'s'}`,mobilityUses(pair.mobilityUses)]);const unresolved=(wave.targets||[]).filter(row=>!row.collisionPartner),collateral=(wave.collateralHits||[]);return`<article class="card crosswind-card"><h3>狂怒侧风 #${wave.index||'—'}，点名 ${esc(wave.applyTime)}，起飞 ${esc(wave.launchTime||'—')}，${wave.targetCount||0} 人</h3><div class="crosswind-groups">${directionGroups}</div>${fieldMap(data,{wave,showWind:false})}<h4>对撞解除</h4>${table(["时间","对撞玩家","起飞后耗时","主动位移技能"],pairRows)}${unresolved.length?`<div class="crosswind-unresolved"><strong>未确认正常对撞：</strong>${unresolved.map(row=>`<div>${player(row)}（${esc(row.resolution)}），${mobilityUses([...(row.mobilityUses||[]),...(row.immunityUses||[])])}</div>`).join('')}</div>`:''}${collateral.length?`<h4>6 码群体击飞误伤</h4>${table(["时间","被误伤玩家","附近点名玩家","距离","伤害"],collateral.map(row=>[esc(row.time),player(row),row.sourceTarget?player(row.sourceTarget):'—',row.distanceYards==null?'—':`${row.distanceYards} 码`,num(row.amount)]))}`:''}</article>`}
function renderSszorak(tab){const data=boss();const replay=data.fieldReplay||{};if(tab==='fury')return renderSszorakFury();if(tab==='predator')return renderPredator();if(tab==='cysts')return`<section class="panel"><h2>腐蚀囊肿放置（按掘地轮次）</h2><p class="muted">每次剧毒涌动施法点名两名玩家；同一批两人属于同一次放置，目标先后仅作为 WCL 证据展示。</p>${(data.cysts?.rounds||[]).map(round=>`<article class="card"><h3>掘地固守 #${round.index}，${esc(round.time)}</h3>${table(["放置批次","放置","激活","玩家","放置侧","激活证据","判定"],(round.placements||[]).map(row=>{const evidence=row.activationEvidence,activation=evidence?`${player(evidence.nearestPlayer)} 距离 ${evidence.nearestDistanceYards}码，光环${evidence.auraApplyCount}/伤害${evidence.damageHitCount}/位移${evidence.forcedMovementCount}`:'—',batch=row.placementWave??row.slot??'—',order=row.volleyTargetOrder?`<div class="muted">同批第 ${row.volleyTargetOrder} 名目标</div>`:'';return[`第 ${batch} 次${order}`,esc(row.time),row.activatedTime?esc(row.activatedTime):'—',player(row),esc(row.windSideLabel||'待定'),activation,row.placementOk===false?`<span class="badge bad">位置错误</span><div class="muted">${esc(row.expected||'')}</div>`:row.placementOk?'<span class="badge good">符合</span>':row.placementStatus==='exempt'?`<span class="badge warn">豁免</span><div class="muted">${esc(row.exemptionReason||row.expected||'')}</div>`:row.placementStatus==='unverified'?`<span class="badge warn">未取证</span><div class="muted">${esc(row.expected||'')}</div>`:'<span class="muted">不归责</span>']}))}</article>`).join('')||table(["序号","放置","激活","玩家","坐标"],(data.cysts?.placements||[]).map((row,index)=>[`#${index+1}`,esc(row.time),row.activatedTime?esc(row.activatedTime):'—',player(row),row.position?`${(row.position.x/100).toFixed(1)}, ${(row.position.y/100).toFixed(1)}`:'无坐标']))}</section>`;if(tab==='crosswinds')return`<section class="panel"><h2>狂怒侧风</h2><p class="muted">同一轮次汇总全部点名。1285425/1285453 记录两个方向；起飞后 1285447 在 120ms 内由相反方向两人同时移除，判定为对撞消除。</p><div class="cards crosswind-rounds">${(data.crosswinds?.waves||replay.crosswindWaves||[]).map(wave=>renderCrosswindMap(replay,wave)).join('')||'<div class="empty">没有狂怒侧风记录。</div>'}</div></section>`;if(tab==='replay')return renderReplay()}
