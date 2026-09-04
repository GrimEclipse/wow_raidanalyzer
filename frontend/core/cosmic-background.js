(() => {
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const canvas = document.createElement('canvas');
  canvas.id = 'cosmicCanvas';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const context = canvas.getContext('2d', {alpha:true});
  let width=0,height=0,ratio=1,points=[],rotation=0,velocity=.00008,pointerX=0,pointerY=0;
  let dragging=false,lastX=0,lastY=0,dragVX=0,dragVY=0;
  const density = Math.max(120, Math.min(520, Number(document.body.dataset.cosmicDensity || 320)));
  function seed(){
    points=Array.from({length:innerWidth<700?Math.round(density*.55):density},(_,index)=>{
      const arm=index%3, radius=Math.pow(Math.random(),.62), angle=radius*11+arm*Math.PI*2/3+(Math.random()-.5)*.42;
      return {radius,angle,size:.35+Math.random()*1.8,alpha:.18+Math.random()*.76,warm:Math.random()<.12,depth:.35+Math.random()*.9};
    });
  }
  function resize(){
    width=innerWidth;height=innerHeight;ratio=Math.min(devicePixelRatio||1,1.7);
    canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);
    canvas.style.width=`${width}px`;canvas.style.height=`${height}px`;seed();if(reducedMotion)draw(performance.now());
  }
  function draw(time){
    context.setTransform(ratio,0,0,ratio,0,0);context.clearRect(0,0,width,height);
    const cx=width*(width<760?.58:.68)+pointerX*18,cy=height*.31+pointerY*12;
    const scale=Math.min(width,height)*.52;
    rotation += reducedMotion ? 0 : velocity;
    velocity*=dragging?1:.985;velocity+=dragVX*.000012;dragVX*=.9;dragVY*=.9;
    for(const point of points){
      const angle=point.angle+rotation*point.depth;
      const squash=.48+pointerY*.025;
      const x=cx+Math.cos(angle)*point.radius*scale+pointerX*point.depth*9;
      const y=cy+Math.sin(angle)*point.radius*scale*squash+pointerY*point.depth*7;
      const glow=point.size*(.8+point.depth*.55);
      context.beginPath();context.arc(x,y,glow,0,Math.PI*2);
      context.fillStyle=point.warm?`rgba(255,196,150,${point.alpha})`:`rgba(205,231,255,${point.alpha})`;context.fill();
      if(point.size>1.55){context.shadowBlur=12;context.shadowColor=point.warm?'#ffb98d':'#a9dbff';context.fill();context.shadowBlur=0;}
    }
    if(!reducedMotion) requestAnimationFrame(draw);
  }
  addEventListener('pointermove',event=>{
    pointerX=event.clientX/Math.max(1,width)-.5;pointerY=event.clientY/Math.max(1,height)-.5;
    if(dragging){dragVX=event.clientX-lastX;dragVY=event.clientY-lastY;rotation+=dragVX*.0028;lastX=event.clientX;lastY=event.clientY;}
  },{passive:true});
  addEventListener('pointerdown',event=>{
    if(event.target.closest('a,button,input,select,textarea,label'))return;
    dragging=true;lastX=event.clientX;lastY=event.clientY;document.body.classList.add('cosmic-dragging');
  });
  addEventListener('pointerup',()=>{dragging=false;velocity+=dragVX*.00004;document.body.classList.remove('cosmic-dragging')});
  addEventListener('pointercancel',()=>{dragging=false;document.body.classList.remove('cosmic-dragging')});
  addEventListener('resize',resize,{passive:true});resize();if(!reducedMotion)requestAnimationFrame(draw);
})();
