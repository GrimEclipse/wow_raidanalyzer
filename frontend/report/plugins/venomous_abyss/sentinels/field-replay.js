(function(root){
  'use strict';
  const api=()=>root.MechanicWorkbench;
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  function project(p,arena){
    if(!p)return null;
    const scale=arena.pixelsPerYard/arena.unitsPerYard,angle=(arena.rotationDegrees||0)*Math.PI/180;
    const dx=p.x-arena.centerX,dy=p.y-arena.centerY;
    return {x:arena.width/2+(arena.offsetX||0)+(dx*Math.cos(angle)-dy*Math.sin(angle))*scale,
      y:arena.height/2+(arena.offsetY||0)-(dx*Math.sin(angle)+dy*Math.cos(angle))*scale};
  }
  function mount(host,field,durationMs){
    if(!field?.enabled){host.innerHTML='<div class="empty">这场战斗没有场地推演数据，请重新分析。</div>';return null;}
    const replay=field.combatReplay||{},arena=field.arena,workbench=api();
    const units=new Map((replay.units||[]).map(u=>[u.actorID,u]));
    const unitsByKey=new Map((replay.units||[]).map(u=>[u.key,u]));
    const position=(id,t)=>{const unit=units.get(id);return unit&&workbench.trackPosition(unit,t,replay.interpolateMaxGapMs);};
    const screen=(p)=>project(p,arena);
    const radius=y=>y*arena.pixelsPerYard;
    const marks=[{id:'start',timeMs:0,label:'战斗开始',layer:'全场'}];
    const add=(rows,label,layer)=>rows.forEach((row,i)=>marks.push({id:`${layer}:${i}`,timeMs:row.startTimeMs??row.timeMs,
      label:typeof label==='function'?label(row):label,layer,actor:units.get(row.playerID)?.name||'',spellID:row.spellID}));
    add(field.protovenom||[],'变幻的原型毒液','原型毒液');
    add(field.safeClears||[],'双人安全消毒','原型毒液');
    add(field.eruptions||[],'错误接触击飞','原型毒液');
    add(field.miasma||[],'不稳定瘴气读条前预兆（8 码）','分摊放水');
    add(field.soaks||[],'不稳定瘴气命中','分摊放水');
    add(field.helicalExplosions||[],r=>r.stack?`螺旋毒素 ${r.stack} 层爆炸，${r.radiusYards} 码`:'螺旋毒素爆炸，层数未记录','螺旋毒素');
    add(field.helicalAuras||[],r=>`螺旋毒素撞错后 ${r.stack>99?'∞':r.stack} 层，2 码个人圈`,'螺旋毒素');
    add(field.water||[],r=>r.source==='injection'?`血毒注射消失，${r.radiusYards} 码红水`:'附着幽暗放水','地面红水');
    add(field.droplets||[],'踩绿球，腐蚀长矛生成','绿球长矛');
    (field.droplets||[]).forEach((row,i)=>marks.push({id:`lance-launch:${i}`,timeMs:row.launchTimeMs,
      label:'腐蚀长矛射出',layer:'绿球长矛',actor:units.get(row.playerID)?.name||''}));
    add(field.spearHits||[],'腐蚀长矛命中','绿球长矛');
    (field.slimes||[]).forEach((slime,i)=>marks.push({id:`slime:${i}`,timeMs:slime.startTimeMs,
      label:'软泥刷新（首次可见位置）',layer:'软泥',actor:'软泥',
      evidence:slime.nearbyPlayers.length?`8 码内：${slime.nearbyPlayers.map(p=>`${p.player} ${p.distanceYards} 码`).join('、')}`:'8 码内未找到可靠玩家坐标',
      points:[{position:slime.position,label:'软泥刷新位置'}]}));
    const wb=workbench.mount(host,{key:'sentinels-field',title:'陵寝哨兵 场地推演',combatReplay:replay,
      durationMs,events:marks,note:'橙圈为 5 码示意；双橙圈接触可安全解除，碰到无毒玩家会击飞两人。不稳定瘴气的 8 码预兆在读条前出现并跟随随后被点名的玩家；读条前目标由后续 debuff 回推。附着幽暗结束时放置半径 5 码的红水；血毒注射消失时每层增加 5 码半径。红水从落点以每秒 1 码扩张并持续到战斗结束。螺旋毒素只在撞错后超过 4 层且 buff 仍存在时显示 2 码个人圈；超过 99 层显示 ∞，爆炸范围为 5 × 已记录层数码。长矛原地蓄势 5 秒后迅速射向 Boss。'},
      {video:true,handlesPlayers:true,project:p=>{const q=screen(p);return q&&{x:q.x/arena.width*100,y:q.y/arena.height*100};},
      renderMap(_selected,_filtered,t){
        const circles=(field.protovenom||[]).filter(a=>a.startTimeMs<=t&&t<a.endTimeMs).map(a=>{
          const q=screen(position(a.playerID,t));if(!q)return '';
          return `<circle data-key="venom:${a.playerID}:${a.startTimeMs}" data-effect="protovenom-5yd" cx="${q.x}" cy="${q.y}" r="${radius(a.radiusYards)}" fill="#ffa323" fill-opacity=".1" stroke="#ffc063" stroke-width="3" stroke-dasharray="9 5"/>`;
        }).join('');
        const murk=(field.murk||[]).filter(a=>a.timeMs<=t&&t<a.endTimeMs).map(a=>{
          const q=screen(position(a.playerID,t));if(!q)return '';
          return `<circle data-key="murk:${a.playerID}:${a.timeMs}" data-effect="murk-carrier" cx="${q.x}" cy="${q.y}" r="${radius(5)}" fill="#9b1d36" fill-opacity=".12" stroke="#ff6173" stroke-width="2" stroke-dasharray="4 4"/>`;
        }).join('');
        const miasma=(field.miasma||[]).filter(a=>a.startTimeMs<=t&&t<a.endTimeMs).map(a=>{
          const q=screen(position(a.playerID,t));if(!q)return '';
          const r=radius(a.radiusYards),precast=t<a.auraStartTimeMs;
          const progress=clamp((t-a.startTimeMs)/(a.endTimeMs-a.startTimeMs||1),0,1);
          return `<g data-key="miasma:${a.playerID}:${a.startTimeMs}" data-effect="${precast?'miasma-precast-warning':'miasma-telegraph'}" data-inferred="${a.timingInferred?'true':'false'}"><title>${precast?'读条前点名预兆，目标由随后光环回推':'不稳定瘴气点名'}，8 码</title><circle cx="${q.x}" cy="${q.y}" r="${r}" fill="#ae83e9" fill-opacity="${precast?.08:.12}" stroke="#e7c7ff" stroke-width="3" ${precast?'stroke-dasharray="12 7"':''}/><circle cx="${q.x}" cy="${q.y}" r="${r*(1-progress)}" fill="none" stroke="#f4dfff" stroke-opacity=".6" stroke-width="2"/></g>`;
        }).join('');
        const water=(field.water||[]).filter(a=>a.timeMs<=t&&t<=a.endTimeMs).map((a,i)=>{
          const q=screen(a.position);if(!q)return '';
          const grownYards=clamp((t-a.timeMs)/1000*(a.expansionYardsPerSecond||1),0,a.radiusYards);
          const r=radius(grownYards),fade=clamp((t-a.timeMs)/500,0,1);
          return `<g data-key="pool:${i}" data-effect="${a.source}-water" opacity="${fade}"><circle cx="${q.x}" cy="${q.y}" r="${r}" fill="#d5213c" fill-opacity="${a.source==='injection'?.15:.36}" stroke="#ff5e64" stroke-width="3"/><circle cx="${q.x}" cy="${q.y}" r="${r*.65}" fill="none" stroke="#ff9894" stroke-opacity=".3" stroke-width="2"/></g>`;
        }).join('');
        const lances=(field.droplets||[]).map((d,i)=>{
          if(t<d.timeMs||t>d.launchTimeMs+300)return '';
          const from=screen(d.position),boss=screen(position(d.bossID,Math.min(t,d.launchTimeMs)));
          if(!from||!boss)return '';
          const launched=t>=d.launchTimeMs,age=t-d.launchTimeMs,f=clamp(age/120,0,1);
          const length=Math.hypot(boss.x-from.x,boss.y-from.y)||1,ux=(boss.x-from.x)/length,uy=(boss.y-from.y)/length;
          const tip=launched?{x:from.x+(boss.x-from.x)*f,y:from.y+(boss.y-from.y)*f}:{x:from.x+ux*32,y:from.y+uy*32};
          const fade=launched?clamp(1-(age-120)/180,0,1):1;
          return `<g data-key="lance:${i}" data-effect="${launched?'corrosive-lance-flight':'corrosive-lance-aim'}" opacity="${fade}"><circle cx="${from.x}" cy="${from.y}" r="12" fill="#73f74a" fill-opacity=".4" stroke="#c9ff9c" stroke-width="2"/><path d="M ${from.x} ${from.y} L ${tip.x} ${tip.y}" stroke="#d7ff8a" stroke-width="${launched?7:4}" stroke-linecap="round"/><circle cx="${tip.x}" cy="${tip.y}" r="${launched?8:5}" fill="#e9ffb1"/></g>`;
        }).join('');
        const slimes=(field.slimes||[]).filter(s=>s.startTimeMs<=t&&t<s.endTimeMs+700).map(s=>{
          const unit=unitsByKey.get(s.key),life=unit?workbench.lifeState(unit,t):{opacity:1,positionTime:t};
          const q=screen(unit&&workbench.trackPosition(unit,life.positionTime,replay.interpolateMaxGapMs)||s.position);
          if(!q)return '';
          return `<g data-key="slime:${s.key}" data-effect="venom-coagulation" opacity="${life.opacity}"><title>软泥 · 首次可见 ${Math.floor(s.startTimeMs/1000)} 秒 · 8 码内 ${workbench.escape(s.nearbyPlayers.map(p=>p.player).join('、')||'无人')}</title><circle cx="${q.x}" cy="${q.y}" r="25" fill="#132b1a" fill-opacity=".72" stroke="#96e56e" stroke-width="3"/><image href="/assets/raids/venomous_abyss/02-sentinels-slime.png" x="${q.x-22}" y="${q.y-22}" width="44" height="44"/></g>`;
        }).join('');
        const clears=(field.safeClears||[]).filter(a=>t>=a.timeMs&&t<a.timeMs+650).map((a,i)=>{
          const q=screen(a.position);if(!q)return '';const f=(t-a.timeMs)/650;
          return `<circle data-key="safe:${i}" data-effect="protovenom-safe-clear" cx="${q.x}" cy="${q.y}" r="${15+f*75}" fill="none" stroke="#8df8c1" stroke-width="5" opacity="${1-f}"/>`;
        }).join('');
        const hits=[...(field.eruptions||[]).map(e=>({...e,kind:'knockback'})),...(field.spearHits||[]).map(e=>({...e,kind:'spear'})),...(field.helicalExplosions||[]).map(e=>({...e,kind:'helical'}))];
        const impacted=new Set(hits.filter(e=>t>=e.timeMs&&t<e.timeMs+650).map(e=>e.playerID));
        const avatars=(replay.units||[]).filter(u=>u.kind==='player').map(u=>{
          const life=workbench.lifeState(u,t),q=screen(workbench.trackPosition(u,life.positionTime,replay.interpolateMaxGapMs));
          if(!q||!life.opacity)return '';
          return workbench.avatar(u,{...q,stale:false},17,impacted.has(u.actorID),life.dead,life.opacity);
        }).join('');
        const helical=(field.helicalAuras||[]).filter(a=>a.startTimeMs<=t&&t<a.endTimeMs).map(a=>{
          const q=screen(position(a.playerID,t));if(!q)return '';
          const label=a.stack>99?'∞':a.stack;
          return `<g data-key="helical:${a.playerID}:${a.startTimeMs}" data-effect="helical-stack" aria-label="螺旋毒素 ${label} 层"><circle cx="${q.x}" cy="${q.y}" r="${radius(a.radiusYards)}" fill="#f2a02c" fill-opacity=".14" stroke="#ffd35e" stroke-width="3"/><rect x="${q.x-22}" y="${q.y-49}" width="44" height="24" rx="9" fill="#2d1932" stroke="#ffd35e" stroke-width="2"/><text x="${q.x}" y="${q.y-32}" text-anchor="middle" fill="#fff2bd" style="font:bold 16px system-ui;paint-order:stroke;stroke:#2d1932;stroke-width:2px">${label}</text></g>`;
        }).join('');
        const bosses=(replay.bosses||[]).map(b=>{
          const life=workbench.lifeState(b,t),q=screen(position(b.actorID,life.positionTime));
          if(!q||!life.opacity)return '';
          const breath=b.gameID===258557,portrait=breath?'/assets/raids/venomous_abyss/02-sentinels-breath.png':'/assets/raids/venomous_abyss/02-sentinels-blood.png';
          return `<g data-key="boss:${b.actorID}" opacity="${life.opacity}"><title>${breath?'乌拉特克之息':'乌拉特克之血'}</title><circle cx="${q.x}" cy="${q.y}" r="28" fill="#141825" stroke="${breath?'#9cf681':'#ff8a92'}" stroke-width="4"/><image href="${portrait}" x="${q.x-25}" y="${q.y-25}" width="50" height="50"/><circle cx="${q.x}" cy="${q.y}" r="28" fill="none" stroke="${breath?'#9cf681':'#ff8a92'}" stroke-width="4"/>${workbench.castBar(b,t,{x:q.x,y:q.y-18},116)}</g>`;
        }).join('');
        const impacts=hits.filter(e=>t>=e.timeMs&&t<e.timeMs+650).map((e,i)=>{
          const q=screen(e.position||position(e.playerID,e.timeMs));if(!q)return '';
          const f=(t-e.timeMs)/650,color=e.kind==='spear'?'#baff7a':'#ff6c49';
          const blast=e.kind==='helical'&&e.radiusYards?`<circle cx="${q.x}" cy="${q.y}" r="${radius(e.radiusYards)}" fill="#e5263c" fill-opacity="${.23*(1-f)}" stroke="#ff596c" stroke-width="5" opacity="${1-f}"/>`:'';
          return `<g data-key="impact:${e.kind}:${i}" data-effect="${e.kind}-hit">${blast}<circle cx="${q.x}" cy="${q.y}" r="${12+f*52}" fill="none" stroke="${color}" stroke-width="6" opacity="${1-f}"/><path d="M ${q.x-13} ${q.y-13} L ${q.x+13} ${q.y+13} M ${q.x+13} ${q.y-13} L ${q.x-13} ${q.y+13}" stroke="${color}" stroke-width="4" opacity="${1-f}"/></g>`;
        }).join('');
        const soaks=(field.soaks||[]).filter(e=>t>=e.timeMs&&t<e.timeMs+450).map((e,i)=>{
          const q=screen(e.position);return q?`<circle data-key="soak:${i}" data-effect="miasma-soak" cx="${q.x}" cy="${q.y}" r="${radius(5)}" fill="#ae87ff" fill-opacity=".15" stroke="#dac7ff" stroke-width="2"/>`:'';
        }).join('');
        return `<div class="mw-map" data-replay-field style="aspect-ratio:${arena.width}/${arena.height}"><svg viewBox="0 0 ${arena.width} ${arena.height}" role="img" aria-label="陵寝哨兵连续战斗场地推演"><image href="${arena.image}" width="${arena.width}" height="${arena.height}"/><g pointer-events="none">${water}${murk}${miasma}${circles}${soaks}${lances}${clears}</g><g>${bosses}${slimes}${avatars}</g><g pointer-events="none">${helical}${impacts}</g></svg></div>`;
      }});
    const jumps=marks.filter(e=>e.timeMs>=0).sort((a,b)=>a.timeMs-b.timeMs);
    host.insertAdjacentHTML('afterbegin',`<label>回放片段<select aria-label="陵寝哨兵回放片段">${jumps.map(e=>`<option value="${e.timeMs}">${workbench.escape(e.label)}，${Math.floor(e.timeMs/60000)}:${((e.timeMs%60000)/1000).toFixed(1).padStart(4,'0')}</option>`).join('')}</select></label>`);
    host.querySelector('select[aria-label="陵寝哨兵回放片段"]').onchange=e=>wb.seek(Number(e.target.value));
    return wb;
  }
  root.SentinelsReplay={mount,project};if(typeof module!=='undefined')module.exports=root.SentinelsReplay;
})(typeof window==='undefined'?globalThis:window);
