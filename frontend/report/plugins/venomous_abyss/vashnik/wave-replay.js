/* Vashnik geometry and deterministic replay, driven by the battle cursor. */
(function(root){
  'use strict';
  const axes=[{x:1,y:0},{x:0,y:1},{x:-1,y:0},{x:0,y:-1}];
  function project(point,p){const dx=point.x-p.worldAnchor.x,dy=point.y-p.worldAnchor.y,m=p.matrix;return {x:p.imageAnchor.x+m[0]*dx+m[1]*dy,y:p.imageAnchor.y+m[2]*dx+m[3]*dy};}
  function band(origin,axis,near,far,width){const n={x:-axis.y,y:axis.x},at=(d,w)=>({x:origin.x+axis.x*d+n.x*w,y:origin.y+axis.y*d+n.y*w});return [at(near,-width/2),at(far,-width/2),at(far,width/2),at(near,width/2)];}
  function waves(round,cursor,simulation){
    if(!round)return [];
    const speed=simulation.speedYardsPerSecond*100,range=simulation.rangeYards*100,width=simulation.widthYards*100;
    return round.players.filter(p=>p.referenceAvailable&&p.ending!=='death'&&p.position).flatMap(p=>{
      const elapsed=(cursor-p.timeMs)/1000;
      if(elapsed<0||elapsed>range/speed+1)return [];
      const front=Math.min(range,elapsed*speed),tail=Math.max(0,front-800),fade=Math.min(1,range/speed+1-elapsed);
      return axes.map(axis=>({player:p.player,eventID:p.eventID,axis,front,fade,
        path:band(p.position,axis,0,front,width),tail:band(p.position,axis,tail,front,width),
        head:band(p.position,axis,Math.max(0,front-150),front,width),
        crest:[{x:p.position.x+axis.x*front-axis.y*width/2,y:p.position.y+axis.y*front+axis.x*width/2},
               {x:p.position.x+axis.x*(front+120),y:p.position.y+axis.y*(front+120)},
               {x:p.position.x+axis.x*front+axis.y*width/2,y:p.position.y+axis.y*front-axis.x*width/2}]}));
    });
  }
  function totemState(unit,cursor){
    const born=unit.spawnTimeMs??unit.firstSeenTimeMs;
    if(cursor<born)return 'future';
    if(unit.deathTimeMs!=null&&cursor>=unit.deathTimeMs)return 'dead';
    if(unit.despawnTimeMs!=null&&cursor>=unit.despawnTimeMs)return 'despawned';
    if(unit.castCompletions.some(t=>t<=cursor))return 'completed';
    if(unit.castStarts.some(t=>t<=cursor))return 'casting';
    return 'alive';
  }
  function totemPosition(unit,cursor){return unit.positions.findLast(p=>p.timeMs<=cursor)||unit.positions[0]||null;}
  function contains(point,origin,axis,distance,width){const dx=point.x-origin.x,dy=point.y-origin.y,along=dx*axis.x+dy*axis.y,across=-dx*axis.y+dy*axis.x;return along>=0&&along<=distance&&Math.abs(across)<=width/2;}
  const api={axes,project,band,waves,totemState,totemPosition,contains};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.VashnikReplay=api;
})(typeof window==='undefined'?globalThis:window);
