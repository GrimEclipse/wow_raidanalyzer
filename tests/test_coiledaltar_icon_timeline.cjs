const assert=require('node:assert/strict');
global.CoiledAltarGuildView=require('../frontend/report/plugins/venomous_abyss/coiledaltar/guild-timeline.js');
const {makeModel}=require('../frontend/report/plugins/venomous_abyss/coiledaltar/icon-timeline.js');
const roster=[{id:1,name:'Mage',role:'range-dps',icon:'mage-arcane',classColor:'#3FC7EB'},
 {id:2,name:'Heal',role:'range-healer',icon:'druid-restoration'}];
const guild={bossComparison:{phaseTimeline:[{key:'p1',timeMs:0}],events:[]},displayTimelines:[
 {playerID:1,player:'Mage',role:'range-dps',ability:'mage.arcane-surge',label:'Surge',category:'major-burst',spellIDs:[365350],casts:[3000],intervals:[{startTimeMs:3000,endTimeMs:18000}],plannedWindows:[{timeMs:180000,endTimeMs:180000,windowStartMs:170000,windowEndMs:190000}]},
 {playerID:1,player:'Mage',ability:'item.1250533',label:'Item',category:'trinket',spellIDs:[1250533],casts:[5000],plannedWindows:[{timeMs:0}]}
]};
const pull={fightID:5,durationMs:240000,players:roster,coiledaltar:{guildTimeline:guild}};
const assets={icons:{365350:'/assets/spells/365350.jpg'},reference:{id:'old-m'},defs:[],bossIDs:{}};
const model=makeModel(guild,pull,[pull],'dps',assets);
assert.equal(model.current.players.length,1);
assert.deepEqual(model.current.players[0].s[0].plan,[[180,180,170,190]]);
assert.deepEqual(model.current.players[0].s[1].plan,[]);
assert.equal(model.skills['item.1250533'].kind,'item');
assert.equal(model.images['mage-arcane'],'/assets/specs/mage-arcane.jpg');
assert.equal(makeModel(guild,pull,[pull],'all',assets).current.players.length,2);
assert.equal(makeModel({},pull,[pull],'dps',assets),null);
assert.equal(model.references[0].id,'night-5');
console.log('Icon timeline model preserves fixed major plans, hides item plans and filters by roster');
