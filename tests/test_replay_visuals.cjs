const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
require('../frontend/core/mechanic-workbench.js');
const api=globalThis.MechanicWorkbench,context={MechanicWorkbench:api,window:{},boss:()=>({}),current:()=>({durationMs:10000}),esc:s=>String(s??'').replaceAll('"','&quot;')};
vm.createContext(context);
vm.runInContext(fs.readFileSync('frontend/report/plugins/venomous_abyss/progression/report.js','utf8').split('\n').filter(line=>line.startsWith('function lerp')).join('\n'),context);
vm.runInContext(fs.readFileSync('frontend/report/plugins/venomous_abyss/sszorak/mechanics.js','utf8'),context);
const round={timeMs:1000,durationSec:3,winds:[{angleDegrees:0},{angleDegrees:90},{angleDegrees:180}]};
assert.equal(context.windAtFrame(round,999),null);
assert.equal(context.windAtFrame(round,2200).angleDegrees,90);
assert.equal(context.windAtFrame(round,4000),null);
const data={rounds:[{frames:[{timeMs:0,players:[{playerID:1,position:{x:0,y:0}},{playerID:2,position:{x:100,y:0}}]},{timeMs:1000,players:[{playerID:2,position:{x:120,y:0}},{playerID:1,position:{x:20,y:0}}]}]}]};
const players=context.sszFallbackPlayers(data,500);
assert.equal(players.find(p=>p.playerID===1).position.x,10);
assert.equal(players.find(p=>p.playerID===2).position.x,110);
const replay={bosses:[{actorID:9,name:'Boss',health:[[0,100,100]],casts:[{startTimeMs:100,endTimeMs:500,outcome:'completed',spellName:'Cast'}]}]};
assert.ok(api.bossStatus(replay,200).includes('Cast'));
assert.ok(api.bossStatus(replay,600).includes('mw-cast '));
assert.ok(!api.bossStatus(replay,600).includes('未施法'));
assert.equal(api.castBar(replay.bosses[0],600,{x:50,y:50}), '');
assert.ok(api.castBar(replay.bosses[0],200,{x:50,y:50}).includes('castbar:9'));
assert.equal((api.bossStatus(replay,600).match(/mw-cast /g)||[]).length,1);
context.boss=()=>({combatReplay:{bosses:[{actorID:9}],units:[{actorID:1,kind:'player',samples:[[0,10,6000]],states:[]},{actorID:9,kind:'enemy',samples:[[0,0,6000],[1000,100,7000]]}],interpolateMaxGapMs:5000}});
assert.equal(context.sszPlayerRows({arena:{coordinateOffsetYards:-50}},0)[0].position.y,1000);
assert.equal(context.sszBossPosition({arena:{coordinateOffsetYards:-50}},500).y,1500);
assert.equal(context.sszBossPosition({arena:{coordinateOffsetYards:-50}},500).x,50);
assert.equal(api.lifeState({states:[[100,'dead'],[2000,'alive']]},550).opacity,.5);
assert.equal(api.lifeState({states:[[100,'dead'],[2000,'alive']]},1100).opacity,0);
assert.equal(api.lifeState({states:[[100,'dead'],[2000,'alive']]},2000).opacity,1);
assert.ok(api.bossStatus({bosses:[{actorID:9,casts:[{startTimeMs:100,endTimeMs:4100,outcome:'completed',phase:'channel',spellName:'Channel'}]}]},2100).includes('引导'));
vm.runInContext(fs.readFileSync('frontend/report/plugins/venomous_abyss/twinfangs/mechanics.js','utf8'),context);
const flood={startTimeMs:4000,endTimeMs:18000,initialAngleRadians:Math.PI/2,rotationDirection:1,sweepDegrees:270};
assert.equal(context.twinFloodAngle(flood,0),Math.PI/2);
assert.ok(Math.abs(context.twinFloodAngle(flood,18000)-Math.PI/2-1.5*Math.PI)<1e-9);
assert.equal(context.twinFloodAngle(flood,25000),context.twinFloodAngle(flood,18000));
assert.ok(!context.twinFloodWarning(flood,[100,100],2000).includes('<text'));
assert.ok(context.twinFloodWarning(flood,[100,100],2000).includes('flood-direction-warning'));
const calibrated={...flood,angularSpeedDegrees:24,rotationDurationMs:14000,rotationEndTimeMs:18000,coneDegrees:30,sweepDegrees:336};
assert.ok(Math.abs(context.twinFloodAngle(calibrated,18000)-Math.PI/2-336*Math.PI/180)<1e-9);
assert.ok(context.twinFloodCone(calibrated,[100,100],8000).includes('vile-flood'));
assert.ok(context.twinFloodCone(calibrated,[100,100],16000).includes('vile-flood'));
assert.equal(context.twinFloodCone(calibrated,[100,100],18000),'');
assert.equal(context.twinFloodCone(calibrated,[100,100],3000),'');
const short={...calibrated,endTimeMs:6000,rotationEndTimeMs:6000,sweepDegrees:48};
assert.ok(Math.abs(context.twinFloodAngle(short,6000)-Math.PI/2-48*Math.PI/180)<1e-9);
context.esc=s=>String(s??'').replaceAll('"','&quot;');context.player=p=>p.player;
const checkpoint={timeMs:6000,intervalStartTimeMs:2500,players:[{playerID:1,player:'Player',stacks:2,alive:true,history:[
  {timeMs:1000,time:'00:01',delta:1,originKey:'orb',fromStack:0,toStack:1},
  {timeMs:2000,time:'00:02',delta:1,originKey:'wave',fromStack:1,toStack:2},
  {timeMs:3000,time:'00:03',delta:-1,category:'feast',fromStack:2,toStack:1},
  {timeMs:4000,time:'00:04',delta:2,originKey:'orb',fromStack:1,toStack:3},
  {timeMs:5000,time:'00:05',delta:-1,category:'death',fromStack:3,toStack:2},
  {timeMs:7000,time:'00:07',delta:1,originKey:'wave',fromStack:2,toStack:3}]}]};
const columns=[{key:'orb',label:'Orb',color:'#0f0'},{key:'wave',label:'Wave',color:'#00f'}];
const chronological=context.twinVenomSourceRows(checkpoint,columns);
assert.deepEqual([...chronological.matchAll(/data-source="([^"]+)"/g)].map(m=>m[1]),['orb','wave','orb','orb']);
assert.ok(chronological.indexOf('twin-source-removals')>chronological.lastIndexOf('data-source='));
assert.deepEqual([...chronological.matchAll(/data-removal="([^"]+)"/g)].map(m=>m[1]),['feast','death']);
const interval=context.twinVenomSourceRows(checkpoint,columns,'interval');
assert.deepEqual([...interval.matchAll(/data-source="([^"]+)"/g)].map(m=>m[1]),['orb','orb']);
assert.ok(!interval.includes('00:01'));
console.log('Replay identity, effect windows and fixed cast slot passed');
