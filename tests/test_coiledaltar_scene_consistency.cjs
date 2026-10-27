const assert=require('node:assert/strict');
require('../frontend/core/mechanic-workbench.js');
const replay=require('../frontend/report/plugins/venomous_abyss/coiledaltar/field-replay.js');
const api=globalThis.MechanicWorkbench,original=api.mount,captured=[];
api.mount=(host,scene,adapter)=>{captured.push({scene,adapter});return {seek(){}};};
const host=()=>({insertAdjacentHTML(){},querySelector(){return {};}});
const mechanics={fieldAudit:{arena:{radius:5500,unitsPerYard:100}},
  combatReplay:{units:[{actorID:1,kind:'player',name:'A',samples:[[1000,0,0],[2000,100,0]],states:[]}],bosses:[]},
  toxicDeluge:{rounds:[{timeMs:0}],carriers:[{puddleID:1,playerID:1,applyTimeMs:1200,removeTimeMs:1800,pickupPosition:{x:0,y:0},dropPosition:{x:80,y:0}}]}};
const project=p=>({x:50+p.x/100,y:50+p.y/100});
replay.mount(host(),mechanics,10000,project);
replay.mount(host(),mechanics,10000,project,{workbench:true,events:[{id:'future',timeMs:9000,label:'future snapshot',diagram:{targets:[{position:{x:999,y:999}}]}}]});
for(const t of [0,999,1000,1200,1700,2000,5000]){
  const ordinary=captured[0].adapter.renderMap(null,[],t,{});
  const workbench=captured[1].adapter.renderMap({diagram:{position:{x:999,y:999}}},[],t,{});
  assert.equal(workbench,ordinary,`Same scene at ${t} ms regardless of selected historical snapshot`);
}
assert.equal(captured[0].adapter.video,true);
assert.equal(captured[1].adapter.video,true);
assert(captured[1].scene.events.some(e=>e.id==='evidence:future'));
assert(!captured[0].adapter.renderMap(null,[],999,{}).includes('data-key="actor:1"'));
api.mount=original;
console.log('Homepage and legacy replay entry share identical temporal scene rendering');

// Turning off review sections must not erase the compact replay evidence.
api.mount=(host,scene,adapter)=>{captured.push({scene,adapter});return {seek(){}};};
const basic={...mechanics,toxicDeluge:{},sever:{},soulSever:{},blightedSever:{},gloombomb:{},
  replayMechanics:{version:1,toxicDeluge:mechanics.toxicDeluge,
    runouts:[{label:'处斩',timeMs:1800,shareCentroid:{x:0,y:0},dangerRadiusYards:40,
              participants:[{shareTimeMs:1800}],pulseTimeMs:7800}],
    cones:[{spellID:10,label:'撕裂',timeMs:1600,casterID:1,origin:{x:0,y:0},facingRadians:0},
           {spellID:20,label:'灵魂撕裂',timeMs:5000,casterID:1,origin:{x:0,y:0},facingRadians:0},
           {spellID:30,label:'凋零撕裂',timeMs:9000,casterID:1,origin:{x:0,y:0},facingRadians:0}],
    gloombomb:{rounds:[{targets:[{playerID:1,applyTimeMs:1000,explodeTimeMs:1800,position:{x:0,y:0}}]}]}},
  guillotineTelegraphs:[{playerID:1,startTimeMs:1000,endTimeMs:1800,radiusYards:6}]};
replay.mount(host(),basic,10000,project);
const restored=captured[2];
assert(restored.adapter.renderMap(null,[],1400,{}).includes('data-key="orb:'));
assert(restored.adapter.renderMap(null,[],1400,{}).includes('data-key="cone:10:1600"'));
assert(restored.adapter.renderMap(null,[],4800,{}).includes('data-key="cone:20:5000"'));
assert(restored.adapter.renderMap(null,[],8800,{}).includes('data-key="cone:30:9000"'));
assert(restored.scene.events.some(e=>e.id==='bomb:1:1000'));
assert(restored.adapter.renderMap(null,[],1400,{}).includes('data-effect="guillotine-share-warning"'));
assert(!restored.adapter.renderMap(null,[],1800,{}).includes('data-effect="guillotine-share-warning"'));
assert(restored.adapter.renderMap(null,[],1900,{}).includes('data-effect="guillotine-runout" data-radius-yards="40"'));
assert(!restored.adapter.renderMap(null,[],7800,{}).includes('data-effect="guillotine-runout"'));
api.mount=original;
console.log('Replay keeps orbs, P1/P2/P3 frontals and bombs with every review section disabled');
