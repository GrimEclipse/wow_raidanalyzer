/* Twin Fangs mechanic views; adjudication lives in the Boss module. */
function twinEmpty(section) {
  return `<div class="empty">${esc(section?.reason || '本次未分析该项目，或报告生成于旧版本。')}</div>`;
}
function twinDamage(rows) {
  return table(['时间','来源','技能 / 说明','伤害','吸收','过量'], (rows || []).map(e => [esc(e.time),esc(e.source),spellLink(e.spellID,e.spell)+(e.mechanicNote?`<br><small>${esc(e.mechanicNote)}</small>`:''),e.amount,e.absorbed,e.overkill]));
}
function twinImmunity(evidence) {
  const e = evidence || {};
  const active = (e.auras || []).map(a => spellLink(a.spellID,a.spell)).join('、');
  const ended = (e.recentlyEnded || []).map(a => `${spellLink(a.spellID,a.spell)} 于本段前 ${esc(a.secondsBefore)} 秒结束`).join('、');
  return active || (e.immuneHit ? 'WCL immune 命中' : ended || '未覆盖免疫');
}
function twinVenomRounds(rounds) {
  if (!rounds?.length) return '';
  return `<section class="panel twin-venom-rounds"><h2>永恒毒液，每轮吃球与叠层</h2>
    <p class="muted">沿用坦克腐蚀洪流后的吃球轮次，按吃球数量从少到多排列，包含全团零吃球玩家。条形依次显示吃球层数、异常技能命中次数、其他叠层；均统计本轮新增。零吃球仅为记录，不自动判错。</p>
    <div class="twin-venom-legend"><span class="twin-orb">吃球（层）</span><span class="twin-abnormal">异常命中（次）</span><span class="twin-other">其他 / 正常（层）</span></div>
    ${rounds.map(round=>{
      const rows=round.players||[];
      const max=Math.max(1,...rows.map(p=>p.orbStacks+p.abnormalHitCount+p.otherStacks));
      const segment=(value,kind,label)=>value?`<span class="twin-venom-segment twin-${kind}" style="width:${value/max*100}%" title="${esc(label)}">${value}</span>`:'';
      return `<details class="twin-venom-round"><summary>第 ${round.index} 轮，${esc(round.time)}–${esc(round.endTime)}，${round.hitCount} 次吃球，${round.zeroPickupCount} 人未吃球</summary>
        <div class="twin-venom-chart" role="list" aria-label="第 ${round.index} 轮全团吃球与叠层">
        ${rows.map(p=>{
          const label=`${p.player}：吃球 ${p.orbCount} 次，增加 ${p.orbStacks} 层；异常命中 ${p.abnormalHitCount} 次，增加 ${p.abnormalStacks} 层；其他 ${p.otherStacks} 层；共新增 ${p.totalGains} 层`;
          return `<div class="twin-venom-row ${p.orbCount===0?'twin-zero-pickup':''}" role="listitem">
            <div class="twin-venom-player">${player(p)}<small>${!p.aliveAtStart?'轮初已死亡':!p.aliveAtEnd?'本轮死亡':p.orbCount===0?'未吃球':`吃球 ${p.orbCount} 次`}</small></div>
            <div class="twin-venom-track" role="img" aria-label="${esc(label)}" title="${esc(label)}">${segment(p.orbStacks,'orb',`吃球增加 ${p.orbStacks} 层`)}${segment(p.abnormalHitCount,'abnormal',`异常命中 ${p.abnormalHitCount} 次，增加 ${p.abnormalStacks} 层`)}${segment(p.otherStacks,'other',`其他 ${p.otherStacks} 层${p.unknownStacks?`，其中 ${p.unknownStacks} 层来源未确认`:''}`)}${p.orbStacks+p.abnormalHitCount+p.otherStacks===0?'<span class="muted twin-venom-zero">0</span>':''}</div>
            <div class="twin-venom-total">新增 <b>${p.totalGains}</b> 层${p.unknownStacks?`<small>来源未确认 ${p.unknownStacks} 层</small>`:''}${p.abnormalHitCount?`<small>异常贡献 ${p.abnormalStacks} 层</small>`:''}${p.orbCount>0&&!p.orbStacks?'<small>吃球叠层未匹配</small>':''}</div>
          </div>`;
        }).join('')}</div></details>`;
    }).join('')}</section>`;
}
function twinImmunityUsage(section) {
  const usage=section.immunityUsage;
  if(section.strategy!=='immunity'||!usage)return '';
  const rows=usage.events||[];
  const renderRows=items=>table(['使用时间','施法者 → 目标','技能 / 结束时间','时机判定','后续盛宴 / 补位记录'],items.map(e=>[
    esc(e.time),`${player(e.caster)} → ${player(e.target)}`,
    `${spellLink(e.spellID,e.spell)}<br><small>${e.endTime?`结束于 ${esc(e.endTime)}`:'未见结束记录'}</small>`,
    `${e.abnormal?'<span class="badge warn">待复核</span> ':''}${esc(e.status)}${e.coverage.length?`<br><small>${e.coverage.map(c=>`覆盖第 ${c.round} 轮第 ${c.strikeIndices.join('、')} 段`).join('；')}</small>`:''}`,
    `${e.nextRound?`第 ${e.nextRound} 轮${e.assigned?'（已安排）':''}，${e.secondsBefore>=0?`提前 ${e.secondsBefore} 秒`:`首段后 ${Math.abs(e.secondsBefore)} 秒`}`:'无后续盛宴'}${e.replacements.map(r=>`<br><small>第 ${r.strikeIndex} 段名单外免疫参与：${players(r.players)}</small>`).join('')}`
  ]));
  return `<section class="panel"><h2>异常时机使用保护 / 无敌 / 冰箱 / 龟壳，${usage.abnormalCount} 次待复核</h2><p class="muted">${esc(usage.evidenceNote)}</p>
    ${rows.some(e=>e.abnormal)?renderRows(rows.filter(e=>e.abnormal)):'<div class="empty">未见异常时机使用记录。</div>'}
    <details><summary>全部免疫使用记录（${rows.length} 次）</summary>${renderRows(rows)}</details></section>`;
}
function twinBroodMap(arena, rows) {
  const points = [...arena.left, ...arena.right];
  const minX = Math.min(...points.map(p=>p[0]))-650, maxX = Math.max(...points.map(p=>p[0]))+650;
  const minY = Math.min(...points.map(p=>p[1]))-650, maxY = Math.max(...points.map(p=>p[1]))+650;
  const x = value => 30+(value-minX)/(maxX-minX)*480;
  const y = value => 30+(maxY-value)/(maxY-minY)*300;
  const dots = ['left','right'].map(side => arena[side].map((point,i) => {
    const events = rows.filter(r=>r.position?.arena===arena.key && r.position.side===side && r.position.slot===i+1);
    const color = events.some(r=>r.successfulCasts) ? '#fb7185' : events.some(r=>r.interrupts.length) ? '#34d399' : '#93806a';
    const label = `${side==='left'?'左':'右'}${i+1}`;
    return `<g><title>${esc(label)}，${point[0]}, ${point[1]}，${events.length} 个蛇头</title><circle cx="${x(point[0])}" cy="${y(point[1])}" r="10" fill="${color}"/><text x="${x(point[0])+14}" y="${y(point[1])+5}" fill="white" font-size="13">${esc(label)}</text></g>`;
  }).join('')).join('');
  const bosses = ['left','right'].map(side=>{const p=arena.bosses[side];return `<text x="${x(p[0])}" y="${y(p[1])-18}" text-anchor="middle" fill="#fbbf24" font-size="12">${side==='left'?'左侧Boss':'右侧Boss'}</text>`;}).join('');
  return `<figure style="margin:0;max-width:580px"><figcaption>${esc(arena.label)}，红色漏断 / 绿色已打断 / 灰色未观测</figcaption><svg role="img" aria-label="${esc(arena.label)}蛇头固定点位" viewBox="0 0 560 380" style="width:100%;background:#1c160f;border-radius:12px">${dots}${bosses}</svg></figure>`;
}
function twinCheckpoints(checkpoints) {
  if (!checkpoints?.length) return '<section class="panel"><h2>层数超过预期</h2><p class="muted">未观测到完整转圈结束，未生成层数检查点。</p></section>';
  return `<section class="panel"><h2>层数超过预期</h2><p class="muted">按转圈实际结束检查，第一轮最多4层、第二轮最多7层，每人每个检查点最多计一次；检查前任何玩家阵亡则全团该次检查豁免，战复不取消。来源表为此前累计增加，扣除移除层数得到当前层数；不推测被消掉的具体来源。</p>${checkpoints.map(c=>`<article class="card"><h3>第 ${c.index} 次，${esc(c.time)}，上限 ${c.limit} 层，计数 ${c.count} 人${c.exempt?'（已豁免）':''}</h3>${c.exemption?`<p class="muted">${esc(c.exemption.time)} ${player(c.exemption)} 阵亡；${esc(c.exemption.reason)}</p>`:''}<p class="muted">${esc(c.evidence)}</p>${c.players.map(p=>`<details ${p.exceeded?'open':''}><summary>${player(p)}：${p.stacks} 层 ${p.exceeded?(p.exempt?'<span class="badge warn">超限但豁免，不计数</span>':'<span class="badge bad">超过预期 +1</span>'):''}${!p.alive?'（已死亡）':''}</summary><p>${p.gainsBySource.map(s=>`${esc(s.source)} +${s.stacks}`).join('；')||'无新增记录'}；共移除 ${p.removedStacks} 层</p>${table(['时间','来源','变化','结果'],p.history.map(e=>[esc(e.time),esc(e.source),`${e.delta>0?'+':''}${e.delta}`,`${e.fromStack} → ${e.toStack}`]))}</details>`).join('')}</article>`).join('')}</section>`;
}
// WCL positions are hundredths of a yard. The six fixed Boss positions align
// with the three corners of the original 1997x1118 encounter image at this scale.
const TWIN_ARENA_IMAGE = '/assets/raids/venomous_abyss/06-twinfangs.jpg';
const TWIN_ARENA_MAP = {width:1997,height:1118,centerX:998.5,northY:69145,northPixelY:150,scale:.0625};
// Calibrated to the five marked positions on the original map. A single
// world-to-image scale puts the bosses and the three spit heads on different
// sides of the platform art, so only these fixed north anchors are corrected.
const TWIN_NORTH_ANCHORS = {
  bosses:{left:[912,97],right:[1100,97]},
  brood:{left:[[835,122],[952,67]],right:[[1180,124],[1045,74]]},
  heads:{left:[942,484],middle:[1006,461],right:[1067,470]},
};
const TWIN_BOSS_PORTRAITS = {
  Vexhul:{name:'维克苏尔',color:'#86efac',image:'/assets/raids/venomous_abyss/portraits/140993.png'},
  Ithraz:{name:'伊斯拉兹',color:'#fb7185',image:'/assets/raids/venomous_abyss/portraits/141309.png'},
};
function twinMapPoint(point) {
  if(!Array.isArray(point)||point.length<2||!point.every(Number.isFinite))return null;
  const m=TWIN_ARENA_MAP;
  return [m.centerX+point[0]*m.scale,m.northPixelY+(m.northY-point[1])*m.scale];
}
function twinMapRayEnd(start,through) {
  const dx=through[0]-start[0],dy=through[1]-start[1],m=TWIN_ARENA_MAP;
  const distances=[dx>0?(m.width-start[0])/dx:dx<0?-start[0]/dx:Infinity,
    dy>0?(m.height-start[1])/dy:dy<0?-start[1]/dy:Infinity].filter(value=>value>0);
  const distance=Math.min(...distances);
  return Number.isFinite(distance)?[start[0]+dx*distance,start[1]+dy*distance]:start;
}
function twinSpitMap(row,bossSides) {
  if(!row.origin||!row.targetPosition||!row.headPositions||!row.bossPositions)return '';
  const north=row.arena==='north'?TWIN_NORTH_ANCHORS:null;
  const headPoint=(side,p)=>north?.heads[side]||twinMapPoint(p);
  const bossPoint=(side,p)=>north?.bosses[side]||twinMapPoint(p);
  const heads=Object.entries(row.headPositions).map(([side,p])=>[side,headPoint(side,p)]).filter(([,p])=>p);
  const bosses=Object.entries(row.bossPositions).map(([side,p])=>[side,bossPoint(side,p)]).filter(([,p])=>p);
  const headBySide=Object.fromEntries(heads),bossBySide=Object.fromEntries(bosses);
  const rawOrigin=twinMapPoint(row.origin),fixedHead=twinMapPoint(row.headPositions[row.headSlot]);
  const correctedHead=headBySide[row.headSlot];
  const origin=rawOrigin&&fixedHead&&correctedHead
    ?[rawOrigin[0]+correctedHead[0]-fixedHead[0],rawOrigin[1]+correctedHead[1]-fixedHead[1]]:rawOrigin;
  const target=twinMapPoint(row.targetPosition);
  if(!origin||!target||Math.hypot(target[0]-origin[0],target[1]-origin[1])<.01)return '';
  const point=p=>`${p[0].toFixed(1)},${p[1].toFixed(1)}`;
  const polygon=[headBySide.left,bossBySide.left,bossBySide.right,headBySide.right];
  const line=[headBySide.left,headBySide.right];
  const boundaries=['left','right'].map(side=>headBySide[side]&&bossBySide[side]
    ?[origin[0]+bossBySide[side][0]-headBySide[side][0],origin[1]+bossBySide[side][1]-headBySide[side][1]]:null);
  const cone=boundaries.every(Boolean)?boundaries.map(p=>twinMapRayEnd(origin,p)):[];
  const end=twinMapRayEnd(origin,target),color=row.counted?'#fb7185':'#67e8f9';
  const labels=heads.map(([side,p])=>`<g><circle cx="${p[0]}" cy="${p[1]}" r="11" fill="#a78bfa" stroke="#1e1b4b" stroke-width="4"/><text x="${p[0]}" y="${p[1]+39}" text-anchor="middle" fill="#eee8ff" font-size="27">${({left:'左蛇',middle:'中蛇',right:'右蛇'})[side]}</text></g>`).join('')
    +bosses.map(([side,p])=>{const boss=TWIN_BOSS_PORTRAITS[bossSides?.[side]];
      return `<g><rect x="${p[0]-22}" y="${p[1]-22}" width="44" height="44" rx="8" fill="${boss?.color||'#fbbf24'}"/>${boss?`<image href="${boss.image}" x="${p[0]-20}" y="${p[1]-20}" width="40" height="40" preserveAspectRatio="xMidYMid slice"/>`:''}<rect x="${p[0]-22}" y="${p[1]-22}" width="44" height="44" rx="8" fill="none" stroke="${boss?.color||'#fbbf24'}" stroke-width="5"/><text x="${p[0]}" y="${p[1]-32}" text-anchor="middle" fill="${boss?.color||'#fff1b0'}" font-size="29">${boss?.name||`${side==='left'?'左':'右'} Boss`}</text></g>`;
    }).join('');
  return `<figure class="twin-spit-map"><svg viewBox="0 0 1997 1118" role="img" aria-label="原场地图上的蛇头射线、Boss、点名目标和禁射范围"><image href="${TWIN_ARENA_IMAGE}" width="1997" height="1118"/><rect width="1997" height="1118" fill="#020617" opacity=".24"/>${cone.length===2?`<polygon points="${[origin,...cone].map(point).join(' ')}" fill="#ef4444" fill-opacity=".2" stroke="#fb7185" stroke-width="5" stroke-dasharray="16 12"/>`:''}${polygon.length===4&&polygon.every(Boolean)?`<polygon points="${polygon.map(point).join(' ')}" fill="#fbbf24" fill-opacity=".14" stroke="#fbbf24" stroke-width="4" stroke-dasharray="12 10"/>`:''}${line.length===2&&line.every(Boolean)?`<line x1="${line[0][0]}" y1="${line[0][1]}" x2="${line[1][0]}" y2="${line[1][1]}" stroke="#e2e8f0" stroke-width="5" stroke-dasharray="12 10"/>`:''}<line x1="${origin[0]}" y1="${origin[1]}" x2="${end[0]}" y2="${end[1]}" stroke="#020617" stroke-width="13"/><line x1="${origin[0]}" y1="${origin[1]}" x2="${end[0]}" y2="${end[1]}" stroke="${color}" stroke-width="7"/>${labels}<circle cx="${origin[0]}" cy="${origin[1]}" r="17" fill="#a78bfa" stroke="#fff" stroke-width="5"/><circle cx="${target[0]}" cy="${target[1]}" r="18" fill="#fff" stroke="${color}" stroke-width="6"/><text x="${target[0]+28}" y="${target[1]+9}" fill="#fff" font-size="32">${esc(row.target?.player||'未知目标')}</text></svg><figcaption>原场地图：绿框维克苏尔、红框伊斯拉兹；紫点为这次施法的蛇头，白点为点名玩家。青色／红色线为实际射线方向，淡红区域为禁射夹角。上方五个固定锚点按标注位置校准。</figcaption></figure>`;
}
function renderTwin(tab) {
  if(tab==='explore')return '<div id="twinBroodWorkbench"></div>';
  const data = boss();
  if (tab === 'venom') return twinCheckpoints(data.eternalVenom?.checkpoints) + twinVenomRounds(data.eternalVenom?.rounds) + renderTwinLegacy(tab);
  if (tab === 'spit') {
    const section=data.spit;if(!section?.enabled)return twinEmpty(section);
    let activeArena=null,swapped=false;
    const events=section.events.map(r=>{
      if(r.arena&&activeArena&&r.arena!==activeArena)swapped=!swapped;
      if(r.arena)activeArena=r.arena;
      const bossSides=r.bossSides||{left:swapped?'Ithraz':'Vexhul',right:swapped?'Vexhul':'Ithraz'};
      swapped=bossSides.left==='Ithraz';
      return `<details ${r.counted||r.collateral.length?'open':''}><summary>${esc(r.time)}，蛇头 ${r.headID} / ${r.headInstance} → ${r.target?player(r.target):'目标未确认'}，${esc(r.status)}${r.collateral.length?`，额外受击 ${r.collateral.length} 人`:''}</summary><p>${esc(r.reasons.join('；'))}</p>${twinSpitMap(r,bossSides)}<p class="muted">${esc(r.arenaLabel||'场地未定位')}；左侧 ${TWIN_BOSS_PORTRAITS[bossSides.left]?.name||'待确认'}，右侧 ${TWIN_BOSS_PORTRAITS[bossSides.right]?.name||'待确认'}${r.bossSideEvidence?`（${esc(r.bossSideEvidence)}）`:''}；目标坐标距完成 ${r.positionAgeMs??'未知'} ms。额外受击者对应此蛇头的射线，是否由点名者错误引导应结合方向结论。</p>${table(['受击玩家','身份','命中时间','伤害'],r.victims.map(v=>[player(v),v.isTarget?'点名目标':'额外受击',esc(v.hitTime),v.damage]))}</details>`;
    }).join('');
    return `<section class="panel"><h2>蛇头射线：方向错误 ${section.count} 次，额外受击 ${section.collateralCount} 人次</h2><p class="muted">${esc(section.evidenceNote)}</p><p class="muted">两只 Boss 初始站在原场地图上方三角台子的两个角；每次转阶段后交换左右位置。报告优先使用 Boss 在 WCL 中的坐标确认身份，缺少坐标时按转场次数交替。每条射线直接叠在原图上，过渡位置不作禁射边界。</p>${events||'<div class="empty">没有蛇头完成射线读条。</div>'}</section>`;
  }
  if (tab === 'feast') {
    const section = data.feast;
    if (!section?.enabled) return twinEmpty(section);
    return twinImmunityUsage(section) + `<section class="panel"><h2>贪婪盛宴，${section.strategy==='immunity'?'免疫分摊':'非免疫分摊'}</h2><p class="muted">${esc(section.evidenceNote)}</p>
      ${(section.rounds||[]).map(round=>`<article class="card"><h3>第 ${round.index} 轮，${esc(round.time)} ${round.incomplete?'<span class="badge warn">三段记录不完整</span>':''}</h3>
      ${section.strategy==='immunity'?`<p>免疫安排：${players(round.assigned)}</p>${(round.protectionWarnings||[]).map(w=>`<p class="muted">${esc(w)}</p>`).join('')}${!round.assignmentValid?`<p class="muted">${esc(round.configurationNote)} ${esc((round.unresolvedNames||[]).join('、'))}</p>`:''}`:''}
      ${(round.strikes||[]).map(strike=>`<details ${strike.underfilled||strike.directUnprotected?.length||strike.secondaryRaidDamage?.length?'open':''}><summary>第 ${strike.index} 段，${esc(strike.time)}，${strike.participantCount} 人首批命中 / 至少 ${strike.minimum} 人 ${strike.underfilled?'，人数不足':''}${strike.directUnprotected?.length?`，额外直击 ${strike.directUnprotected.length} 人`:''}${strike.secondaryRaidDamage?.length?`，延迟全团溅射 ${strike.secondaryRaidDamage.length} 人`:''}</summary>
      ${table(['玩家','命中结果','伤害','免疫证据'],(strike.displayParticipants||strike.participants).map(p=>[player(p),esc(p.result),p.damage,twinImmunity(p.immunity)]))}
      ${strike.directUnprotected?.length?`<p class="muted">首批直接承受未免疫分摊：${strike.directUnprotected.map(p=>`${player(p)} ${p.damage} 伤害`).join('、')}。这些记录与延迟全团溅射分开。</p>`:''}
      ${strike.secondaryRaidDamage?.length?`<p class="muted">本段另有 ${strike.secondaryRaidDamage.length} 条延迟全团溅射记录，不计入分摊人数。</p>`:''}
      ${strike.assignmentChecks?.length?table(['安排玩家','判定','免疫覆盖','近期免疫施法'],strike.assignmentChecks.map(p=>[player(p),esc(p.status),twinImmunity(p.immunity),(p.recentCasts||[]).map(c=>`${esc(c.time)} ${spellLink(c.spellID)}（${c.secondsBefore}s 前）`).join('<br>')||'未见记录'])):''}
      ${strike.assignmentChecks?.length?'<p class="muted">记录可证明提前结束或未覆盖，无法证明具体按键操作；近期施法用于核对冷却与重置。</p>':''}</details>`).join('')}
      ${round.failures?.length?`<h4>本轮失误（每人一次）</h4>${table(['责任玩家','伤害段','原因'],round.failures.map(p=>[player(p),esc([...new Set(p.strikeIndices)].join('、')),esc(p.reasons.join('；'))]))}`:''}</article>`).join('')||'<div class="empty">没有盛宴结算。</div>'}</section>`;
  }
  if (tab === 'brood') {
    const section=data.brood;if(!section?.enabled)return twinEmpty(section);
    const rounds=[...new Set((section.events||[]).map(r=>r.round))];
    return `<div id="twinBroodWorkbench"></div>${section.collapseExemption?`<section class="panel"><p>${esc(section.collapseExemption.time)}：已有 ${section.collapseExemption.deadCount} 人死亡且未战复，本场漏断不计归责；完整事件仍可回放。</p></section>`:''}<section class="panel"><h2>蛇头打断，${section.successfulCastCount} 次首漏断</h2><p class="muted">${esc(section.positionNote)} 未定位 ${section.unresolvedCount} 个。</p>
      ${rounds.map(no=>{const rows=section.events.filter(r=>r.round===no);const arenas=(section.arenas||[]).filter(a=>rows.some(r=>r.position?.arena===a.key));return `<article class="card"><h3>召唤第 ${no||'未知'} 轮</h3>${arenas.map(a=>twinBroodMap(a,rows)).join('')}
      ${table(['首次漏断时间','点位','组别 / 序号','主断','补断','实际打断','结果 / 证据'],rows.map(r=>[esc(r.time),esc(r.position?`${r.position.arenaLabel} ${r.position.label}`:'坐标未确认'),esc(r.groupLabel||'')+' '+(r.groupOrder||'—'),players(r.assigned)+(r.unresolvedNames?.length?`<br><small>名单待匹配：${esc(r.unresolvedNames.join('、'))}</small>`:''),players(r.backup),(r.interrupts||[]).map(e=>`${esc(e.time)} ${player(e.player)} ${spellLink(e.spellID)}`).join('<br>')||'—',`${esc(r.leakLabel||r.status)}${r.successfulCasts?` ×${r.successfulCasts}`:''}<br><small>${esc(r.assignmentNote)}</small>${r.tankEvidence?`<br><small>${esc(r.tankEvidence.reason)}，${Math.round((r.tankEvidence.ageMs||0)/100)/10}s 前</small>`:''}`]))}</article>`;}).join('')||'<div class="empty">本场未见脏腑爆裂成功施法。</div>'}</section>`;
  }
  if (tab === 'stone') {
    const section=data.stone;if(!section?.enabled)return twinEmpty(section);
    const cutoffNote=section.tankDeathCutoffMs!=null?`本场首次倒坦在 ${(section.tankDeathCutoffMs/1000).toFixed(1)} 秒，之后不再统计。`:'本场未观测到坦克死亡。';
    return `<section class="panel"><h2>裂石击，${section.raidDamageCount} 次计入</h2><p>${esc(cutoffNote)}</p><p class="muted">优先使用实际接圈目标，其次参考同组三连击目标或读条时仇恨，并展示依据。每场只计首次全团伤害；此前炸球或已死亡超过 3 人则豁免，后续伤害保留明细。</p>${table(['时间','接圈玩家 / 依据','结果','总伤害','受击玩家'],(section.events||[]).map(r=>[esc(r.time),`${r.tank?player(r.tank):'未确认'}<br><small>${esc(r.evidence)}</small>`,r.raidDamage?(r.counted?'<span class="badge bad">全团伤害，计入</span>':`<span class="badge">全团伤害，豁免</span><br><small>${esc((r.exemptionReasons||[]).join('；'))}</small>`):'未见全团爆发',r.totalDamage,players(r.victims)]))}</section>`;
  }
  if (tab === 'earlyDeaths' || tab === 'venomDeaths') {
    const section=data[tab];if(!section?.enabled)return twinEmpty(section);
    const isEarly=tab==='earlyDeaths';
    return `<section class="panel"><h2>${isEarly?'提前死亡及全部死亡明细':'永恒毒液，带毒死亡与后续爆球'}</h2><p class="muted">${esc(section.evidenceNote)}</p>
      ${isEarly?`<p>间隔阈值 ${section.gapSeconds} 秒，提前死亡 ${section.earlyDeaths?.length||0} 人次</p>`:`<p>带毒死亡 ${section.deaths?.length||0} 人次，按携带层数预期额外球 ${section.expectedGlobuleCount} 个</p>`}
      ${(section.deaths||[]).map(r=>`<details ${isEarly&&r.early?'open':''}><summary>${esc(r.time)}，${player(r)}，${spellLink(r.killingSpellID,r.killingSpell)} ${r.mechanicNote?`（${esc(r.mechanicNote)}）`:""}，带毒 ${r.venomStacks} 层 ${r.early?'，提前死亡':''}</summary>${r.gapToFollowingDeathsSeconds?`<p>距后续死亡 / 战斗结束 ${r.gapToFollowingDeathsSeconds} 秒</p>`:''}${twinDamage(r.precedingDamage)}</details>`).join('')||'<div class="empty">没有对应死亡。</div>'}
      ${!isEarly?`<h3>实测球爆炸</h3>${table(['时间','总伤害','受击玩家','此前15秒带毒死亡'],(section.explosions||[]).map(r=>[esc(r.time),r.totalDamage,players(r.victims),(r.nearbyVenomDeaths||[]).map(p=>`${player(p)} ${esc(p.time)}（${p.stacks}层）`).join('、')||'未见记录']))}<p class="muted">时间关联不等于球来源的唯一因果关系。</p>`:''}</section>`;
  }
  if (tab==='globules' && data.isMythic) {
    return twinVenomRounds(data.globules?.venomRounds) + `<section class="panel"><h2>史诗腐蚀洪流，坦克点名与绿球</h2><p class="muted">区分坦克洪流轮次、球周围壁垒实体和实际吃球。死亡额外球见“带毒死亡”。史诗不使用每人必须吃一个的英雄归责。</p>
      ${table(['轮次','时间','洪流点名','观测壁垒实体'],(data.tankGlobules?.rounds||[]).map(r=>[r.index,esc(r.time),player(r.target),r.bulwarks.length]))}
      ${(data.globules?.rounds||[]).map(r=>`<article class="card"><h3>#${r.index}，${esc(r.time)}，${r.hitCount} 次吃球命中</h3><p>吃球玩家：${(r.eaten||[]).map(p=>`${player(p)} ×${p.count}`).join('、')||'—'}</p><p>${r.exploded?`观测球爆炸：${esc(r.explosionTime)}`:'未见球爆炸'}</p></article>`).join('')}</section>`;
  }
  if (tab==='globules') return twinVenomRounds(data.globules?.venomRounds) + renderTwinLegacy(tab);
  return renderTwinLegacy(tab);
}

function renderTwinLegacy(tab){const data=boss();if(tab==='venom'){const venom=data.eternalVenom||{};const pl=venom.players||[];const abn=venom.abnormalGains||[];if(!state.venomPlayer||!pl.some(p=>p.player===state.venomPlayer))state.venomPlayer=pl[0]?.player||'';const sel=pl.find(p=>p.player===state.venomPlayer)||pl[0]||null;const catBadge=c=>({normal:'<span class="badge">正常叠层</span>',abnormal:'<span class="badge bad">异常叠层</span>',feast:'<span class="badge warn">贪婪盛宴消耗</span>',remove:'<span class="badge">其他移除</span>',clear:'<span class="badge">完全移除</span>',death:'<span class="badge bad">死亡清层</span>'}[c]||esc(c));const options=pl.map(p=>`<option value="${esc(p.player)}"${p.player===state.venomPlayer?' selected':''}>${esc(p.player)}，峰值 ${p.peakStack} 层</option>`).join('');const selRows=sel?sel.events.map(ev=>`<tr class="${ev.category==='abnormal'?'abnormal-row':''}"><td>${esc(ev.time)}</td><td>${ev.delta>0?`+${ev.delta}`:ev.delta}</td><td>${ev.fromStack}→${ev.toStack}</td><td>${catBadge(ev.category)}</td><td>${spellLink(ev.sourceID,ev.source)}</td></tr>`).join(''):'';const html=`<section class="panel abnormal-panel" data-analysis-option="venomReviewEnabled"><h2>异常叠层记录</h2><p class="muted">腐蚀洪流绿圈直击 / 腐蚀液滴爆裂 / 搅动深渊 / 邪恶洪流等异常来源直接叠加的层数；正常吃球与 Boss 直接点名叠层不在此列。</p>${table(["时间","玩家","变化","叠至","来源"],abn.map(row=>[esc(row.time),player(row),`+${row.delta}`,row.toStack,spellLink(row.sourceID,row.source)]))}</section><section class="panel" data-analysis-option="venomReviewEnabled"><h2>永恒毒液叠层明细</h2><div class="venom-picker">查看玩家<select id="venomPlayerSelect">${options}</select></div>${sel?`<h3>${player(sel)}，峰值 ${sel.peakStack} 层，累计叠 ${sel.gainCount}，累计消 ${sel.removedCount}</h3><table><thead><tr><th>时间</th><th>变化</th><th>层数</th><th>归类</th><th>来源 / 原因</th></tr></thead><tbody>${selRows}</tbody></table>`:'<div class="empty">没有永恒毒液记录。</div>'}</section><section class="panel" data-analysis-option="feastReviewEnabled"><h2>贪婪盛宴消层检查</h2>${table(["轮次","时间","应进圈","已消层","未正常消层"],(venom.feastChecks||[]).map(row=>[`#${row.index}`,esc(row.time),players(row.present),players(row.consumed),players(row.missing)]))}</section>`;setTimeout(()=>{const select=document.getElementById("venomPlayerSelect");if(select)select.onchange=event=>{state.venomPlayer=event.target.value;renderContent()}},0);return html};if(tab==='globules')return`<section class="panel"><h2>腐蚀浪潮，每轮吃球</h2><p class="muted">每轮球数与吃球来自 WCL 伤害记录，团队规模为应吃份额：正常每人 1 个，超过 1 个即异常叠层，0 个即没吃。</p><div class="cards">${(data.globules?.rounds||[]).map(row=>`<article class="card"><h3>#${row.index}，${esc(row.time)}，共 <strong>${row.ballCount??row.hitCount}</strong> 球，团队 ${row.teamSize??'—'}（在场 ${row.aliveCount??'—'}）${row.exploded?`，<span class="badge bad">${esc(row.explosionTime)} 爆炸</span>`:''}</h3>${(row.abnormal||[]).length?`<p><span class="badge bad">异常叠层</span> ${row.abnormal.map(item=>`<b>${player(item)} ×${item.count}</b>`).join('、')}</p>`:''}<p><span class="badge good">吃了</span> ${row.eaten?.length?row.eaten.map(item=>`${player(item)}${item.count>1?` ×${item.count}`:''}`).join('、'):'—'}</p><p><span class="badge warn">没吃</span> ${(row.missed||[]).length?players(row.missed):'—'}</p>${row.exploded&&(row.nonParticipants||[]).length?`<p class="muted">爆炸时未参与：${players(row.nonParticipants)}</p>`:''}</article>`).join('')||'<div class="empty">没有腐蚀浪潮轮次。</div>'}</div></section>`;if(tab==='mythic')return`<section class="panel"><h2>史诗难度占位</h2><div class="empty">${esc(data.mythicPlaceholder||'该部分暂时没有可用的信息。')}</div></section>`}

window.mountBossMechanics=()=>{if(state.tab==='brood'||state.tab==='explore')mountTwinBroodWorkbench();};

function twinPlatformAnchor(arena,kind,side,slot){
  const p=kind==='brood'?TWIN_NORTH_ANCHORS.brood[side]?.[slot-1]:TWIN_NORTH_ANCHORS[kind]?.[side];if(!p)return null;
  const center=twinMapPoint([0,61155]),angle=arena==='southeast'?2*Math.PI/3:arena==='southwest'?-2*Math.PI/3:0,dx=p[0]-center[0],dy=p[1]-center[1];
  return [center[0]+dx*Math.cos(angle)-dy*Math.sin(angle),center[1]+dx*Math.sin(angle)+dy*Math.cos(angle)];
}
function twinPortrait(key,p,r,image,color,age=null,label=''){
  const opacity=age==null?1:Math.max(0,1-age/900);if(!opacity)return '';
  return `<g data-key="${esc(key)}" transform="translate(${p[0]} ${p[1]})" opacity="${opacity}"><title>${esc(label)}</title><circle r="${r+2}" fill="#101b2b" stroke="${color}" stroke-width="2"/><image href="${image}" x="${-r}" y="${-r}" width="${2*r}" height="${2*r}" preserveAspectRatio="xMidYMid slice" style="clip-path:circle(50%);${age==null?'':'filter:grayscale(1)'}"/>${age==null?'':`<path d="M -7 -7 L 7 7 M 7 -7 L -7 7" stroke="#fff" stroke-width="2"/>`}</g>`;
}
function twinBeam(key,p,target,color,cursor,warning=false){
  if(!p||!target)return '';const length=Math.hypot(target[0]-p[0],target[1]-p[1]);if(length<1)return '';
  const dx=(target[0]-p[0])/length,dy=(target[1]-p[1])/length,end=[p[0]+dx*1200,p[1]+dy*1200],line=`M ${p[0]} ${p[1]} L ${end[0]} ${end[1]}`;
  return `<g data-key="${esc(key)}" pointer-events="none"><path d="${line}" fill="none" stroke="${color}" stroke-width="${warning?12:28}" opacity="${warning?.2:.18}"/><path d="${line}" fill="none" stroke="${color}" stroke-width="${warning?2:5}" opacity=".8" stroke-dasharray="${warning?'10 9':'30 20'}" stroke-dashoffset="${warning?0:-(cursor%900)/900*50}"/></g>`;
}
function twinBroodPoint(head){
  const p=head.position;if(!p)return null;
  return p.slot<=2?twinPlatformAnchor(p.arena,'brood',p.side,p.slot)||twinMapPoint([p.x,p.y]):twinMapPoint([p.x,p.y]);
}
function mountTwinBroodWorkbench(){
  const section=boss().brood||{},host=document.getElementById('twinBroodWorkbench');if(!host||!window.MechanicWorkbench)return;
  const rows=section.replayEvents||section.events||[],feedback=boss().replayFeedback||{},replay=boss().combatReplay||{},events=[];
  const add=(timeMs,label,extra={})=>events.push({id:String(events.length),timeMs,label,layer:label,group:extra.head?`第 ${extra.head.round} 轮`:'全场',...extra});
  add(0,'战斗开始');
  for(const head of rows){add(head.spawnTimeMs??head.timeMs,'蛇头出现',{head});for(const kick of head.interrupts||[])add(kick.timeMs,'实际打断',{head,actor:kick.player?.player});for(const ms of head.successTimesMs||[])add(ms,'漏断施法',{head,problem:true});}
  for(const t of feedback.torrents||[]){add(t.startTimeMs,'邪恶洪流');if(t.endTimeMs!=null)add(t.endTimeMs,'转场');}
  for(const round of boss().feast?.rounds||[])add(round.timeMs,'贪婪盛宴');
  const bosses=(replay.bosses||[]).map(b=>({...b,name:b.gameID===257361?'维克苏尔':b.gameID===257368?'伊斯拉兹':b.name,casts:[...(b.casts||[]),...(feedback.channels||[]).filter(c=>c.actorID===b.actorID),...(feedback.torrents||[]).filter(t=>t.actorID===b.actorID&&t.endTimeMs!=null).map(t=>({...t,outcome:'completed',phase:'channel'}))].sort((a,b)=>a.startTimeMs-b.startTimeMs)}));
  let camera={x:0,y:0,width:1997,height:1118};
  const workbench=MechanicWorkbench.mount(host,{key:'twinfangs-brood',combatReplay:{...replay,bosses},durationMs:current()?.durationMs,events,deaths:current()?.survival?.timeline||[]},
    {video:state.tab!=='explore',handlesPlayers:true,project(point){const p=twinMapPoint([point.x,point.y]);return p?{x:(p[0]-camera.x)/camera.width*100,y:(p[1]-camera.y)/camera.height*100}:null;},renderMap(selected,filtered,cursor){
      const torrent=(feedback.torrents||[]).find(t=>cursor>=t.startTimeMs&&(t.endTimeMs==null||cursor<t.endTimeMs));
      let arenaKey=rows.find(r=>r.position)?.position.arena||'north';
      for(const t of feedback.torrents||[]){if(t.endTimeMs!=null&&cursor>=t.endTimeMs){const next=rows.find(h=>(h.spawnTimeMs??h.timeMs)>t.endTimeMs&&h.position);if(next)arenaKey=next.position.arena;}}
      if(!(feedback.torrents||[]).length)arenaKey=rows.findLast(h=>h.timeMs<=cursor&&h.position)?.position.arena||arenaKey;
      const area=(section.arenas||[]).find(a=>a.key===arenaKey),areaHeads=rows.filter(h=>h.position?.arena===arenaKey),locations=[...areaHeads.map(twinBroodPoint),...['left','right'].map(side=>twinPlatformAnchor(arenaKey,'bosses',side))].filter(Boolean);
      if(torrent){camera={x:370,y:310,width:1257,height:704};}else if(locations.length){const xs=locations.map(p=>p[0]),ys=locations.map(p=>p[1]),cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2,width=Math.min(1997,Math.max(891.4375,Math.max(...xs)-Math.min(...xs)+100,(Math.max(...ys)-Math.min(...ys)+70)*1997/1118)),height=width*1118/1997;camera={x:Math.max(0,Math.min(1997-width,cx-width/2)),y:Math.max(0,Math.min(1118-height,cy-height/2)),width,height};}
      const radius=12*camera.width/Math.max(700,host.clientWidth),position=id=>{const u=(replay.units||[]).find(u=>u.actorID===id),p=u&&MechanicWorkbench.trackPosition(u,cursor,replay.interpolateMaxGapMs);return p?twinMapPoint([p.x,p.y]):null;};
      const heads=areaHeads.map(head=>{
        const p=twinBroodPoint(head),born=head.spawnTimeMs??head.timeMs;if(!p||cursor<born||head.endTimeMs!=null&&cursor>=head.endTimeMs+900)return '';
        const begin=(head.castWindows||[]).findLast(w=>w.type==='begincast'&&w.timeMs<=cursor)?.timeMs??born,kick=(head.interrupts||[]).findLast(k=>k.timeMs<=cursor&&k.timeMs>=begin),leak=(head.successTimesMs||[]).findLast(t=>t<=cursor&&t>=begin),age=kick?cursor-kick.timeMs:0;
        if(kick&&age>=900)return '';
        const outcome=kick?'已打断':leak!=null?'漏断':'读条中',color=kick?'#74e5c0':leak!=null?'#fb7185':'#ffd287',left=head.position.side==='left',x=p[0]+(left?-24:24),spawn=Math.min(1,(cursor-born)/500);
        const gone=kick?age:head.endTimeMs!=null&&cursor>=head.endTimeMs?cursor-head.endTimeMs:null;
        return `<g data-key="head:${head.actorID}:${head.instance}" >${spawn<1?`<circle cx="${p[0]}" cy="${p[1]}" r="${18+(1-spawn)*30}" fill="none" stroke="${color}" opacity="${1-spawn}" stroke-width="3"/>`:''}${twinPortrait('head-avatar:'+head.actorID+':'+head.instance,p,radius,'/assets/raids/venomous_abyss/portraits/146494.png',color,gone,head.position.label+' '+outcome)}<text x="${x}" y="${p[1]+4}" text-anchor="${left?'end':'start'}" style="font-size:16px;stroke-width:4px">${esc(head.position.label+' '+outcome)}</text>${kick?`<text x="${x}" y="${p[1]+23}" text-anchor="${left?'end':'start'}" style="font-size:14px;stroke-width:4px">${esc(kick.player?.player)}</text>`:''}</g>`;
      }).join('');
      const bossPoints=Object.fromEntries(bosses.map((b,i)=>{
        let p=position(b.actorID);if(area&&!torrent){const sides=Object.entries(area.bosses||{}),nearest=p&&sides.map(([side,world])=>[side,twinMapPoint(world)]).sort((a,z)=>Math.hypot(a[1][0]-p[0],a[1][1]-p[1])-Math.hypot(z[1][0]-p[0],z[1][1]-p[1]))[0];if(nearest&&Math.hypot(nearest[1][0]-p[0],nearest[1][1]-p[1])<50)p=twinPlatformAnchor(arenaKey,'bosses',nearest[0]);}
        if(!p&&area){const side=i?'right':'left';p=twinPlatformAnchor(arenaKey,'bosses',side);}return [b.actorID,p];
      }));
      const bossDots=bosses.map(b=>{const p=bossPoints[b.actorID];if(!p)return '';const red=b.gameID===257368,color=red?'#ff5e72':'#8bdca8',died=(b.states||[]).findLast(s=>s[0]<=cursor&&s[1]==='dead')||(b.health||[]).find(h=>h[1]===0&&h[0]<=cursor),portrait=TWIN_BOSS_PORTRAITS[red?'Ithraz':'Vexhul'];return twinPortrait('boss:'+b.actorID,p,radius*1.8,portrait.image,color,died?cursor-died[0]:null,b.name);}).join('');
      const flood=torrent&&torrent.rotationDirection&&torrent.angularSpeedDegrees?(()=>{const p=bossPoints[torrent.actorID],angle=torrent.initialAngleRadians+torrent.rotationDirection*torrent.angularSpeedDegrees*Math.PI/180*(cursor-torrent.startTimeMs)/1000;return p?twinBeam('vile-flood',p,[p[0]+Math.cos(angle)*1200,p[1]-Math.sin(angle)*1200],'#b7fa79',cursor)+`<text x="${p[0]}" y="${p[1]-36}" text-anchor="middle" style="font-size:16px">邪恶洪流 · ${torrent.rotationDirection>0?'逆时针':'顺时针'}</text>`:'';})():torrent?'<text x="998" y="600" text-anchor="middle" style="font-size:18px">邪恶洪流 · 旋转方向待确认</text>':'';
      const tankBeams=(feedback.channels||[]).filter(c=>cursor>=c.startTimeMs&&cursor<c.endTimeMs).map(c=>twinBeam('channel:'+c.actorID,bossPoints[c.actorID],position(c.targetID),c.spellID===1289192?'#b4f48a':'#ff8c9c',cursor)).join('');
      const strikers=(feedback.strikers||[]).map(h=>{if(!h.position||cursor<h.spawnTimeMs||h.endTimeMs!=null&&cursor>=h.endTimeMs+900)return '';const p=twinPlatformAnchor(h.arena,'heads',h.slot)||twinMapPoint([h.position.x,h.position.y]),cast=(h.casts||[]).findLast(c=>c.startTimeMs<=cursor&&c.endTimeMs!=null&&cursor<c.endTimeMs+550),aim=cast&&(cast.targetPosition?twinMapPoint([cast.targetPosition.x,cast.targetPosition.y]):position(cast.targetID)),firing=cast&&cursor>=cast.endTimeMs;return `<g data-key="striker:${h.key}">${cast?twinBeam('spit-ray:'+h.key,p,aim,firing?'#ddffaf':'#ffde9e',cursor,!firing):''}${twinPortrait('striker-avatar:'+h.key,p,radius*1.3,'/assets/raids/venomous_abyss/portraits/143971.png','#e7b4ff',h.endTimeMs!=null&&cursor>=h.endTimeMs?cursor-h.endTimeMs:null,'转火蛇头')}${cast?`<rect x="${p[0]-18}" y="${p[1]+radius*1.3+7}" width="36" height="4" rx="2" fill="#28344a"/><rect x="${p[0]-18}" y="${p[1]+radius*1.3+7}" width="${firing?36:36*(cursor-cast.startTimeMs)/(cast.endTimeMs-cast.startTimeMs)}" height="4" rx="2" fill="#f8d79b"/>`:''}</g>`;}).join('');
      const feast=(boss().feast?.rounds||[]).find(r=>cursor>=r.timeMs-4000&&cursor<Math.max(r.timeMs+5000,...(r.strikes||[]).map(s=>s.timeMs+900))),redBoss=bosses.find(b=>b.gameID===257368),redPoint=redBoss&&bossPoints[redBoss.actorID];
      const firstStrike=feast?.strikes?.find(s=>s.participants?.length>0&&s.participants.length<=5)||feast?.strikes?.[0],soakSamples=(firstStrike?.participants||[]).map(person=>{const unit=(replay.units||[]).find(u=>u.actorID===person.playerID),point=unit&&MechanicWorkbench.trackPosition(unit,firstStrike.timeMs,replay.interpolateMaxGapMs);return point?twinMapPoint([point.x,point.y]):null;}).filter(Boolean);
      const median=values=>values.sort((a,b)=>a-b)[Math.floor(values.length/2)],soakPoint=soakSamples.length>=3?[median(soakSamples.map(p=>p[0])),median(soakSamples.map(p=>p[1]))]:redPoint?[redPoint[0],redPoint[1]+160]:null;
      const soak=feast&&soakPoint?`<g data-key="feast-area"><title>分摊中心参考本轮实际命中玩家，范围半径约 8 码</title><circle cx="${soakPoint[0]}" cy="${soakPoint[1]}" r="50" fill="#fb526c" fill-opacity=".16" stroke="#ff8198" stroke-width="3" stroke-dasharray="8 6"/><text x="${soakPoint[0]}" y="${soakPoint[1]+65}" text-anchor="middle" style="font-size:14px">贪婪盛宴 · 约 8 码</text></g>`:'';
      const walls=(feedback.bulwarks||[]).map(w=>{if(!w.position||cursor<w.spawnTimeMs||w.endTimeMs!=null&&cursor>=w.endTimeMs+900)return '';const p=twinMapPoint([w.position.x,w.position.y]),gone=w.endTimeMs!=null&&cursor>=w.endTimeMs,age=gone?(cursor-w.endTimeMs)/900:0;
        const attacks=(w.attacks||[]).filter(a=>cursor>=a.timeMs&&cursor-a.timeMs<350).map(a=>{const from=position(a.playerID);return from?`<path d="M ${from[0]} ${from[1]} L ${p[0]} ${p[1]}" stroke="#8de9ff" stroke-width="3" opacity="${1-(cursor-a.timeMs)/350}"/>`:'';}).join('');
        return `<g data-key="wall:${w.key}" opacity="${1-age}"><circle cx="${p[0]}" cy="${p[1]}" r="${gone?16+age*38:16}" fill="#d8f6aa" fill-opacity=".15" stroke="${gone?'#fff7b0':'#badc66'}" stroke-width="3"/>${gone?`<text x="${p[0]}" y="${p[1]-25}" text-anchor="middle" style="font-size:14px">${esc(w.breaker?.player||'')} 壁垒击破</text>`:''}${attacks}</g>`;
      }).join('');
      const hitIDs=new Set((feedback.hits||[]).filter(h=>cursor>=h.timeMs&&cursor-h.timeMs<650).map(h=>h.playerID)),players=(replay.units||[]).filter(u=>u.kind==='player').map(u=>{const life=MechanicWorkbench.lifeState(u,cursor),point=MechanicWorkbench.trackPosition(u,life.positionTime,replay.interpolateMaxGapMs),p=point&&twinMapPoint([point.x,point.y]),badge=radius*1.55;if(!p||!life.opacity)return '';const auras=(feedback.immunities||[]).filter(a=>a.playerID===u.actorID&&cursor>=a.startTimeMs&&cursor<a.endTimeMs),badges=auras.map((a,i)=>`<g transform="translate(${p[0]+(i-(auras.length-1)/2)*(badge+2)} ${p[1]-radius-badge/2-5})"><title>${esc(a.spell)}</title><rect x="${-badge/2-1}" y="${-badge/2-1}" width="${badge+2}" height="${badge+2}" rx="4" fill="#164571" stroke="#d5edff"/><image href="/assets/spells/${a.spellID}.jpg" x="${-badge/2}" y="${-badge/2}" width="${badge}" height="${badge}"/></g>`).join('');
        const controls=(feedback.controls||[]).filter(c=>c.playerID===u.actorID&&cursor>=c.timeMs&&cursor-c.timeMs<1200).map(c=>`<g><title>${esc(c.spell)}</title><image href="/assets/spells/${c.spellID}.jpg" x="${p[0]-radius-badge-5}" y="${p[1]-badge/2}" width="${badge}" height="${badge}"/><text x="${p[0]}" y="${p[1]+radius+20}" text-anchor="middle" style="fill:#ffe6a1;font-size:14px">${esc(c.spell)}</text></g>`).join('');
        const strike=feast?.strikes?.findLast(s=>s.timeMs<=cursor&&cursor-s.timeMs<900),notHit=auras.length&&strike&&!strike.participants?.some(person=>person.playerID===u.actorID),cue=notHit?`<circle cx="${p[0]}" cy="${p[1]}" r="${radius+7}" fill="none" stroke="#ffc766" stroke-width="3"/><text x="${p[0]}" y="${p[1]+radius+35}" text-anchor="middle" style="fill:#ffc766;font-size:12px">未见本段分摊命中</text>`:'';
        return MechanicWorkbench.avatar(u,{x:p[0],y:p[1],stale:point.stale},radius,hitIDs.has(u.actorID),life.dead,life.opacity)+`<g data-key="feedback:${u.actorID}" opacity="${life.opacity}">${badges}${controls}${cue}</g>`;
      }).join('');
      return `<div data-key="field" class="mw-map"><svg viewBox="${camera.x} ${camera.y} ${camera.width} ${camera.height}" role="img" aria-label="双牙整场机制回放"><image href="${TWIN_ARENA_IMAGE}" width="1997" height="1118"/><rect width="1997" height="1118" fill="#020617" opacity=".15"/><g data-key="soak">${soak}</g><g data-key="beams">${flood}${tankBeams}</g><g data-key="walls">${walls}</g><g data-key="bosses">${bossDots}</g><g data-key="heads">${heads}</g><g data-key="strikers">${strikers}</g><g data-key="players">${players}</g></svg></div>`;
    }});
  host.insertAdjacentHTML('afterbegin',`<div class="twin-replay-jumps"><label>回放片段<select aria-label="双牙回放片段"><option value="0">完整战斗</option>${(boss().feast?.rounds||[]).map(r=>`<option value="${Math.max(0,r.timeMs-4000)}">贪婪盛宴 #${r.index} · ${esc(r.time)}</option>`).join('')}${(feedback.torrents||[]).map((t,i)=>`<option value="${t.startTimeMs}">邪恶洪流 #${i+1}</option>`).join('')}${[...new Set(rows.map(r=>r.round))].map(no=>`<option value="${Math.min(...rows.filter(r=>r.round===no).map(r=>r.timeMs))}">蛇头召唤 #${no}</option>`).join('')}</select></label></div>`);
  host.querySelector('.twin-replay-jumps select').onchange=e=>workbench.seek(Number(e.target.value));
}
