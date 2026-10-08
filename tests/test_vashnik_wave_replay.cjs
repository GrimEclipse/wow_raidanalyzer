const assert=require('node:assert/strict');
const replay=require('../frontend/report/plugins/venomous_abyss/vashnik/wave-replay.js');
const origin={x:0,y:0},round={players:[{referenceAvailable:true,ending:'removed',position:origin,timeMs:1000,player:'A',eventID:'1'}]},simulation={widthYards:5,speedYardsPerSecond:20,rangeYards:80};
assert.equal(replay.waves(round,999,simulation).length,0);
const fronts=replay.waves(round,2000,simulation);
assert.equal(fronts.length,4);
assert.equal(fronts[0].front,2000);
assert.deepEqual(replay.waves(round,2000,simulation),fronts); // Seek/replay is deterministic.
assert.equal(fronts[0].head[3].y-fronts[0].head[0].y,500);
assert.ok(replay.contains({x:1000,y:250},origin,replay.axes[0],2000,500));
assert.ok(!replay.contains({x:1000,y:251},origin,replay.axes[0],2000,500));
assert.ok(!replay.contains({x:-1,y:0},origin,replay.axes[0],2000,500));
assert.equal(replay.waves({...round,players:[{...round.players[0],ending:'death'}]},2000,simulation).length,0);
assert.equal(replay.waves(round,7000,simulation).length,0);
const unit={spawnTimeMs:1000,firstSeenTimeMs:1000,deathTimeMs:5000,despawnTimeMs:null,castStarts:[2000],castCompletions:[4000],positions:[{timeMs:4000,x:10,y:20}]};
assert.equal(replay.totemState(unit,999),'future');
assert.equal(replay.totemState(unit,1500),'alive');
assert.equal(replay.totemState(unit,2500),'casting');
assert.equal(replay.totemState(unit,4500),'completed');
assert.equal(replay.totemState(unit,5000),'dead');
assert.equal(replay.totemState({...unit,deathTimeMs:null},9000),'completed');
assert.equal(replay.totemPosition(unit,1500).timeMs,4000); // Explicit static-unit backfill.
assert.equal(replay.totemPosition({...unit,positions:[]},1500),null);
console.log('Vashnik wave geometry and replay checks passed');
