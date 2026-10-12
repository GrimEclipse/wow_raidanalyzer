const assert=require('node:assert/strict');
const {sszCrossPolygons,sszConePoints}=require('../frontend/report/plugins/venomous_abyss/sszorak/mechanics.js');
const arena={rotationDegrees:60},a=Math.PI/3;
const project=p=>({x:p.x*Math.cos(a)-p.y*Math.sin(a),y:-(p.x*Math.sin(a)+p.y*Math.cos(a))});
for(const angle of [0,45]){
  const bars=sszCrossPolygons({screenAngleDegrees:angle,halfLengthYards:6,widthYards:3},{x:0,y:0},arena,project);
  assert.equal(bars.length,2);
  const p=bars[0],dx=p[1].x-p[0].x,dy=p[1].y-p[0].y;
  assert(Math.abs(Math.hypot(dx,dy)-1200)<1e-8);
  assert(Math.abs(Math.hypot(p[2].x-p[1].x,p[2].y-p[1].y)-300)<1e-8);
  assert(Math.abs(Math.atan2(dy,dx)*180/Math.PI-angle)<1e-8);
}
const cone={angleDegrees:60,lengthYards:30};
const points=sszConePoints(cone,{x:0,y:0},{x:100,y:0},p=>p);
assert.equal(points.length,18);
assert(Math.abs(Math.atan2(points[1].y,points[1].x)*180/Math.PI+30)<1e-8);
assert(Math.abs(Math.hypot(points.at(-1).x,points.at(-1).y)-3000)<1e-8);
console.log('Sszorak fixed cross axes, world projection and frontal geometry passed');
