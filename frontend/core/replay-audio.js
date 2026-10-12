/* Replay clock driven soundtrack. Encounter adapters provide phase windows. */
(function(root){
  'use strict';
  function targetAt(profile,timeMs){
    const phase=(profile.phases||[]).findLast(p=>p.startTimeMs<=timeMs&&timeMs<p.endTimeMs),track=phase&&profile.tracks?.[phase.key];
    if(!track||timeMs-phase.startTimeMs>=track.durationMs)return null;
    return {key:phase.key,src:track.src,time:(timeMs-phase.startTimeMs)/1000,duration:track.durationMs/1000};
  }
  function createController(profile,options={}){
    const make=options.createAudio||(()=>new Audio()),raf=options.raf||requestAnimationFrame,cancel=options.cancel||cancelAnimationFrame,now=options.now||(()=>performance.now());
    const slots=[0,1].map(()=>({audio:make(),key:null,pendingTime:null,starting:false,startToken:0}));
    for(const s of slots){s.audio.preload='none';s.audio.volume=0;s.audio.loop=false;s.audio.addEventListener('loadedmetadata',()=>{if(s.pendingTime!=null){s.audio.currentTime=s.pendingTime;s.pendingTime=null;}});}
    let active=-1,frame=0,muted=!!options.muted,volume=options.volume??profile.defaultVolume??.3,last={playing:false,timeMs:0,rate:1,durationMs:Infinity},destroyed=false;
    const fadeMs=profile.crossfadeMs||1500;
    function stopAll(){cancel(frame);frame=0;for(const s of slots){s.audio.volume=0;s.audio.pause();}}
    function gain(){const t=targetAt(profile,last.timeMs);return !t?0:volume*Math.min(1,(t.duration-t.time)*1000/(fadeMs*(last.rate||1)));}
    function fade(from){
      cancel(frame);const began=now(),initial=slots.map(s=>s.audio.volume);
      function tick(){if(destroyed||!last.playing)return;const f=Math.min(1,(now()-began)/fadeMs),level=gain();
        slots.forEach((s,i)=>{s.audio.volume=Math.max(0,Math.min(1,i===active?initial[i]+(level-initial[i])*f:initial[i]*(1-f)));});
        if(f<1)frame=raf(tick);else{frame=0;slots.forEach((s,i)=>{if(i!==active)s.audio.pause();});}
      }
      frame=raf(tick);
    }
    function begin(s){
      s.starting=true;const token=++s.startToken;
      const result=s.audio.play();
      if(result?.then)result.then(()=>{if(destroyed||!last.playing)s.audio.pause();else if(s===slots[active])fade();})
        .catch(e=>{if(e.name!=='AbortError')options.onError?.();}).finally(()=>{if(s.startToken===token)s.starting=false;});
      else{s.starting=false;fade();}
    }
    function sync(state){
      if(destroyed)return;
      last={...last,...state};const target=targetAt(profile,last.timeMs);
      for(const s of slots)s.audio.muted=muted;
      options.onState?.({target,muted,volume,playing:last.playing});
      if(!last.playing||volume===0||last.timeMs>=last.durationMs){stopAll();return;}
      if(!target){if(active>=0){active=-1;fade();}return;}
      let changed=false;
      if(active<0||slots[active].key!==target.key){
        active=active===0?1:0;const s=slots[active];s.audio.pause();s.audio.volume=0;s.key=target.key;s.audio.src=target.src;changed=true;
      }
      const s=slots[active],a=s.audio;
      if(s.pendingTime!=null||a.readyState===0)s.pendingTime=target.time;
      else if(Math.abs(a.currentTime-target.time)>.6)try{a.currentTime=target.time;}catch(_){s.pendingTime=target.time;}
      try{a.playbackRate=last.rate||1;}catch(_){a.playbackRate=1;}
      if(changed||a.paused&&!a.ended&&!s.starting)begin(s);
      else if(!frame&&!s.starting)a.volume=gain();
    }
    return {sync,slots,setMuted(value){muted=!!value;sync(last);},setVolume(value){volume=Math.max(0,Math.min(1,Number(value)||0));sync(last);},
      destroy(){destroyed=true;stopAll();},state(){return {muted,volume,active,target:targetAt(profile,last.timeMs),last};}};
  }
  function mountControls(host,profile,durationMs){
    if(!profile?.phases?.length)return null;
    const key='mythic:replay-audio:v1';let saved={};try{saved=JSON.parse(localStorage.getItem(key)||'{}')||{};}catch(_){}
    const volume=Number.isFinite(saved.volume)?Math.max(0,Math.min(1,saved.volume)):profile.defaultVolume??.3,box=document.createElement('span');
    box.className='mw-audio';box.innerHTML='<button type="button" data-audio-toggle></button><input type="range" min="0" max="100" aria-label="战斗音乐音量"><span data-audio-status></span>';
    const toggle=box.querySelector('button'),slider=box.querySelector('input');slider.value=String(Math.round(volume*100));
    (host.querySelector('.mw-transport')||host).appendChild(box);
    const controller=createController(profile,{volume,muted:saved.muted===true,
      createAudio(){const a=document.createElement('audio');a.hidden=true;a.className='mw-replay-audio';box.appendChild(a);return a;},
      onState(s){toggle.textContent=s.muted?'声音 关':'声音 开';toggle.setAttribute('aria-label',s.muted?'开启战斗声音':'关闭战斗声音');toggle.setAttribute('aria-pressed',String(s.muted));box.dataset.musicPhase=s.target?.key||'silent';box.dataset.musicOffset=String(s.target?.time||0);},
      onError(){box.querySelector('[data-audio-status]').textContent='声音加载失败';}});
    function save(){try{const s=controller.state();localStorage.setItem(key,JSON.stringify({muted:s.muted,volume:s.volume}));}catch(_){}}
    toggle.onclick=()=>{controller.setMuted(!controller.state().muted);save();};
    slider.oninput=()=>{controller.setVolume(Number(slider.value)/100);save();};
    const leave=()=>controller.sync({playing:false});window.addEventListener('pagehide',leave);
    const destroy=controller.destroy;controller.destroy=()=>{window.removeEventListener('pagehide',leave);destroy();box.remove();};
    controller.sync({timeMs:0,playing:false,durationMs,rate:1});return controller;
  }
  root.ReplayAudio={targetAt,createController,mountControls};if(typeof module!=='undefined')module.exports=root.ReplayAudio;
})(typeof window==='undefined'?globalThis:window);
