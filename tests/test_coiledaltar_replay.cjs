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
