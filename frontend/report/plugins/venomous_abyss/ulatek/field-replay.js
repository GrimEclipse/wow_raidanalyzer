(function(root){
  'use strict';
  const portraits={259555:'gore-rattle',267418:'gore-rattle',264045:'doomscale-warden',269200:'doomscale-weakened',261915:'blightscale-viper',266085:'devourers-spawn',265644:'devourers-spawn',268121:'devourers-spawn',268164:'doomscale-egg',271194:'doomscale-egg',263535:'doomscale-egg',263942:'doomscale-wretch',273577:'doomscale-wretch'};
  const eggIDs=new Set([265644,266085,268121,268164,271194,263535]);
  const names={257758:'乌拉特克',267460:'烈毒之心',259555:'血腥响尾',267418:'血腥响尾',264045:'厄鳞守卫',269200:'虚弱的厄鳞',261915:'疫鳞蝰蛇',263942:'疫鳞畸体',273577:'尖啸者'};
  function recentInterrupt(casts,id,instance,t){return (casts||[]).findLast(c=>c.actorID===id&&c.instance===instance&&c.outcome==='interrupted'&&c.endTimeMs<=t&&t-c.endTimeMs<1100)||null;}
  function portraitFor(unit){return portraits[unit.gameID]||(['Ravenous Doomscale','Weakened Doomscale','贪婪的厄鳞','虚弱的厄鳞'].includes(unit.name)?'doomscale-weakened':null);}
  function auraWarningActive(aura,t){
    if(aura.kind!=='purge')return aura.startTimeMs<=t&&t<aura.endTimeMs;
    if(aura.warningEndTimeMs==null&&aura.spellID!==1316356)return false;
    const start=aura.warningStartTimeMs??aura.startTimeMs,end=Math.min(aura.warningEndTimeMs??aura.endTimeMs,start+6000);
    return start<=t&&t<end;
  }
  function waveFront(wave,t){
    const age=(t-wave.timeMs)/1000,distance=age*wave.speedYardsPerSecond;
    return age>=0&&distance<wave.travelYards?{distance,opacity:Math.min(1,(wave.travelYards-distance)/10)}:null;
  }
  // Clip only the four pieces of floor. The lateral stairs remain visible.
  const floorPieces={
    nw:[[.498,.026],[.390,.033],[.234,.280],[.226,.495],[.405,.495],[.412,.427],[.451,.411],[.488,.358],[.498,.280]],
    ne:[[.499,.018],[.626,.022],[.768,.309],[.768,.490],[.590,.487],[.590,.420],[.543,.416],[.510,.354],[.500,.260]],
    sw:[[.241,.510],[.412,.501],[.447,.563],[.469,.639],[.497,.719],[.486,.799],[.498,.977],[.383,.982],[.236,.716]],
    se:[[.593,.501],[.624,.490],[.779,.519],[.777,.725],[.635,.980],[.504,.982],[.500,.740],[.510,.680],[.549,.610],[.538,.583],[.580,.589],[.590,.553]]
  };
  function floorPolygon(map,position){
    const q=projectMap(position,map),left=q.x<map.width/2,top=q.y<map.height/2;
    return floorPieces[(top?'n':'s')+(left?'w':'e')].map(([x,y])=>({x:x*map.width,y:y*map.height}));
  }
  function waterPattern(map,key,escape){
    // Reuse the map's clear water beside the east floor, at its original
    // pixel scale. Mirrored repeats join without stretching or blurry zoom.
    const x=map.width*.805,y=map.height*.52,w=map.width*.13,h=map.height*.45,id=`ula-water-sample-${key}`;
    return `<pattern id="ula-water-${key}" width="${w*2}" height="${h*2}" patternUnits="userSpaceOnUse"><svg id="${id}" width="${w}" height="${h}" viewBox="${x} ${y} ${w} ${h}" preserveAspectRatio="none"><image href="${escape(map.image)}" width="${map.width}" height="${map.height}"/></svg><use href="#${id}" transform="translate(${w*2} 0) scale(-1 1)"/><use href="#${id}" transform="translate(0 ${h*2}) scale(1 -1)"/><use href="#${id}" transform="translate(${w*2} ${h*2}) scale(-1 -1)"/></pattern>`;
  }
  function conePoints(cone,map,position=cone.position){
    const target=cone.targetPosition;if(!position||!target)return [];
    if(Math.hypot(target.x-position.x,target.y-position.y)<1)return [];
    const angle=Math.atan2(target.y-position.y,target.x-position.x),half=cone.angleDegrees*Math.PI/360,length=cone.lengthYards*100;
    return [projectMap(position,map),...Array.from({length:9},(_,i)=>{const a=angle-half+i*half/4;return projectMap({x:position.x+Math.cos(a)*length,y:position.y+Math.sin(a)*length},map);})];
  }
  function project(point,arena){
    if(!point)return null;
    const scale=(arena.pixelsPerYard||10.6)/100;
    return {x:(arena.imageCenterX??998.5)+(point.x-arena.centerX)*scale,
      y:(arena.imageCenterY??559)-(point.y-arena.centerY)*scale};
  }
  function projectMap(point,map){
    if(!point)return null;
    const dx=(point.x-map.centerX)/100,dy=(map.centerY-point.y)/100,a=(map.yaw||0)*Math.PI/180,s=map.height/map.yards;
    return {x:map.width/2+(dx*Math.cos(a)-dy*Math.sin(a))*s,y:map.height/2+(dx*Math.sin(a)+dy*Math.cos(a))*s};
  }
  function isSplit(feedback,t){return (feedback.phaseWindows||[]).some(p=>p.key==='p2'&&p.startTimeMs<=t&&t<p.endTimeMs);}
  function panelLayout(maps,split,broken=false){
    const width=maps.platform.width+360,height=maps.platform.height+360;
    if(!split)return {split:false,width,height,panels:[{key:'main',map:broken?maps.broken:maps.platform,dx:180,dy:180}]};
    const gap=24,rowHeight=(height-gap)/2;
    const panels=['left','right'].map((key,i)=>{
      const map=maps[key],cropY=map.height*.22,cropHeight=map.height*.74,scale=rowHeight/cropHeight;
      return {key,map,cropY,cropHeight,scale,dx:(width-map.width*scale)/2,dy:i*(rowHeight+gap)-cropY*scale};
    });
    return {split:true,width,height,panels};
  }
  function eggState(egg,t){
    if(t<egg.startTimeMs||t>=egg.endTimeMs+900)return null;
    const carry=(egg.carries||[]).find(c=>c.startTimeMs<=t&&t<c.endTimeMs);
    const released=(egg.carries||[]).find(c=>c.endTimeMs<=t);
    return {carry,released,opacity:t<egg.endTimeMs?1:Math.max(0,1-(t-egg.endTimeMs)/900),
      shield:(egg.shield||[]).findLast(s=>s[0]<=t),
      broken:egg.shieldBreakTimeMs!=null&&t>=egg.shieldBreakTimeMs};
  }
  function channelBosses(bosses,channels){return bosses.map(b=>({...b,name:names[b.gameID]||b.name,
    casts:[...(b.casts||[]),...channels.filter(c=>c.actorID===b.actorID)].sort((a,b)=>a.startTimeMs-b.startTimeMs)}));}
  function circlePulse(circle,t){
    if(t<circle.startTimeMs||t>=circle.endTimeMs)return null;
    const elapsed=t-circle.impactTimeMs,channel=elapsed>=0;
    const tick=(circle.tickTimesMs||[]).findLast(x=>x<=t);
    return {channel,opacity:channel?(tick!=null&&t-tick<170?.36:.15):.10,
      progress:Math.min(1,Math.max(0,(t-circle.startTimeMs)/(circle.impactTimeMs-circle.startTimeMs||1)))};
  }
  function mount(host,mechanics,durationMs){
    const api=root.MechanicWorkbench,source=mechanics.combatReplay;
    if(!source?.units?.length){host.innerHTML='<div class="empty">这份旧报告没有整场位置记录，请重新分析后播放。</div>';return null;}
    const feedback=mechanics.replayFeedback||{},arena=feedback.arena||{centerX:0,centerY:155500};
    const fallback={width:1997,height:1118,centerX:arena.centerX,centerY:arena.centerY,yaw:0,yards:1118/(arena.pixelsPerYard||10.6),image:'/assets/raids/venomous_abyss/08-ulatek-arena.jpg'};
    const maps=feedback.maps||{platform:fallback,broken:{...fallback,image:'/assets/raids/venomous_abyss/08-ulatek-broken.jpg'}};
    const bossList=channelBosses((source.bosses||[]).filter(b=>[257758,267460,259555].includes(b.gameID)),feedback.channels||[]);
    const replay={...source,bosses:bossList},players=source.units.filter(u=>u.kind==='player');
    const units=new Map();for(const u of source.units){if(!units.has(u.actorID))units.set(u.actorID,[]);units.get(u.actorID).push(u);}
    function unitAt(id,t,instance){
      const candidates=units.get(id)||[];
      if(instance!=null)return candidates.find(u=>u.instance===instance);
      return candidates.find(u=>u.kind==='player')||candidates.find(u=>u.samples?.length&&u.samples[0][0]-1000<=t&&t<=u.samples.at(-1)[0]+900);
    }
    function world(id,t,instance){const u=unitAt(id,t,instance);return u&&api.trackPosition(u,t,replay.interpolateMaxGapMs);}
    const rageAt=t=>(feedback.events||[]).some(e=>e.kind==='rage'&&e.timeMs<=t&&t<e.endTimeMs);
    const events=(feedback.events||[]).map((e,i)=>({...e,id:`phase:${i}`,layer:'战斗流程'}));
    for(const a of feedback.auras||[])events.push({id:`aura:${a.kind}:${a.playerID}:${a.startTimeMs}`,timeMs:a.startTimeMs,label:{egg:'携带蛇卵',fang:'攫取毒牙',bite:'毒蛇之咬',purge:'易爆清除'}[a.kind],layer:'点名',actor:unitAt(a.playerID,a.startTimeMs)?.name});
    for(const h of feedback.hits||[])events.push({id:`hit:${h.playerID}:${h.timeMs}`,timeMs:h.timeMs,label:'受到伤害',layer:'受击',problem:true,actor:unitAt(h.playerID,h.timeMs)?.name});
    function panelInfo(cursor){
      const split=isSplit(feedback,cursor)&&maps.left&&maps.right;
      const broken=(feedback.events||[]).some(e=>e.kind==='shatter'&&e.timeMs<=cursor);
      return panelLayout(maps,split,broken);
    }
    function drawPanel(panel,cursor,split){
      const {map,key}=panel,pr=p=>projectMap(p,map),scale=map.height/map.yards;
      const hitIDs=new Set((feedback.hits||[]).filter(h=>cursor>=h.timeMs&&cursor-h.timeMs<650).map(h=>h.playerID));
      const belongs=p=>!split||(key==='left'?p.x<-3500:p.x>3500);
      const visible=p=>p&&belongs(p);
      const avatarRadius=split?46:24,bossRadius=split?78:44;
      const avatars=players.map(u=>{const life=api.lifeState(u,cursor),p=world(u.actorID,life.positionTime);if(!visible(p)||!life.opacity)return '';const q=pr(p);
        const auras=(feedback.auras||[]).filter(a=>a.playerID===u.actorID&&auraWarningActive(a,cursor));
        const badges=auras.map((a,i)=>{const x=q.x+avatarRadius+i*avatarRadius,y=q.y-avatarRadius*1.5;if(a.kind==='egg')return a.eggKey?'':`<image href="/assets/raids/venomous_abyss/icons/devourers-spawn.png" x="${x-avatarRadius*.6}" y="${y-avatarRadius*.6}" width="${avatarRadius*1.2}" height="${avatarRadius*1.2}"/>`;const color=a.kind==='bite'?'#ffae64':a.kind==='purge'?'#b5ff71':'#ac86ff',r=a.radiusYards? a.radiusYards*scale:avatarRadius*1.5,progress=a.kind==='purge'?Math.max(0,(a.warningEndTimeMs-cursor)/(a.warningEndTimeMs-a.warningStartTimeMs)):1;return `<g data-effect="${a.kind}-circle"><circle cx="${q.x}" cy="${q.y}" r="${r}" fill="${color}" fill-opacity=".08" stroke="${color}" stroke-width="3"/>${a.kind==='purge'?`<circle cx="${q.x}" cy="${q.y}" r="${r+4}" fill="none" stroke="${color}" stroke-width="5" stroke-dasharray="${2*Math.PI*(r+4)*progress} ${2*Math.PI*(r+4)}" transform="rotate(-90 ${q.x} ${q.y})"/>`:''}</g>`;}).join('');
        return `<g data-key="${key}:player:${u.actorID}" opacity="${life.opacity}">${api.avatar(u,{...q,stale:p.stale},avatarRadius,hitIDs.has(u.actorID),life.dead,1)}${life.dead?'':badges}</g>`;
      }).join('');
      const entities=(source.units||[]).filter(u=>!(feedback.eggs&&eggIDs.has(u.gameID))).filter(u=>split?[264045,269200,266085,273577,261915,263535,263942].includes(u.gameID)||u.name==='Ravenous Doomscale':[257758,267460,259555,267418,264045,269200,261915,266085,263942,273577].includes(u.gameID)||u.name==='Ravenous Doomscale');
      const bosses=entities.map(u=>{const life=api.lifeState(u,cursor),p=world(u.actorID,life.positionTime,u.instance);if(!visible(p)||!life.opacity||u.gameID===267460&&!rageAt(cursor))return '';
        if(u.kind!=='player'&&u.samples?.length&&(cursor<u.samples[0][0]-1000||cursor>u.samples.at(-1)[0]+900))return '';
        const q=pr(p),r=split?bossRadius:u.gameID===259555?34:bossRadius;
        const portrait=portraitFor(u),face=portrait?`<image href="/assets/raids/venomous_abyss/icons/${portrait}.png" x="${q.x-r}" y="${q.y-r}" width="${r*2}" height="${r*2}"/>`:u.gameID===257758?`<defs><clipPath id="ula-face-${key}-${u.key}"><circle cx="${q.x}" cy="${q.y}" r="${r-2}"/></clipPath></defs><image href="/assets/raids/venomous_abyss/08-ulatek-hero.jpg" x="${q.x-r*5.56}" y="${q.y-r*4.68}" width="${r*16.384}" height="${r*9.216}" clip-path="url(#ula-face-${key}-${u.key})"/>`:u.gameID===267460?`<path d="M ${q.x} ${q.y+r*.7} C ${q.x-r*1.4} ${q.y-r*.3} ${q.x-r*.5} ${q.y-r*1.2} ${q.x} ${q.y-r*.5} C ${q.x+r*.5} ${q.y-r*1.2} ${q.x+r*1.4} ${q.y-r*.3} ${q.x} ${q.y+r*.7}" fill="#c1e56a"/>`:`<path d="M ${q.x-r*.6} ${q.y-r*.5} Q ${q.x+r} ${q.y-r*.7} ${q.x+r*.5} ${q.y} Q ${q.x-r} ${q.y+r} ${q.x-r*.5} ${q.y+r*.5}" fill="none" stroke="${u.gameID===259555?'#f7bf63':'#ceacff'}" stroke-width="${r*.3}" stroke-linecap="round"/>`;
        const b={...u,actorID:u.key,casts:(feedback.npcCasts||[]).filter(c=>c.actorID===u.actorID&&c.instance===u.instance)};
        const npcBar=(feedback.npcCasts||[]).some(c=>c.actorID===u.actorID&&c.instance===u.instance&&c.startTimeMs<=cursor&&cursor<c.endTimeMs);
        const kick=recentInterrupt(feedback.npcCasts,u.actorID,u.instance,cursor),kicker=kick&&unitAt(kick.interruptPlayerID,cursor),badgeSize=r*.85,fade=kick?1-(cursor-kick.endTimeMs)/1100:0;
        const stopped=kick?`<g data-effect="npc-interrupt" opacity="${fade}"><title>${api.escape(kicker?.name||'玩家')}打断${api.escape(kick.spellName||'施法')}</title><circle cx="${q.x}" cy="${q.y}" r="${r+5+(cursor-kick.endTimeMs)*.05}" fill="none" stroke="#8dffcb" stroke-width="5"/>${kicker?api.avatar(kicker,{x:q.x-badgeSize*.7,y:q.y-r-badgeSize*.8},badgeSize*.45):''}${kick.interruptIcon?`<image href="${api.escape(kick.interruptIcon)}" x="${q.x+badgeSize*.1}" y="${q.y-r-badgeSize*1.25}" width="${badgeSize}" height="${badgeSize}"/>`:''}<path d="M ${q.x-r*.3} ${q.y-r*.3} L ${q.x+r*.3} ${q.y+r*.3} M ${q.x+r*.3} ${q.y-r*.3} L ${q.x-r*.3} ${q.y+r*.3}" stroke="#b9ffe0" stroke-width="4"/></g>`:'';
        return `<g data-key="${key}:boss:${u.key}" data-game-id="${u.gameID}" opacity="${life.opacity}"><title>${api.escape(names[u.gameID]||u.name)}</title><circle cx="${q.x}" cy="${q.y}" r="${r}" fill="#17243b" stroke="#f2be72" stroke-width="3"/>${face}${npcBar?`<g data-effect="npc-cast" transform="translate(${q.x} ${q.y-r}) scale(${split?4:2})">${api.castBar(b,cursor,{x:0,y:0},80)}</g>`:''}${stopped}</g>`;
      }).join('');
      const circles=(feedback.circles||[]).map(c=>{const state=circlePulse(c,cursor),origin=c.kind==='fester-safe'?world(c.sourceID,cursor,c.sourceInstance)||c.position:c.position;if(!state||!visible(origin))return '';const q=pr(origin),r=c.radiusYards*scale,color=c.kind==='fester-safe'?'#84f5e1':c.kind==='coil-soak'?'#b497ff':c.kind==='wrath'?'#ff5265':'#ffbe69';
        return `<g data-key="${key}:circle:${c.sourceID}:${c.impactTimeMs}" data-effect="${c.kind}"><circle cx="${q.x}" cy="${q.y}" r="${r}" fill="${color}" fill-opacity="${state.opacity}" stroke="${color}" stroke-width="4"/><circle cx="${q.x}" cy="${q.y}" r="${r*(state.channel?1:state.progress)}" fill="none" stroke="${color}" stroke-width="${state.channel?7:2}" stroke-opacity=".65"/></g>`;
      }).join('');
      const purge=(feedback.auras||[]).filter(a=>a.kind==='purge'&&auraWarningActive(a,cursor)).map(a=>{const p=world(a.playerID,cursor);if(!visible(p))return '';const q=pr(p);return `<g data-key="purge:${a.playerID}:${a.startTimeMs}" data-effect="purge-directions">${(feedback.purgeDirections||[]).map(d=>{const to=pr({x:p.x+d.x*6500,y:p.y+d.y*6500});return `<path d="M ${q.x} ${q.y} L ${to.x} ${to.y}" fill="none" stroke="#a4ff78" stroke-width="${split?9:4}" stroke-dasharray="${scale*1.5} ${scale*.7}" stroke-opacity=".65"/>`;}).join('')}</g>`;}).join('');
      const waves=(feedback.waves||[]).map((w,i)=>{const front=waveFront(w,cursor);if(!front||!visible(w.position))return '';const p=w.position;return `<g data-key="${key}:wave:${i}" data-effect="${w.kind}-wave" opacity="${front.opacity}">${w.directions.map(d=>{const center={x:p.x+d.x*front.distance*100,y:p.y+d.y*front.distance*100},q=pr(center),wing=w.kind==='purge'?180:140,from=pr({x:center.x-d.y*wing,y:center.y+d.x*wing}),to=pr({x:center.x+d.y*wing,y:center.y-d.x*wing});return `<path d="M ${from.x} ${from.y} Q ${q.x} ${q.y} ${to.x} ${to.y}" fill="none" stroke="#85ff9e" stroke-width="${w.widthYards*scale}" stroke-opacity=".3" stroke-linecap="round"/><path d="M ${from.x} ${from.y} Q ${q.x} ${q.y} ${to.x} ${to.y}" fill="none" stroke="#d3ffb9" stroke-width="${scale*.35}" stroke-linecap="round"/>`;}).join('')}</g>`;}).join('');
      const tankLinks=(feedback.tankTethers||[]).filter(a=>a.startTimeMs<=cursor&&cursor<a.endTimeMs).map(a=>{const target=world(a.targetID,cursor,a.targetInstance)||a.targetPosition;if(!visible(target)||!a.position)return '';const from=pr(a.position),to=pr(target);return `<g data-key="${key}:tank-tether:${a.sourceID}:${a.instance}:${a.startTimeMs}" data-effect="tank-tether"><circle cx="${from.x}" cy="${from.y}" r="${scale*1.5}" fill="#acff7a" fill-opacity=".4"/><path d="M ${from.x} ${from.y} L ${to.x} ${to.y}" stroke="#beff86" stroke-width="${scale*.4}" stroke-dasharray="${scale} ${scale*.5}"/></g>`;}).join('');
      const cones=(feedback.cones||[]).filter(c=>c.startTimeMs<=cursor&&cursor<c.endTimeMs).map(c=>{
        const origin=world(c.actorID,cursor,c.instance)||c.position;if(!visible(origin))return '';
        const points=conePoints(c,map,origin);if(!points.length)return '';
        return `<polygon data-key="${key}:cone:${c.actorID}:${c.instance}:${c.startTimeMs}" data-effect="thrash-warning" points="${points.map(p=>`${p.x},${p.y}`).join(' ')}" fill="#ff8c73" fill-opacity=".16" stroke="#ffd399" stroke-width="${split?5:3}"/>`;
      }).join('');
      const eggs=(feedback.eggs||[]).map(e=>{const state=eggState(e,cursor);if(!state)return '';const p=state.carry?world(state.carry.playerID,cursor):state.released?.releasePosition||api.trackPosition(e,Math.min(cursor,e.endTimeMs),replay.interpolateMaxGapMs)||e.position;if(!visible(p))return '';const q=pr(p),r=state.carry?avatarRadius*.65:eggIDs.has(e.gameID)&&[263535,268164,271194].includes(e.gameID)?avatarRadius*1.25:avatarRadius*.9;
        if(state.carry){q.x+=avatarRadius*.85;q.y-=avatarRadius*1.2;}
        const shield=state.shield?.[2]>0&&!state.broken?Math.min(1,state.shield[1]/state.shield[2]):0;
        const breakAge=cursor-e.shieldBreakTimeMs,burst=e.shieldBreakTimeMs!=null&&breakAge>=0&&breakAge<600?`<circle cx="${q.x}" cy="${q.y}" r="${r*(1+breakAge/250)}" fill="none" stroke="#c5f2ff" stroke-width="3" opacity="${1-breakAge/600}"/>`:'';
        const hits=(e.interactions||[]).filter(h=>cursor>=h.timeMs&&cursor-h.timeMs<240).map(h=>{const from=world(h.playerID,cursor);if(!visible(from))return '';const s=pr(from);return `<path d="M ${s.x} ${s.y} L ${q.x} ${q.y}" stroke="#d7efff" stroke-width="2" opacity="${.7*(1-(cursor-h.timeMs)/240)}"/>`;}).join('');
        const release=state.released&&cursor>=state.released.endTimeMs?`<circle cx="${q.x}" cy="${q.y}" r="${r+(cursor-state.released.endTimeMs)*.09}" fill="none" stroke="#b2ff77" stroke-width="4"/>`:'';
        return `<g data-key="${key}:${e.key}" data-effect="egg-${state.carry?'carried':state.released?'released':'ground'}" opacity="${state.opacity}">${hits}<image href="/assets/raids/venomous_abyss/icons/${portraits[e.gameID]||'devourers-spawn'}.png" x="${q.x-r}" y="${q.y-r}" width="${r*2}" height="${r*2}"/>${shield?`<circle cx="${q.x}" cy="${q.y}" r="${r+4}" fill="#b7eaff" fill-opacity=".12" stroke="#b7eaff" stroke-width="4" stroke-dasharray="${2*Math.PI*(r+4)*shield} ${2*Math.PI*(r+4)}" transform="rotate(-90 ${q.x} ${q.y})"/>`:''}${burst}${release}</g>`;
      }).join('');
      const links=(feedback.auras||[]).filter(a=>a.kind==='fang'&&a.startTimeMs<=cursor&&cursor<a.endTimeMs).map(a=>{const target=world(a.playerID,cursor);if(!visible(target))return '';const sourceCandidates=units.get(a.sourceID)||[],source=sourceCandidates.map(u=>world(u.actorID,cursor,u.instance)).find(p=>p&&belongs(p)),from=pr(source),to=pr(target);return from&&to?`<path d="M ${from.x} ${from.y} L ${to.x} ${to.y}" stroke="#b993ff" stroke-width="${split?9:3}" stroke-dasharray="14 9"/>`:'';}).join('');
      const floor=split?'':(feedback.lostPlatforms||[]).filter(f=>cursor>=f.timeMs).map((f,i)=>`<polygon data-key="lost:${i}" data-effect="lost-floor" points="${floorPolygon(map,f.position).map(p=>`${p.x},${p.y}`).join(' ')}" fill="url(#ula-water-${key})" opacity="${Math.min(1,(cursor-f.timeMs)/800)}"/>`).join('');
      const warden=split?(feedback.wardens||[]).filter(w=>w.startTimeMs<=cursor&&w.position&&belongs(w.position)).at(-1):null;
      let wardenHUD='';
      if(warden){
        const hp=(warden.health||[]).findLast(h=>h[0]<=cursor),dead=api.lifeState(warden,cursor).dead,percent=dead?0:hp?Math.max(0,Math.min(100,hp[1]/hp[2]*100)):null;
        const x=map.width-670,y=panel.cropY+26,b={...warden,actorID:`${warden.actorID}:${warden.instance}`,casts:(feedback.npcCasts||[]).filter(c=>c.actorID===warden.actorID&&c.instance===warden.instance)};
        wardenHUD=`<g data-key="${key}:warden-health" data-effect="warden-health" transform="translate(${x} ${y})"><rect width="640" height="180" rx="18" fill="#0b1424e8" stroke="#344456" stroke-width="2"/><text x="26" y="55" fill="#edf3ff" style="font:42px system-ui">厄鳞守卫</text><text x="614" y="55" text-anchor="end" fill="#edf3ff" style="font:38px system-ui">${percent==null?'—':percent.toFixed(1)+'%'}</text><rect x="26" y="76" width="588" height="18" rx="8" fill="#293347"/><rect x="26" y="76" width="${588*(percent??0)/100}" height="18" rx="8" fill="#9ace71"/><g transform="translate(320 110) scale(3.4)">${api.castBar(b,cursor,{x:0,y:44},170)}</g></g>`;
      }
      return `<g transform="translate(${panel.dx} ${panel.dy||0}) scale(${panel.scale||1})"><defs><clipPath id="ula-panel-${key}"><rect x="${split?0:-180}" y="${split?panel.cropY:-180}" width="${map.width+(split?0:360)}" height="${split?panel.cropHeight:map.height+360}"/></clipPath>${split?'':waterPattern(map,key,api.escape)}</defs><g clip-path="url(#ula-panel-${key})"><image href="${api.escape(map.image)}" width="${map.width}" height="${map.height}"/><g data-key="${key}:floor">${floor}</g><g data-key="${key}:effects">${circles}${purge}${waves}${tankLinks}${cones}${links}</g><g data-key="${key}:bosses">${bosses}</g><g data-key="${key}:players">${avatars}</g><g data-key="${key}:eggs">${eggs}</g></g>${split?`<text x="${map.width/2}" y="${panel.cropY+65}" text-anchor="middle" fill="#e9edf7" style="font-size:56px;stroke-width:8px" stroke="#101724" paint-order="stroke">${key==='left'?'左长廊':'右长廊'}</text>${wardenHUD}`:''}</g>`;
    }
    const wb=api.mount(host,{key:'ulatek-replay',combatReplay:replay,durationMs,events},{video:true,handlesPlayers:true,
      project:p=>{const map=maps.platform,q=projectMap(p,map);return q&&{x:(q.x+180)/(map.width+360)*100,y:(q.y+180)/(map.height+360)*100};},
      bossPosition:(b,t)=>{const layout=panelInfo(t);if(layout.split)return null;const p=world(b.actorID,t),q=projectMap(p,layout.panels[0].map);return q&&{x:(q.x+180)/layout.width*100,y:(q.y+156)/layout.height*100};},
      renderMap(_s,_f,cursor){const layout=panelInfo(cursor);replay.bosses=layout.split?[]:bossList.filter(b=>b.gameID!==267460||rageAt(cursor)).filter(b=>world(b.actorID,cursor));
      const impact=(feedback.raidImpacts||[]).findLast(e=>e.timeMs<=cursor&&cursor-e.timeMs<650),age=impact?cursor-impact.timeMs:0,fade=impact?1-age/650:0;
      const shock=impact?`<g data-key="raid-impact" data-effect="raid-impact" pointer-events="none" opacity="${fade}"><rect width="${layout.width}" height="${layout.height}" fill="#ff405e" fill-opacity="${.16*fade}"/>${Array.from({length:24},(_,i)=>{const a=i*Math.PI/12,x=layout.width/2,y=layout.height/2,l=(.38+age/1600)*layout.width;return `<path d="M ${x+Math.cos(a)*l*.6} ${y+Math.sin(a)*l*.35} L ${x+Math.cos(a)*l} ${y+Math.sin(a)*l*.6}" stroke="#ffc8cf" stroke-width="${i%2?6:12}"/>`;}).join('')}</g>`:'';
      return `<div class="mw-map" data-replay-field style="aspect-ratio:${layout.width}/${layout.height}"><svg viewBox="0 0 ${layout.width} ${layout.height}" role="img" aria-label="${layout.split?'左右长廊同步回放':'乌拉特克连续战斗回放'}">${layout.panels.map(p=>drawPanel(p,cursor,layout.split)).join('')}${shock}</svg></div>`;
      }});
    const jumps=[...(feedback.events||[]),...(feedback.tankTethers||[]).map(a=>({timeMs:a.startTimeMs,label:"毒性孵化接线"})),...(feedback.waves||[]).filter(w=>w.kind==="purge").map(w=>({timeMs:w.timeMs,label:"易爆清除推波"})),...(feedback.cones||[]).map(c=>({timeMs:c.startTimeMs,label:'痛苦挣扎'})),...(feedback.eggs||[]).map(e=>({timeMs:e.startTimeMs,label:'蛇卵生成'})),...(feedback.auras||[]).filter(a=>['fang','bite'].includes(a.kind)||a.kind==='purge'&&a.radiusYards===3).map(a=>({timeMs:a.startTimeMs,label:{fang:'攫取毒牙',bite:'毒蛇之咬',purge:'易爆清除'}[a.kind]}))].filter((e,i,all)=>all.findIndex(x=>Math.abs(x.timeMs-e.timeMs)<1000&&x.label===e.label)===i).sort((a,b)=>a.timeMs-b.timeMs);
    host.insertAdjacentHTML('afterbegin',`<label>回放片段<select aria-label="乌拉特克回放片段">${jumps.map(e=>`<option value="${e.timeMs}">${api.escape(e.label)}，${`${Math.floor(e.timeMs/60000)}:${(e.timeMs/1000%60).toFixed(1).padStart(4,'0')}`}</option>`).join('')}</select></label>`);
    host.querySelector('select[aria-label="乌拉特克回放片段"]').onchange=e=>wb.seek(Number(e.target.value));
    return wb;
  }
  root.UlatekReplay={project,projectMap,isSplit,panelLayout,eggState,channelBosses,circlePulse,auraWarningActive,conePoints,portraitFor,waveFront,floorPolygon,recentInterrupt,mount};if(typeof module!=='undefined')module.exports=root.UlatekReplay;
})(typeof window==='undefined'?globalThis:window);
