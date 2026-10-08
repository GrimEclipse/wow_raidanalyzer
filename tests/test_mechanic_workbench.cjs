const assert=require('node:assert/strict');
require('../frontend/core/mechanic-workbench.js');
const api=globalThis.MechanicWorkbench;
// Frame-rate-independent interpolation; long gaps hold a labelled known point.
assert.deepEqual(api.trackPosition({samples:[[0,10,20],[1000,30,40]]},500),{x:20,y:30,stale:false});
assert.deepEqual(api.trackPosition({samples:[[0,10,20],[10000,30,40]]},6000),{x:10,y:20,stale:true});
assert.equal(api.trackPosition({samples:[]},500),null);
const portrait=api.avatar({key:'1:0',name:'Mage',icon:'/assets/specs/mage-arcane.jpg',color:'#3FC7EB'},{x:5,y:6},11,true);
assert.ok(portrait.includes('<image href="/assets/specs/mage-arcane.jpg"'));
assert.ok(portrait.includes('fill="#ff223b"'));
const events=[{actor:'A',layer:'X',timeMs:0,group:1,amount:12,problem:false},{actor:'A',layer:'Y',timeMs:20,group:2,amount:50,problem:true},{actor:'B',layer:'X',timeMs:30,group:2,amount:5,problem:true}];
assert.deepEqual(api.filterEvents(events,{actor:'A',layers:['Y'],from:0,to:100}),[events[1]]);
assert.deepEqual(api.filterEvents(events,{problemOnly:true,from:25,to:100}),[events[2]]);
const matrix=api.aggregate(events,'actor','layer','amount');
assert.equal(matrix.values.get(JSON.stringify(['A','Y'])),50);
assert.equal(matrix.values.get(JSON.stringify(['B','X'])),5);
const config=api.cleanConfig({from:-5,to:10000,rowKey:'__proto__',view:'other',layers:['missing']},100,['X']);
assert.equal(config.from,0);assert.equal(config.to,100);assert.equal(config.view,'map');assert.equal(config.layers.length,0);
// Reference vectors stay aligned after a non-square coordinate projection.
const guides=api.projectGuides({guides:[{origin:{x:10,y:20},axis:{x:1,y:0}},{origin:{x:10,y:20},axis:{x:0,y:1}}]},p=>({x:p.x/10,y:100-p.y/20}));
assert.equal(guides.length,2);
assert.equal(guides[0].y1,guides[0].y2);
assert.equal(guides[1].x1,guides[1].x2);
assert.deepEqual(api.projectGuides({guides:[{origin:{x:0,y:0},axis:{x:0,y:0}}]},p=>p),[]);
assert.deepEqual(api.projectGuides({guides:[{origin:{x:0,y:0},axis:{x:1,y:0}}]},()=>null),[]);
assert.equal(api.cleanConfig({rowKey:'role',columns:['role']},100,[]).rowKey,'role');
console.log('mechanic-workbench filters, matrix and preset validation passed');
