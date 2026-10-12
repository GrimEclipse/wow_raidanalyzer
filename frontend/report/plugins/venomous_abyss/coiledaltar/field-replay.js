/* Coiled Altar owns its object lifetimes and mechanic effects. */
(function(root){
  'use strict';
  function orbSpawnStart(round){const times=(round?.spawns||[]).filter(s=>!s.dropRespawn&&Number.isFinite(s.spawnTimeMs)).map(s=>s.spawnTimeMs);return times.length?Math.min(...times):round.timeMs;}
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
      if(first?.kind==='carried'&&first.position){const round=(venom.rounds||[]).findLast(r=>r.timeMs<=first.start);if(round)orb.states.unshift({start:Math.min(first.start,orbSpawnStart(round)),end:first.start,kind:'ground',position:first.position,inferred:true});}
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
          if(round&&s.position)segment.states.push({start:Math.min(s.start,orbSpawnStart(round)),end:s.start,kind:'ground',position:s.position,inferred:true});
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
  function lastSample(rows,t){let lo=0,hi=rows.length;while(lo<hi){const m=(lo+hi)>>1;if(rows[m][0]<=t)lo=m+1;else hi=m;}return lo-1;}
  function facingAt(unit,t){const rows=unit?.facingSamples||[],i=lastSample(rows,t);if(i<0)return null;return {angle:rows[i][1]/100,stale:t-rows[i][0]>1000};}
  function carryHistory(venom){
    const history=new Map(),seen=new Set();
    for(const row of [...(venom.carriers||[]),...(venom.pickups||[])]){
      const key=`${row.playerID}:${row.applyTimeMs}:${row.venomKind}`;if(seen.has(key))continue;seen.add(key);
      if(!history.has(row.playerID))history.set(row.playerID,[]);
      history.get(row.playerID).push([row.applyTimeMs,row.venomKind==='virulent-mutation']);
    }
    for(const rows of history.values())rows.sort((a,b)=>a[0]-b[0]);return history;
  }
  function carryCounts(rows,t){let small=0,large=0;for(const [time,big] of rows||[]){if(time>t)break;if(big)large++;else small++;}return {small,large};}
  function bombAt(bomb,t,position){
    const end=bomb.explodeTimeMs??bomb.removeTimeMs;if(t<bomb.applyTimeMs||end!=null&&t>=end+700)return null;
    const exploded=bomb.explodeTimeMs!=null&&t>=bomb.explodeTimeMs;
    if(!exploded&&end!=null&&t>=end)return null;
    const p=exploded?bomb.position:position(bomb.playerID,t);if(!p)return null;
    return {point:p,exploded,opacity:exploded?1-(t-bomb.explodeTimeMs)/700:1};
  }
  function ghostAt(ghost,t,trackPosition){
    if(t<ghost.startTimeMs||t>=ghost.endTimeMs+900)return null;
    const at=Math.min(t,ghost.endTimeMs-1),i=lastSample(ghost.samples,at),s=ghost.samples[i];if(!s)return null;
    const point=trackPosition(ghost,at,1000);if(!point)return null;
    return {point,targetID:s[3],moving:!!s[4],facingKnown:!!s[5],opacity:t<ghost.endTimeMs?1:1-(t-ghost.endTimeMs)/900};
  }
  function soulcoilerAt(npc,t,api){
    if(t<npc.startTimeMs||t>=npc.endTimeMs+900)return null;
    const life=api.lifeState(npc,t),at=life.positionTime,rows=npc.samples||[],i=lastSample(rows,at);
    if(i<0||!life.opacity)return null;
    let p=api.trackPosition(npc,at,5000),a=rows[i],b=rows[i+1];
    if(b&&Math.hypot(b[1]-a[1],b[2]-a[2])>800){const tp=(npc.teleports||[]).find(time=>a[0]<time&&time<=b[0]);p=tp!=null&&at>=tp?{x:b[1],y:b[2]}:{x:a[1],y:a[2]};}
    const cast=life.dead?undefined:(npc.casts||[]).findLast(c=>c.startTimeMs<=t&&t<c.endTimeMs),interrupt=(npc.casts||[]).findLast(c=>c.outcome==='interrupted'&&c.endTimeMs<=t&&t-c.endTimeMs<800),hp=npc.health?.[lastSample(npc.health||[],t)],shield=npc.shield?.[lastSample(npc.shield||[],t)]?.[1]||0;
    return {point:p,cast,interrupt,shield,health:hp?hp[1]/hp[2]*100:null,life};
  }
  function mount(host,mechanics,durationMs,project){
    const api=root.MechanicWorkbench,replay=mechanics.combatReplay||{},arena=mechanics.fieldAudit?.arena||{},cones=[...(mechanics.sever?.rounds||[]),...(mechanics.soulSever?.rounds||[]),...(mechanics.blightedSever?.rounds||[])],orbs=orbTracks(mechanics.toxicDeluge||{},cones,mechanics.phaseTimeline||[]),runouts=[...(mechanics.guillotine?.rounds||[]),...(mechanics.grimGuillotine?.rounds||[])];
    const world=id=>replay.units?.find(u=>u.actorID===id),position=(id,t)=>{const u=world(id);return u&&api.trackPosition(u,t,replay.interpolateMaxGapMs);},point=p=>{const q=p&&project(p);return q&&{x:q.x*19.97,y:q.y*11.18};},scale=(arena.unitsPerYard||100)/(arena.radius||5500)*(arena.plotScaleX||25.9389)*19.97;
    const ghosts=mechanics.manifestReplay?.ghosts||[],echoes=mechanics.manifestReplay?.resonanceCollisions||[],coilers=mechanics.soulcoilerReplay?.actors||[],bombs=(mechanics.gloombomb?.rounds||[]).flatMap(r=>r.targets||[]),history=carryHistory(mechanics.toxicDeluge||{});
    const events=[{id:'start',timeMs:0,label:'战斗开始',layer:'全场'}];
    for(const orb of orbs)for(const s of orb.states)events.push({id:`orb:${orb.id}:${s.start}`,timeMs:s.start,label:s.kind==='carried'?'拾取毒液':'毒液落地',layer:'毒液搬运'});
    for(const c of cones)events.push({id:`cone:${c.spellID}:${c.timeMs}`,timeMs:coneWindow(c,replay.bosses?.flatMap(b=>b.casts||[])||[]).start,label:c.label||'撕裂',layer:'头前预兆'});
    for(const r of runouts)events.push({id:`runout:${r.timeMs}`,timeMs:r.timeMs-3500,label:'处斩分摊',layer:'分摊与跑离'});
    for(const b of bombs)events.push({id:`bomb:${b.playerID}:${b.applyTimeMs}`,timeMs:b.applyTimeMs,label:'幽暗炸弹点名',layer:'炸弹'});
    for(const g of ghosts)events.push({id:`ghost:${g.key}`,timeMs:g.startTimeMs,label:'恐惧具象凝视',layer:'具象追踪'});
    for(const e of echoes)events.push({id:`echo:${e.timeMs}`,timeMs:e.timeMs,label:'恶毒共鸣',layer:'具象碰撞'});
    const wb=api.mount(host,{key:'coiledaltar-replay',combatReplay:replay,durationMs,events},{video:true,handlesPlayers:true,project,renderMap(_selected,_filtered,cursor){
      const activeOrbs=orbs.map(o=>{const state=orbAt(o,cursor,position),q=state&&point(state.point);if(!q)return '';const carried=state.kind==='carried',big=o.kind==='virulent-mutation',r=big?18:carried?9:13,x=q.x+(carried?19:0),y=q.y-(carried?19:0),color=o.kind==='virulent-mutation'?'#c782ff':'#8bea96';return `<g data-key="orb:${o.id}" opacity="${state.opacity}"><title>${state.inferred?'生成点由首次拾取位置估算':carried?'正在搬运':'地面毒液'}</title>${big?`<circle data-effect="mutation-radius" pointer-events="none" cx="${q.x}" cy="${q.y}" r="${8*scale}" fill="#b889ff" fill-opacity=".075" stroke="#c694ff" stroke-width="2"/>`:""}${carried?`<path d="M ${q.x} ${q.y} L ${x} ${y}" stroke="${color}" stroke-width="2"/>`:''}<circle cx="${x}" cy="${y}" r="${r+7}" fill="${color}" opacity=".13"/><circle cx="${x}" cy="${y}" r="${r}" fill="#143b27" stroke="${color}" stroke-width="2"/><image href="/boss_plugins/assets/poison_orb.png" x="${x-r}" y="${y-r}" width="${r*2}" height="${r*2}" style="clip-path:circle(50%);${big?'filter:hue-rotate(105deg)':''}"/></g>`;}).join('');
      const coneEffects=cones.map(row=>{const w=coneWindow(row,replay.bosses?.flatMap(b=>b.casts||[])||[]);if(cursor<w.start||cursor>=w.end)return '';const origin=position(row.casterID,Math.min(cursor,row.timeMs))||row.origin,facing=row.facingRadians;if(!origin||facing==null)return '';const warning=cursor<row.timeMs,radius=(row.coneRadiusYards||35)*(arena.unitsPerYard||100),half=(row.coneHalfAngleDeg||30)*Math.PI/180,points=[origin];for(let i=0;i<=24;i++){const a=facing-half+2*half*i/24;points.push({x:origin.x+Math.cos(a)*radius,y:origin.y-Math.sin(a)*radius});}const qs=points.map(point);if(qs.some(q=>!q))return '';const path='M '+qs.map(q=>`${q.x} ${q.y}`).join(' L ')+' Z',f=(cursor-w.start)/(row.timeMs-w.start||1);return `<g data-key="cone:${row.spellID}:${row.timeMs}"><path d="${path}" fill="${warning?'#ffb551':'#fff0b0'}" fill-opacity="${warning?.12+.16*f:.6*(1-(cursor-row.timeMs)/650)}" stroke="#ffd080" stroke-width="${warning?2:4}" ${warning?'stroke-dasharray="12 7"':''}/></g>`;}).join('');
      const runoutEffects=runouts.map(row=>{const w=runoutWindow(row);if(cursor<w.start||cursor>=w.end)return '';const q=point(row.shareCentroid);if(!q)return '';const r=50*scale,progress=(cursor-w.start)/6000;return `<g data-key="runout:${row.timeMs}"><circle cx="${q.x}" cy="${q.y}" r="${r}" fill="#ff8d53" fill-opacity=".1" stroke="#ffbd79" stroke-width="3"/><circle cx="${q.x}" cy="${q.y}" r="${r}" fill="none" stroke="#ffedb0" stroke-width="7" stroke-dasharray="${2*Math.PI*r*progress} ${2*Math.PI*r}" transform="rotate(-90 ${q.x} ${q.y})"/></g>`;}).join('');
      const bossAvatars=(replay.bosses||[]).map(b=>{const u=world(b.actorID),life=api.lifeState(b,cursor),q=point(u&&api.trackPosition(u,life.positionTime,replay.interpolateMaxGapMs));if(!q||!life.opacity)return '';const image=b.portrait||(b.name?.includes('Zul')?"/boss_plugins/assets/Zul'jan.png":'/boss_plugins/assets/HexLord_Malacrass.png');return `<g data-key="boss:${b.actorID}" opacity="${life.opacity}"><circle cx="${q.x}" cy="${q.y}" r="36" fill="#102036" stroke="#ffb97e" stroke-width="2"/><image href="${image}" x="${q.x-35}" y="${q.y-35}" width="70" height="70" style="clip-path:circle(50%)"/></g>`;}).join('');
      const bombEffects=bombs.map(b=>{const state=bombAt(b,cursor,position),q=state&&point(state.point);if(!q)return '';const r=15*scale;
        return `<g data-key="bomb:${b.playerID}:${b.applyTimeMs}" data-effect="${state.exploded?'bomb-impact':'bomb-follow'}" opacity="${state.opacity}"><circle cx="${q.x}" cy="${q.y}" r="${r}" fill="#eebc57" fill-opacity="${state.exploded?.26:.07}" stroke="#ffd374" stroke-width="${state.exploded?5:2}"/>${state.exploded?'':`<path d="M ${q.x-7} ${q.y-34} l 7 -9 7 9 -7 9 Z" fill="#ffd374"/>`}</g>`;
      }).join('');
      const ghostEffects=ghosts.map(g=>{const s=ghostAt(g,cursor,api.trackPosition),q=s&&point(s.point);if(!q)return '';const target=point(position(s.targetID,cursor)),color=s.moving?'#f6a48c':'#a99ad8';return `<g data-key="ghost:${g.key}" data-effect="manifestation" opacity="${s.opacity*(s.facingKnown?1:.55)}"><title>${api.escape(world(s.targetID)?.name||'恐惧具象')}，${s.facingKnown?s.moving?'追踪中':'停止移动':'面向采样缺失，位置待确认'}；移动和消失位置为推算</title>${target?`<path d="M ${q.x} ${q.y} L ${target.x} ${target.y}" pointer-events="none" stroke="${color}" stroke-width="2" opacity=".35" stroke-dasharray="8 8" stroke-dashoffset="${s.moving?-(cursor*.025)%16:0}"/>`:''}<circle cx="${q.x}" cy="${q.y}" r="11" fill="#17172c" stroke="${color}" stroke-width="2"/><image href="/boss_plugins/assets/Manifestation_Dread.png" x="${q.x-9}" y="${q.y-9}" width="18" height="18" style="clip-path:circle(50%)"/><circle cx="${q.x}" cy="${q.y}" r="2" fill="#fff"/></g>`;}).join('');
      const coilerEffects=coilers.map(npc=>{const s=soulcoilerAt(npc,cursor,api),q=s&&point(s.point);if(!q)return '';const c=s.cast,progress=c?Math.max(0,Math.min(1,(cursor-c.startTimeMs)/(c.endTimeMs-c.startTimeMs||1))):0;
        const bar=c?`<g data-effect="soulcoiler-cast" transform="translate(${q.x-120} ${q.y-70})" pointer-events="none"><rect width="240" height="30" rx="5" fill="#09111f" stroke="#e9bd65" stroke-width="2"/><rect x="3" y="3" width="${234*progress}" height="24" rx="3" fill="#bd9448" opacity=".6"/><text x="120" y="21" text-anchor="middle" style="font:18px system-ui;fill:#fff">恐惧哀嚎</text></g>`:'';
        return `<g data-key="coiler:${npc.key}" data-effect="soulcoiler" opacity="${s.life.opacity}">${api.avatar({...npc,key:'coiler:'+npc.key,name:'怨毒盘魂者',color:'#dbb1ff'},q,25,!!s.interrupt,s.life.dead,s.life.opacity)}${s.shield?`<circle cx="${q.x}" cy="${q.y}" r="32" fill="none" stroke="#b3cbff" stroke-width="3" stroke-dasharray="${s.shield===2?'':'10 10'}"/>`:''}${s.health!=null?`<rect x="${q.x-32}" y="${q.y+35}" width="64" height="6" rx="3" fill="#111928"/><rect x="${q.x-32}" y="${q.y+35}" width="${64*s.health/100}" height="6" rx="3" fill="#cf8ae5"/>`:''}${bar}${s.interrupt?.interruptIcon?`<image data-effect="soulcoiler-interrupt" href="${api.escape(s.interrupt.interruptIcon)}" x="${q.x+17}" y="${q.y-45}" width="22" height="22"/>`:''}</g>`;
      }).join('');
      const echoEffects=echoes.filter(e=>e.contactPosition&&cursor>=e.timeMs&&cursor-e.timeMs<900).map(e=>{const q=point(e.contactPosition),f=(cursor-e.timeMs)/900;return q?`<g data-effect="resonance-impact"><circle cx="${q.x}" cy="${q.y}" r="${10+f*70}" fill="#ff668a" fill-opacity="${.4*(1-f)}" stroke="#ff9cca" stroke-width="4" opacity="${1-f}"/></g>`:'';}).join('');
      const avatars=(replay.units||[]).filter(u=>u.kind==='player').map(u=>{const life=api.lifeState(u,cursor),p=api.trackPosition(u,life.positionTime,replay.interpolateMaxGapMs),q=point(p);if(!q||!life.opacity)return '';
        const counts=carryCounts(history.get(u.actorID),cursor),face=facingAt(u,life.positionTime),tip=`${u.name}\n已搬运小球 ${counts.small} 次，大球 ${counts.large} 次`,hit=echoes.some(e=>e.playerIDs.includes(u.actorID)&&cursor>=e.timeMs&&cursor-e.timeMs<600)||bombs.some(b=>b.playerID===u.actorID&&b.explodeTimeMs!=null&&cursor>=b.explodeTimeMs&&cursor-b.explodeTimeMs<400);
        const arrow=face&&!life.dead?`<path data-effect="player-facing" d="M 22 -5 L 34 0 L 22 5 Z" fill="${face.stale?'#89939d':u.color}" stroke="#0a1020" stroke-width="1.5" transform="translate(${q.x} ${q.y}) rotate(${face.angle*180/Math.PI})" opacity="${face.stale?.4:.9}"/>`:'';
        return `${arrow}${api.avatar({...u,name:tip},{...q,stale:p.stale},17,hit,life.dead,life.opacity)}`;
      }).join('');
      return `<div class="mw-map" data-replay-field><svg viewBox="0 0 1997 1118" role="img" aria-label="盘卷祭坛连续战斗回放"><image href="/assets/raids/venomous_abyss/07-coiledaltar.jpg" width="1997" height="1118"/><g data-key="hazards" pointer-events="none">${coneEffects}${runoutEffects}${bombEffects}${echoEffects}</g><g data-key="ghosts">${ghostEffects}</g><g data-key="coilers">${coilerEffects}</g><g data-key="bosses">${bossAvatars}</g><g data-key="players">${avatars}</g><g data-key="orbs" pointer-events="none">${activeOrbs}</g></svg></div>`;
    }});
    host.insertAdjacentHTML('afterbegin',`<label>回放片段<select aria-label="盘卷祭坛回放片段"><option value="0">完整战斗</option>${cones.map(c=>`<option value="${Math.max(0,c.timeMs-3000)}">${api.escape(c.label||'撕裂')}，${api.escape(c.time)}</option>`).join('')}${runouts.map(r=>`<option value="${Math.max(0,r.timeMs-3500)}">处斩，${api.escape(r.time)}</option>`).join('')}</select></label>`);host.querySelector('select[aria-label="盘卷祭坛回放片段"]').onchange=e=>wb.seek(Number(e.target.value));
    return wb;
  }
  root.CoiledAltarReplay={orbTracks,orbAt,coneWindow,runoutWindow,facingAt,carryHistory,carryCounts,bombAt,ghostAt,soulcoilerAt,mount};if(typeof module!=='undefined')module.exports=root.CoiledAltarReplay;
})(typeof window==='undefined'?globalThis:window);
