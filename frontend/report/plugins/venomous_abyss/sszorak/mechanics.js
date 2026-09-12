/* Sszorak-only mechanic views. Data adjudication stays in the Boss module. */
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
  return `<section class="panel" data-analysis-option="serpentsFuryReviewEnabled"><h2>毒蛇之怒 · 怒满时未进印记</h2>
    <p class="muted">印记需要至少 ${data.requiredPlayers} 人进入 ${data.radiusYards} 码范围触发。${esc(data.evidenceNote)}</p><p>怒满狂暴 ${data.enrageCount || 0} 次 · 豁免 ${data.exemptCount || 0} 次</p>
    ${table(['玩家', '未进圈次数'], (data.players || []).map(row => [player(row), row.count]))}
    ${(data.events || []).map(row => `<article class="card"><h3>${esc(row.time)} · ${esc(row.status)}</h3>
      <p>印记目标：${player(row.markTarget)} · 结算前死亡：${row.deadCount} 人</p>
      ${row.exempt ? '' : `<p>圈外非治疗：${outside(row.outsidePlayers)}</p><p>圈内非治疗：${players(row.insidePlayers)}</p><p>坐标未确认：${players(row.unknownPlayers)}</p>`}
      <p class="muted">排除治疗：${players(row.excludedHealers)}</p></article>`).join('')}
    ${!(data.events || []).length ? '<div class="empty">本场没有符合条件的怒满狂暴记录。</div>' : ''}</section>`;
}
