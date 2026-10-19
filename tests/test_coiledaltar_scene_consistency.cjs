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
assert.equal(captured[1].adapter.video,false);
assert(captured[1].scene.events.some(e=>e.id==='evidence:future'));
assert(!captured[0].adapter.renderMap(null,[],999,{}).includes('data-key="actor:1"'));
api.mount=original;
console.log('Homepage, replay and workbench share identical temporal scene rendering');
