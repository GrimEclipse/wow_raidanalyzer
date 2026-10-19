/* Presentation helpers for the Coiled Altar guild review. */
((root) => {
  const name = row => String(row.player || row.name || '');
  function sortHoldRows(rows, key='damage', direction='desc') {
    const value = row => key==='player' ? name(row) : key==='playerDamage'
      ? Number(row.damage || 0)-Number(row.petDamage || 0) : Number(row[key] || 0);
    return [...rows].sort((a,b) => {
      const compared = key==='player' ? value(a).localeCompare(value(b),'zh-CN') : value(a)-value(b);
      return compared*(direction==='asc'?1:-1) || Number(b.damage||0)-Number(a.damage||0)
        || Number(b.castCount||0)-Number(a.castCount||0) || name(a).localeCompare(name(b),'zh-CN');
    });
  }
  function groupBurstRows(timelines, roster=[], unresolved=[], scope='dps') {
    const key = row => row.playerID!=null || row.id!=null ? `id:${row.playerID??row.id}` : `name:${name(row)}`;
    const groups = new Map();
    for(const row of roster) groups.set(key(row),{...row,player: name(row),playerID:row.playerID??row.id,skills:[],unresolved:[]});
    const find = row => {
      if(row.playerID!=null||row.id!=null)return groups.get(key(row));
      const matches=[...groups.values()].filter(p=>name(p)===name(row));
      return matches.length===1?matches[0]:undefined;
    };
    for(const row of timelines) {
      let group=find(row);
      if(!group) {group={...row,skills:[],unresolved:[]};groups.set(key(row),group);}
      group.skills.push(row);
    }
    for(const row of unresolved) {const group=find(row);if(group)group.unresolved.push(row);}
    return [...groups.values()].filter(row=>scope==='all'||String(row.role||'').includes('dps')||(!row.role&&row.skills.length))
      .sort((a,b)=>String(a.classColor||'').localeCompare(String(b.classColor||''))||name(a).localeCompare(name(b),'zh-CN'));
  }
  function phaseTimings(data) {
    return (data.phaseTimeline||[]).filter(p=>!['wipe','kill'].includes(p.key)).map(phase=>{
      const saved=(data.phaseTimings||[]).find(p=>p.phase===phase.key);
      const control=(data.phaseControl||[]).find(p=>p.phase===phase.key)||{};
      const shift=(data.checks||[]).find(c=>c.phase===phase.key)?.phaseShiftMs;
      const timing=saved||{startAdvanceMs:Math.max(0,-Number(shift||0)),
        endAdvanceMs:control.endTimeMs==null?0:Math.max(0,Number(control.earliestEndTimeMs)-control.endTimeMs),
        firstDreadmarchAdvanceMs:control.firstDreadmarchTimeMs==null?0:Math.max(0,Number(control.firstDreadmarchEarliestTimeMs)-control.firstDreadmarchTimeMs)};
      const seconds=value=>(value/1000).toFixed(1)+'秒',notes=[];
      if(timing.startAdvanceMs>0)notes.push('起点早'+seconds(timing.startAdvanceMs)+'（相对固定轴）');
      if(timing.endAdvanceMs>0)notes.push('结束早'+seconds(timing.endAdvanceMs)+'（相对本阶段最早结束门槛）');
      if(timing.firstDreadmarchAdvanceMs>0)notes.push('首次恐惧行军早'+seconds(timing.firstDreadmarchAdvanceMs));
      const short=[timing.startAdvanceMs>0?'起点早'+seconds(timing.startAdvanceMs):'',
        timing.endAdvanceMs>0?'结束早'+seconds(timing.endAdvanceMs):'',
        timing.firstDreadmarchAdvanceMs>0?'行军早'+seconds(timing.firstDreadmarchAdvanceMs):''].filter(Boolean).join(' / ');
      return {...phase,...timing,advanceLabel:short,advanceNote:notes.join('；')};
    });
  }
  const api={sortHoldRows,groupBurstRows,phaseTimings};
  root.CoiledAltarGuildView=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
