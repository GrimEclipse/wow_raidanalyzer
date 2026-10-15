const assert=require('node:assert/strict');
const {targetAt,createController}=require('../frontend/core/replay-audio.js');
const profile={defaultVolume:.3,crossfadeMs:1500,tracks:{},phases:[
 {key:'p1',startTimeMs:0,endTimeMs:10000},{key:'p2',startTimeMs:10000,endTimeMs:20000},
 {key:'p25',startTimeMs:20000,endTimeMs:25000},{key:'p3',startTimeMs:35000,endTimeMs:60000}]};
for(const p of profile.phases)profile.tracks[p.key]={src:p.key+'.mp3',durationMs:p.endTimeMs-p.startTimeMs};
assert.equal(targetAt(profile,25000),null);
assert.equal(targetAt(profile,34999),null);
assert.equal(targetAt(profile,35000).key,'p3');
assert.equal(targetAt({...profile,tracks:{...profile.tracks,p1:{...profile.tracks.p1,assetVersion:'cut-v2'}}},0).src,'p1.mp3?v=cut-v2');
let clock=0,nextId=0,pending=new Map();
class Audio extends EventTarget{
 constructor(){super();this.paused=true;this.readyState=1;this.currentTime=0;this.ended=false;this.plays=0;}
 set src(s){this.source=s;this.currentTime=0;this.ended=false;this.paused=true;}
 get src(){return this.source;}
 play(){this.paused=false;this.plays++;}
 pause(){this.paused=true;}
}
const c=createController(profile,{createAudio:()=>new Audio(),now:()=>clock,
 raf:fn=>{pending.set(++nextId,fn);return nextId;},cancel:id=>pending.delete(id)});
function advance(ms){clock+=ms;const frames=[...pending.values()];pending.clear();frames.forEach(fn=>fn());}
c.sync({playing:false,timeMs:0,durationMs:60000,rate:1});
assert(c.slots.every(s=>s.audio.paused&&!s.audio.src));
c.sync({playing:true,timeMs:0});advance(750);
assert.equal(c.slots[0].audio.volume,.15);advance(750);
assert.equal(c.slots[0].audio.volume,.3);
c.sync({timeMs:5000});assert.equal(c.slots[0].audio.currentTime,5);
c.sync({playing:false});assert(c.slots.every(s=>s.audio.paused&&s.audio.volume===0));
assert.equal(c.slots[0].audio.currentTime,5);
c.sync({playing:true});advance(1500);assert.equal(c.slots[0].audio.currentTime,5);
c.sync({timeMs:10000});advance(750);
assert.equal(c.slots[0].audio.volume,.15);assert.equal(c.slots[1].audio.volume,.15);
advance(750);assert(c.slots[0].audio.paused);assert.equal(c.slots[1].audio.volume,.3);
c.sync({timeMs:12000,rate:2});assert.equal(c.slots[1].audio.playbackRate,2);
const plays=c.slots[1].audio.plays;
c.setMuted(true);assert(c.slots.every(s=>s.audio.muted));assert.equal(c.slots[1].audio.paused,false);
c.setMuted(false);assert.equal(c.slots[1].audio.currentTime,2);assert.equal(c.slots[1].audio.muted,false);
assert.equal(c.slots[1].audio.plays,plays,'Unmuting must not restart the audio');
assert.equal(c.slots[1].audio.volume,.3);
c.sync({timeMs:25000,rate:1});advance(1500);assert(c.slots.every(s=>s.audio.paused));
c.sync({timeMs:35000});assert.equal(c.state().target.key,'p3');
c.sync({timeMs:60000});assert(c.slots.every(s=>s.audio.paused&&s.audio.volume===0));
c.destroy();assert.equal(pending.size,0);
console.log('Replay audio fades, pause/resume, mute, speed, silent intermission and immediate ending passed');
// No animation frames or replay onFrame callbacks run in this test. Background
// timers alone must select phases, finish fades and stop at the fight end.
let bgClock=0,bgId=0,bgJobs=new Map();
const background=createController(profile,{createAudio:()=>new Audio(),now:()=>bgClock,
 setTimeout(fn,ms){bgJobs.set(++bgId,{fn,due:bgClock+ms});return bgId;},clearTimeout(id){bgJobs.delete(id);}});
function bgAdvance(ms){bgClock+=ms;for(const [id,job] of [...bgJobs].sort((a,b)=>a[1].due-b[1].due)){
 if(job.due<=bgClock&&bgJobs.has(id)){bgJobs.delete(id);job.fn();}
}}
background.sync({playing:true,timeMs:0,durationMs:60000,rate:1});
bgAdvance(16000);
assert.equal(background.state().target.key,'p2');
assert.equal(background.slots[1].audio.currentTime,6);
bgAdvance(1500);assert.equal(background.slots[1].audio.volume,.3);
bgAdvance(6500);assert.equal(background.state().target.key,'p25');
bgAdvance(3000);assert.equal(background.state().target,null);
bgAdvance(1500);assert(background.slots.every(s=>s.audio.paused));
bgAdvance(11500);assert.equal(background.state().target.key,'p3');
const live=background.slots[background.state().active];
live.audio.ended=true;live.audio.paused=true;live.audio.currentTime=25;
const previousPlays=live.audio.plays;
background.sync();
assert.equal(live.audio.paused,false);
assert.equal(live.audio.plays,previousPlays+1,'Returning within the same phase must restart an ended media element');
assert.equal(live.audio.currentTime,5);
bgAdvance(1500);assert.equal(live.audio.volume,.3);
const liveTime=background.state().last.timeMs;
background.setMuted(true);background.setMuted(false);
assert.equal(background.state().last.timeMs,liveTime,'Mute must not reset the autonomous replay clock');
background.sync({playing:false});const pausedTime=background.state().last.timeMs;
bgAdvance(5000);assert.equal(background.state().last.timeMs,pausedTime);
assert(background.slots.every(s=>s.audio.paused&&s.audio.volume===0));
background.sync({playing:true,timeMs:58000,rate:1});bgAdvance(2200);
assert.equal(background.state().last.playing,false);
assert(background.slots.every(s=>s.audio.paused&&s.audio.volume===0));
background.destroy();assert.equal(bgJobs.size,0);
console.log('Background phase switching, timer fades, same-phase recovery, mute clock and immediate fight-end stop passed');
class BufferedAudio extends Audio{
 play(){this.plays++;return new Promise(resolve=>{this.finish=()=>{this.paused=false;resolve();};});}
}
const buffered=createController(profile,{createAudio:()=>new BufferedAudio(),now:()=>clock,
 raf:fn=>{pending.set(++nextId,fn);return nextId;},cancel:id=>pending.delete(id)});
buffered.sync({playing:true,timeMs:0,durationMs:60000});
for(let t=10;t<1000;t+=10)buffered.sync({timeMs:t});
assert.equal(buffered.slots[0].audio.plays,1,'Buffering must not keep restarting play and its fade');
buffered.slots[0].audio.finish();
setImmediate(()=>{advance(1500);assert.equal(buffered.slots[0].audio.volume,.3);buffered.destroy();
 console.log('Deferred media playback completes its fade without repeated play requests');});
