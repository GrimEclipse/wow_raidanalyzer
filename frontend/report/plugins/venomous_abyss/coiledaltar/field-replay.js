/* Coiled Altar owns its object lifetimes and mechanic effects. */
(function(root){
  'use strict';
  function orbTracks(venom,clears=[],phaseTimeline=[]){
    const groups=new Map(),rows=(venom.carriers||[]).map(r=>({...r}));
    for(const p of venom.pickups||[])if(!rows.some(c=>c.playerID===p.playerID&&c.applyTimeMs===p.applyTimeMs))rows.push({...p});
    for(const p of venom.groundPuddles||[])for(const c of p.carriers||[]){const row=rows.find(r=>r.playerID===c.playerID&&r.applyTimeMs===c.applyTimeMs);if(row&&!row.pickupPosition)row.pickupPosition=c.pickupPosition;}
    for(const row of rows){const id=row.puddleID??`${row.playerID}:${row.applyTimeMs}`;if(!groups.has(id))groups.set(id,{id,kind:row.venomKind,states:[]});const orb=groups.get(id);
      orb.states.push({start:row.applyTimeMs,end:row.removeTimeMs??Infinity,kind:'carried',actorID:row.playerID,position:row.pickupPosition});
      if(row.removeTimeMs!=null&&row.dropPosition)orb.states.push({start:row.removeTimeMs,end:Infinity,kind:'ground',position:row.dropPosition});
    }
    for(const p of venom.groundPuddles||[]){if(!groups.has(p.puddleID))groups.set(p.puddleID,{id:p.puddleID,kind:p.venomKind,states:[]});if(p.groundedFromMs!=null&&p.position)groups.get(p.puddleID).states.push({start:p.groundedFromMs,end:p.pickedUpAtMs??Infinity,kind:'ground',position:p.position});}
    const output=[],phaseClears=phaseTimeline.filter(p=>p.key==='p2').map(p=>p.timeMs);
    for(const orb of groups.values()){
      // A pickup/drop replaces the previous state, including old snapshots
      // whose backend end is unknown. Never resurrect an earlier ground state.
      orb.states.sort((a,b)=>a.start-b.start||(a.kind==='carried'?1:-1));
      orb.states=orb.states.filter((s,i,all)=>!all.slice(i+1).some(t=>t.start===s.start));
      const first=orb.states[0];
      if(first?.kind==='carried'&&first.position){const round=(venom.rounds||[]).findLast(r=>r.timeMs<=first.start);if(round)orb.states.unshift({start:round.timeMs,end:first.start,kind:'ground',position:first.position,inferred:true});}
      const clearTimes=[...phaseClears,...clears.filter(r=>(r.targetsInCone||[]).some(t=>t.puddleID===orb.id)).map(r=>r.timeMs)].sort((a,b)=>a-b);
      let segment={...orb,id:`${orb.id}:0`,puddleID:orb.id,states:[],clearTime:Infinity},generation=0,lastClear=-Infinity;
      for(let i=0;i<orb.states.length;i++){
        const s={...orb.states[i]},next=orb.states[i+1];s.end=Math.min(s.end,next?.start??Infinity);
        if(s.start<=lastClear)continue;
        if(segment.clearTime<Infinity){
          // Spatial matching can reuse a consumed puddle ID in a later round.
          // Only a new observed pickup can establish a new lifetime.
          if(s.kind!=='carried')continue;
          output.push(segment);segment={...orb,id:`${orb.id}:${++generation}`,puddleID:orb.id,states:[],clearTime:Infinity};
          const round=(venom.rounds||[]).findLast(r=>r.timeMs>lastClear&&r.timeMs<=s.start);
          if(round&&s.position)segment.states.push({start:round.timeMs,end:s.start,kind:'ground',position:s.position,inferred:true});
        }
        segment.states.push(s);
        const clear=clearTimes.find(t=>t>=s.start&&t<s.end&&(s.kind==='ground'||phaseClears.includes(t)));
        if(clear!=null){segment.clearTime=clear;lastClear=clear;s.end=clear;}
      }
      if(segment.states.length)output.push(segment);
    }
    return output;
  }
  function orbAt(orb,cursor,position){
    if(cursor>=orb.clearTime+900)return null;
    const sampleTime=Math.min(cursor,orb.clearTime-.001),state=orb.states.findLast(s=>s.start<=sampleTime&&sampleTime<s.end);if(!state)return null;
    const point=state.kind==='carried'?position(state.actorID,sampleTime)||state.position:state.position;if(!point)return null;
    return {...state,point,opacity:cursor>=orb.clearTime?Math.max(0,1-(cursor-orb.clearTime)/900):1};
  }
  function coneWindow(row,casts){const cast=casts.find(c=>c.spellID===row.spellID&&Math.abs(c.endTimeMs-row.timeMs)<200);return {start:cast?.startTimeMs??row.timeMs-3000,end:row.timeMs+650};}
  function runoutWindow(row){const hits=(row.participants||[]).map(p=>p.shareTimeMs).filter(Number.isFinite),start=hits.length?Math.min(...hits):row.timeMs;return {start,end:start+6000};}
  function mount(host,mechanics,durationMs,project){
    const api=root.MechanicWorkbench,replay=mechanics.combatReplay||{},arena=mechanics.fieldAudit?.arena||{},cones=[...(mechanics.sever?.rounds||[]),...(mechanics.soulSever?.rounds||[]),...(mechanics.blightedSever?.rounds||[])],orbs=orbTracks(mechanics.toxicDeluge||{},cones,mechanics.phaseTimeline||[]),runouts=[...(mechanics.guillotine?.rounds||[]),...(mechanics.grimGuillotine?.rounds||[])];
    const world=id=>replay.units?.find(u=>u.actorID===id),position=(id,t)=>{const u=world(id);return u&&api.trackPosition(u,t,replay.interpolateMaxGapMs);},point=p=>{const q=p&&project(p);return q&&{x:q.x*19.97,y:q.y*11.18};},scale=(arena.unitsPerYard||100)/(arena.radius||5500)*(arena.plotScaleX||25.9389)*19.97;
    const events=[{id:'start',timeMs:0,label:'战斗开始',layer:'全场'}];
    for(const orb of orbs)for(const s of orb.states)events.push({id:`orb:${orb.id}:${s.start}`,timeMs:s.start,label:s.kind==='carried'?'拾取毒液':'毒液落地',layer:'毒液搬运'});
    for(const c of cones)events.push({id:`cone:${c.spellID}:${c.timeMs}`,timeMs:coneWindow(c,replay.bosses?.flatMap(b=>b.casts||[])||[]).start,label:c.label||'撕裂',layer:'头前预兆'});
    for(const r of runouts)events.push({id:`runout:${r.timeMs}`,timeMs:r.timeMs-3500,label:'处斩分摊',layer:'分摊与跑离'});
    const wb=api.mount(host,{key:'coiledaltar-replay',combatReplay:replay,durationMs,events},{video:true,handlesPlayers:true,project,renderMap(_selected,_filtered,cursor){
      const activeOrbs=orbs.map(o=>{const state=orbAt(o,cursor,position),q=state&&point(state.point);if(!q)return '';const carried=state.kind==='carried',r=carried?9:13,x=q.x+(carried?19:0),y=q.y-(carried?19:0),color=o.kind==='virulent-mutation'?'#c782ff':'#8bea96';return `<g data-key="orb:${o.id}" opacity="${state.opacity}"><title>${state.inferred?'生成点由首次拾取位置估算':carried?'正在搬运':'地面毒液'}</title>${carried?`<path d="M ${q.x} ${q.y} L ${x} ${y}" stroke="${color}" stroke-width="2"/>`:''}<circle cx="${x}" cy="${y}" r="${r+7}" fill="${color}" opacity=".13"/><circle cx="${x}" cy="${y}" r="${r}" fill="#143b27" stroke="${color}" stroke-width="2"/><image href="/boss_plugins/assets/poison_orb.png" x="${x-r}" y="${y-r}" width="${r*2}" height="${r*2}" style="clip-path:circle(50%)"/></g>`;}).join('');
      const coneEffects=cones.map(row=>{const w=coneWindow(row,replay.bosses?.flatMap(b=>b.casts||[])||[]);if(cursor<w.start||cursor>=w.end)return '';const origin=position(row.casterID,Math.min(cursor,row.timeMs))||row.origin,facing=row.facingRadians;if(!origin||facing==null)return '';const warning=cursor<row.timeMs,radius=(row.coneRadiusYards||35)*(arena.unitsPerYard||100),half=(row.coneHalfAngleDeg||30)*Math.PI/180,points=[origin];for(let i=0;i<=24;i++){const a=facing-half+2*half*i/24;points.push({x:origin.x+Math.cos(a)*radius,y:origin.y-Math.sin(a)*radius});}const qs=points.map(point);if(qs.some(q=>!q))return '';const path='M '+qs.map(q=>`${q.x} ${q.y}`).join(' L ')+' Z',f=(cursor-w.start)/(row.timeMs-w.start||1);return `<g data-key="cone:${row.spellID}:${row.timeMs}"><path d="${path}" fill="${warning?'#ffb551':'#fff0b0'}" fill-opacity="${warning?.12+.16*f:.6*(1-(cursor-row.timeMs)/650)}" stroke="#ffd080" stroke-width="${warning?2:4}" ${warning?'stroke-dasharray="12 7"':''}/></g>`;}).join('');
      const runoutEffects=runouts.map(row=>{const w=runoutWindow(row);if(cursor<w.start||cursor>=w.end)return '';const q=point(row.shareCentroid);if(!q)return '';const r=50*scale,progress=(cursor-w.start)/6000;return `<g data-key="runout:${row.timeMs}"><circle cx="${q.x}" cy="${q.y}" r="${r}" fill="#ff8d53" fill-opacity=".1" stroke="#ffbd79" stroke-width="3"/><circle cx="${q.x}" cy="${q.y}" r="${r}" fill="none" stroke="#ffedb0" stroke-width="7" stroke-dasharray="${2*Math.PI*r*progress} ${2*Math.PI*r}" transform="rotate(-90 ${q.x} ${q.y})"/></g>`;}).join('');
      const bossAvatars=(replay.bosses||[]).map(b=>{const u=world(b.actorID),life=api.lifeState(b,cursor),q=point(u&&api.trackPosition(u,life.positionTime,replay.interpolateMaxGapMs));if(!q||!life.opacity)return '';const image=b.gameID===257911?"/boss_plugins/assets/Zul'jan.png":'/boss_plugins/assets/HexLord_Malacrass.png';return `<g data-key="boss:${b.actorID}" opacity="${life.opacity}"><circle cx="${q.x}" cy="${q.y}" r="36" fill="#102036" stroke="#ffb97e" stroke-width="2"/><image href="${image}" x="${q.x-35}" y="${q.y-35}" width="70" height="70" style="clip-path:circle(50%)"/></g>`;}).join('');
      const avatars=(replay.units||[]).filter(u=>u.kind==='player').map(u=>{const life=api.lifeState(u,cursor),p=api.trackPosition(u,life.positionTime,replay.interpolateMaxGapMs),q=point(p);return q&&life.opacity?api.avatar(u,{...q,stale:p.stale},17,false,life.dead,life.opacity):'';}).join('');
      return `<div class="mw-map" data-replay-field><svg viewBox="0 0 1997 1118" role="img" aria-label="盘卷祭坛连续战斗回放"><image href="/assets/raids/venomous_abyss/07-coiledaltar.jpg" width="1997" height="1118"/><g data-key="hazards">${coneEffects}${runoutEffects}</g><g data-key="bosses">${bossAvatars}</g><g data-key="players">${avatars}</g><g data-key="orbs">${activeOrbs}</g></svg></div>`;
    }});
    host.insertAdjacentHTML('afterbegin',`<label>回放片段<select aria-label="盘卷祭坛回放片段"><option value="0">完整战斗</option>${cones.map(c=>`<option value="${Math.max(0,c.timeMs-3000)}">${api.escape(c.label||'撕裂')}，${api.escape(c.time)}</option>`).join('')}${runouts.map(r=>`<option value="${Math.max(0,r.timeMs-3500)}">处斩，${api.escape(r.time)}</option>`).join('')}</select></label>`);host.querySelector('select[aria-label="盘卷祭坛回放片段"]').onchange=e=>wb.seek(Number(e.target.value));
    return wb;
  }
  root.CoiledAltarReplay={orbTracks,orbAt,coneWindow,runoutWindow,mount};if(typeof module!=='undefined')module.exports=root.CoiledAltarReplay;
})(typeof window==='undefined'?globalThis:window);
