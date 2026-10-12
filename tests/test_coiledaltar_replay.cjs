const assert=require('node:assert/strict');
const replay=require('../frontend/report/plugins/venomous_abyss/coiledaltar/field-replay.js');
const venom={rounds:[{timeMs:0}],carriers:[
  {puddleID:1,playerID:7,applyTimeMs:1000,removeTimeMs:3000,pickupPosition:{x:1,y:2},dropPosition:{x:8,y:9}},
  {puddleID:2,playerID:8,applyTimeMs:1500,removeTimeMs:4000,pickupPosition:{x:3,y:4},dropPosition:{x:10,y:11}},
  {puddleID:1,playerID:9,applyTimeMs:5000,removeTimeMs:7000,pickupPosition:{x:8,y:9},dropPosition:{x:20,y:21}}
]};
const orbs=replay.orbTracks(venom);
assert.equal(orbs.length,2);
assert.deepEqual(replay.orbAt(orbs[0],500,()=>null).point,{x:1,y:2});
assert.equal(replay.orbAt(orbs[0],500,()=>null).inferred,true);
const current=(id,time)=>({x:id*100+time,y:time});
assert.equal(replay.orbAt(orbs[0],2000,current).point.x,2700);
assert.equal(replay.orbAt(orbs[1],2000,current).point.x,2800);
assert.equal(replay.orbAt(orbs[0],2000,current).kind,'carried');
assert.deepEqual(replay.orbAt(orbs[0],3500,current).point,{x:8,y:9});
assert.equal(replay.orbAt(orbs[0],6000,current).actorID,9);
// Consuming a ball must remove its old ground state, even if the backend
// spatial match accidentally reuses that puddle ID in a later round.
const consumed=replay.orbTracks({...venom,rounds:[{timeMs:0},{timeMs:4500}]},[{timeMs:3500,targetsInCone:[{puddleID:1}]}]);
assert.equal(consumed.filter(o=>o.puddleID===1).length,2);
assert.equal(replay.orbAt(consumed[0],4600,current),null);
assert.equal(replay.orbAt(consumed.find(o=>o.id==='1:1'),4700,current).inferred,true);
assert.equal(replay.orbAt(consumed.find(o=>o.id==='1:1'),6000,current).actorID,9);
// An expired carry with no known drop point cannot fall back to its inferred
// pre-pickup spawn. A single ongoing carry remains attached to its player.
const noDrop=replay.orbTracks({rounds:[{timeMs:0}],carriers:[{playerID:7,puddleID:1,applyTimeMs:100,removeTimeMs:300,pickupPosition:{x:1,y:2}}]});
assert.equal(replay.orbAt(noDrop[0],500,current),null);
const phaseClear=replay.orbTracks(venom,[],[{key:'p2',timeMs:4500}]);
assert.equal(replay.orbAt(phaseClear.find(o=>o.puddleID===2),5500,current),null);
assert.deepEqual(replay.coneWindow({spellID:1,timeMs:4000},[{spellID:1,startTimeMs:1000,endTimeMs:4000}]),{start:1000,end:4650});
assert.deepEqual(replay.runoutWindow({timeMs:4000,participants:[{shareTimeMs:5500},{shareTimeMs:5501}]}),{start:5500,end:11500});
console.log('Coiled Altar simultaneous ground/carry/drop, cast warning and post-hit runout timing passed');
// Carry history counts actual pickups through the current cursor, not future
// pickups or duplicate copies of the same application in another stream.
const carried={playerID:7,applyTimeMs:100,venomKind:'virulent-mutation'};
const history=replay.carryHistory({carriers:[carried,{playerID:7,applyTimeMs:500,venomKind:'normal'}],pickups:[carried]});
assert.deepEqual(replay.carryCounts(history.get(7),300),{small:0,large:1});
assert.deepEqual(replay.carryCounts(history.get(7),600),{small:1,large:1});
const bomb={playerID:7,applyTimeMs:100,explodeTimeMs:2000,position:{x:99,y:99}};
assert.deepEqual(replay.bombAt(bomb,500,()=>({x:5,y:6})).point,{x:5,y:6});
assert.equal(replay.bombAt(bomb,500,()=>null),null); // Never reveal final location early.
assert.deepEqual(replay.bombAt(bomb,2100,()=>null).point,{x:99,y:99});
assert.equal(replay.bombAt({...bomb,explodeTimeMs:null,removeTimeMs:700},800,current),null);
assert.equal(replay.facingAt({facingSamples:[[100,0]]},50),null);
assert.equal(replay.facingAt({facingSamples:[[100,0]]},100).angle,0);
assert.equal(replay.facingAt({facingSamples:[[100,0]]},1200).stale,true);
const ghost={startTimeMs:100,endTimeMs:500,samples:[[100,0,0,7,1,1]]};
assert.equal(replay.ghostAt(ghost,50,()=>({x:0,y:0})),null);
assert.equal(replay.ghostAt(ghost,700,()=>({x:0,y:0})).targetID,7);
assert.equal(replay.ghostAt(ghost,1500,()=>({x:0,y:0})),null);
console.log('Facing, ghost lifetime, bomb movement and cursor carry totals passed');
const coiler={startTimeMs:100,endTimeMs:2000,samples:[[100,0,0],[300,5000,0]],teleports:[200],states:[],
  casts:[{startTimeMs:100,endTimeMs:500,outcome:'interrupted'}],health:[[100,80,100]],shield:[[100,2]]};
const coilerAPI={lifeState:()=>({opacity:1,positionTime:150}),trackPosition:()=>({x:2500,y:0})};
assert.equal(replay.soulcoilerAt(coiler,50,coilerAPI),null);
assert.equal(replay.soulcoilerAt(coiler,150,coilerAPI).point.x,0); // Teleport does not drift across the room.
assert.equal(replay.soulcoilerAt(coiler,150,coilerAPI).health,80);
assert.equal(replay.soulcoilerAt(coiler,150,coilerAPI).shield,2);
assert.equal(replay.soulcoilerAt(coiler,600,coilerAPI).cast,undefined);
assert.equal(replay.soulcoilerAt(coiler,600,coilerAPI).interrupt.outcome,'interrupted');
console.log('Soulcoiler spawn, teleport, health, shield and interruption passed');
assert.equal(replay.castProgress({startTimeMs:0,endTimeMs:1000,durationMs:10000},900),.09);
assert.equal(replay.castProgress({startTimeMs:0,endTimeMs:1000,durationMs:12000},600),.05);
const rates={startTimeMs:0,progressSegments:[[0,0,10000],[2000,.2,12000]]};
assert.equal(replay.castProgress(rates,2000),.2);
assert.equal(replay.castProgress(rates,8000),.7);
const ground={recedeDurationMs:24000,rounds:[{kind:'green',startTimeMs:0,channelEndTimeMs:8000,recedeStartTimeMs:23000,endTimeMs:47000,peakRadiusYards:45},
 {kind:'purple',ordinal:1,startTimeMs:100000,channelEndTimeMs:108000,recedeStartTimeMs:123000,endTimeMs:147000,peakRadiusYards:50},
 {kind:'purple',ordinal:2,startTimeMs:200000,channelEndTimeMs:208000,recedeStartTimeMs:223000,endTimeMs:247000,peakRadiusYards:60},
 {kind:'purple',ordinal:4,startTimeMs:400000,channelEndTimeMs:408000,recedeStartTimeMs:423000,endTimeMs:447000,peakRadiusYards:80,fullCoverage:true}]};
assert.equal(replay.groundAt(ground,8000).radiusYards,45);
assert.equal(replay.groundAt(ground,23000).radiusYards,45);
assert(replay.groundAt(ground,35000).radiusYards<45);
assert.equal(replay.groundAt(ground,47000),null);
assert.equal(replay.groundAt(ground,123000).radiusYards,50);
assert(replay.groundAt(ground,135000).radiusYards<50);
assert.equal(replay.groundAt(ground,147000),null);
assert.equal(replay.groundAt(ground,200000).radiusYards,0);
assert.equal(replay.groundAt(ground,409000).fullCoverage,true);
assert.equal(replay.groundAt(ground,435000).fullCoverage,false);
assert.equal(replay.groundAt(ground,447000),null);
console.log('Partial interrupted cast progress, live curse rate and green/purple hold and complete recession passed');
