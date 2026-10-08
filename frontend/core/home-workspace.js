(() => {
  'use strict';
  const $=id=>document.getElementById(id),esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  $('reportEntry').onsubmit=event=>{event.preventDefault();const raw=$('homeReport').value.trim(),match=raw.match(/^([A-Za-z0-9]{16})$/)||raw.match(/^https?:\/\/([a-z]+\.)?warcraftlogs\.com\/reports\/([A-Za-z0-9]{16})(?:[/?#]|$)/i);if(!match){$('entryMessage').textContent='请输入 16 位 Report ID 或完整 WCL 链接。';return;}const code=match[2]||match[1],fight=raw.match(/(?:[?#&])fight=(\d+)/)?.[1],params=new URLSearchParams({report:code});if(fight)params.set('fight',fight);location.href='/single-fight?'+params;};
  fetch('/boss_catalog.json').then(r=>{if(!r.ok)throw Error('目录读取失败');return r.json();}).then(data=>{
    const card=(version,raid,b)=>{const params=new URLSearchParams({version:version.version,raid:raid.key,boss:b.key}),fallback='frontend/assets/theme/hero-abyss-960.webp',image=b.previewImage||fallback,order=b.order?String(b.order).padStart(2,'0'):'';return `<a class="boss-entry${b.previewImage?'':' no-art'}" href="/online?${esc(params)}"><img loading="lazy" src="/${esc(image)}" alt=""><div>${order?`<small>${esc(order)}</small>`:''}<strong>${esc(b.name)}</strong><span>选择日志与机制配置 →</span></div></a>`;};
    const raids=[...data.versions].reverse().flatMap(version=>(version.raids||[]).map(raid=>({version,raid,bosses:(raid.bosses||[]).filter(b=>b.supported).sort((a,b)=>Number(a.order||0)-Number(b.order||0))}))).filter(x=>x.bosses.length);
    const block=x=>`<section class="boss-raid"><h3>${esc(x.raid.name)}<em>${esc(x.version.version)}</em></h3><div class="boss-grid">${x.bosses.map(b=>card(x.version,x.raid,b)).join('')}</div></section>`;
    const big=raids.filter(x=>x.bosses.length>=3),small=raids.filter(x=>x.bosses.length<3);
    $('homeBossCatalog').innerHTML=big.map(block).join('')+(small.length?`<div class="boss-mini">${small.map(block).join('')}</div>`:'');
  }).catch(error=>$('homeBossCatalog').textContent=error.message);
  fetch('/assets/demos/manifest.json').then(r=>{if(!r.ok)throw Error('暂无已生成的样例');return r.json();}).then(data=>{
    const demos=data.demos||[];function select(index){$('homeDemoTabs').querySelectorAll('button').forEach((b,i)=>b.classList.toggle('active',i===index));const panel=$('homeDemoPanel'),frame=$('homeDemoFrame');if(panel){panel.classList.add('loading');frame.onload=()=>panel.classList.remove('loading');}frame.src='/demos?embed=1&boss='+encodeURIComponent(demos[index].key);}
    $('homeDemoTabs').innerHTML=demos.map(d=>`<button type="button">${esc(d.label)}</button>`).join('');$('homeDemoTabs').querySelectorAll('button').forEach((b,i)=>b.onclick=()=>select(i));if(demos.length)select(0);
  }).catch(error=>{$('homeDemoTabs').textContent=error.message;$('homeDemoFrame').hidden=true;});
  const reveals=document.querySelectorAll('.reveal');if('IntersectionObserver' in window&&!matchMedia('(prefers-reduced-motion: reduce)').matches){document.documentElement.classList.add('js-reveal');const io=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}}),{rootMargin:'0px 0px -8% 0px'});reveals.forEach(el=>io.observe(el));}else reveals.forEach(el=>el.classList.add('in'));
})();
