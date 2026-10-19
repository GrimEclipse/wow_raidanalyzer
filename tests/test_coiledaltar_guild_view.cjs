const assert=require('node:assert/strict');
const {sortHoldRows,groupBurstRows,phaseTimings}=require('../frontend/report/plugins/venomous_abyss/coiledaltar/guild-timeline.js');
const rows=[{player:'A',damage:300,petDamage:250,castCount:2},{player:'B',damage:100,petDamage:0,castCount:9},{player:'C',damage:200,petDamage:20,castCount:1}];
assert.deepEqual(sortHoldRows(rows).map(r=>r.player),['A','C','B']);
assert.deepEqual(sortHoldRows(rows,'castCount').map(r=>r.player),['B','A','C']);
assert.deepEqual(sortHoldRows(rows,'playerDamage').map(r=>r.player),['C','B','A']);
assert.deepEqual(sortHoldRows(rows,'damage','asc').map(r=>r.player),['B','C','A']);
assert.deepEqual(rows.map(r=>r.player),['A','B','C'],'sorting never mutates the stored evidence');
const roster=[{id:1,name:'A',role:'melee-dps'},{id:2,name:'B',role:'range-dps'},{id:3,name:'Heal',role:'range-healer'}];
const skills=[{playerID:1,player:'A',ability:'one',casts:[0]},{playerID:1,player:'A',ability:'two',casts:[1000]},{playerID:3,player:'Heal',ability:'trinket'}];
const grouped=groupBurstRows(skills,roster,[{player:'B',reason:'spec mismatch'}]);
assert.equal(grouped.length,2,'all DPS appear even without an applicable assignment');
assert.deepEqual(grouped.find(r=>r.playerID===1).skills.map(s=>s.ability),['one','two']);
assert.equal(grouped.find(r=>r.playerID===2).skills.length,0);
assert.equal(grouped.find(r=>r.playerID===2).unresolved[0].reason,'spec mismatch');
assert.equal(groupBurstRows(skills,roster,[],'all').length,3);
assert.equal(groupBurstRows([{playerID:1,player:'Same'},{playerID:2,player:'Same'}]).length,2,'different actor IDs never merge by name');
const timing=phaseTimings({phaseTimeline:[{key:'p1',timeMs:0},{key:'p2',timeMs:160000},{key:'p3',timeMs:385000},{key:'wipe',timeMs:400000}],
  phaseControl:[{phase:'p1',endTimeMs:160000,earliestEndTimeMs:170000,firstDreadmarchTimeMs:179000,firstDreadmarchEarliestTimeMs:185000},
    {phase:'p2',endTimeMs:350000,earliestEndTimeMs:362790}],
  checks:[{phase:'p2',phaseShiftMs:-20000},{phase:'p3',phaseShiftMs:-45000}]});
assert.equal(timing.length,3);
assert.equal(timing[0].endAdvanceMs,10000);
assert(timing[0].advanceLabel.includes('结束早10.0秒')&&timing[0].advanceLabel.includes('行军早6.0秒'));
assert.equal(timing[1].startAdvanceMs,20000);
assert.equal(timing[1].endAdvanceMs,12790,'inherited advance is separate from this phase ending early');
assert(timing[1].advanceLabel.includes('起点早20.0秒')&&timing[1].advanceLabel.includes('结束早12.8秒'));
assert.equal(timing[2].advanceLabel,'起点早45.0秒');
console.log('M7 damage sorting, immutable evidence and one row per DPS with all skills passed');
// Exercise the actual report renderer: a local `window` binding here previously
// threw before the browser's sorting helper could be accessed on Fight entry.
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../frontend/report/plugins/venomous_abyss/coiledaltar/report.js'),'utf8');
const holdSource=source.slice(source.indexOf('function renderHoldEvidence('),source.indexOf('const BURST_COLORS='));
const context={window:{CoiledAltarGuildView:{sortHoldRows}},state:{},esc:String,num:String,player:r=>r.player,
  fmtPhase:t=>(t/1000).toFixed(1),spellLink:String,table:(headers,data)=>JSON.stringify(data)};
vm.createContext(context);
vm.runInContext(holdSource,context);
const rendered=context.renderHoldEvidence({phase:'p1',healthSampleCount:2,thresholds:{5:rows},thresholdWindows:{5:{startTimeMs:160000,endTimeMs:165000,evidenceEndTimeMs:165000}}},5);
assert(rendered.includes('160.0')&&rendered.includes('165.0'));
assert(rendered.indexOf('["A"')<rendered.indexOf('["C"'));
assert(context.renderHoldEvidence({phase:'p1',healthSampleCount:1,thresholds:{}},5).includes('旧报告'));
console.log('Actual hold renderer resolves browser window and renders cutoff evidence on Fight entry');
