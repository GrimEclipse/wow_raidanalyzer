(() => {
  'use strict';
  const $=id=>document.getElementById(id),esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  $('reportEntry').onsubmit=event=>{event.preventDefault();const raw=$('homeReport').value.trim(),match=raw.match(/^([A-Za-z0-9]{16})$/)||raw.match(/^https?:\/\/([a-z]+\.)?warcraftlogs\.com\/reports\/([A-Za-z0-9]{16})(?:[/?#]|$)/i);if(!match){$('entryMessage').textContent='请输入 16 位 Report ID 或完整 WCL 链接。';return;}const code=match[2]||match[1],fight=raw.match(/(?:[?#&])fight=(\d+)/)?.[1],params=new URLSearchParams({report:code});if(fight)params.set('fight',fight);location.href='/single-fight?'+params;};
  fetch('/boss_catalog.json').then(r=>{if(!r.ok)throw Error('目录读取失败');return r.json();}).then(data=>{
    $('homeBossCatalog').innerHTML=[...data.versions].reverse().map(version=>(version.raids||[]).map(raid=>{const bosses=(raid.bosses||[]).filter(b=>b.supported).sort((a,b)=>Number(a.order||0)-Number(b.order||0));if(!bosses.length)return '';return `<section class="boss-raid"><h3>${esc(version.version)} · ${esc(raid.name)}</h3><div class="boss-grid">${bosses.map(b=>{const params=new URLSearchParams({version:version.version,raid:raid.key,boss:b.key}),image=b.arenaAssets?.[0]?.path;return `<a class="boss-entry" href="/online?${esc(params)}">${image?`<img loading="lazy" src="/${esc(image)}" alt="">`:''}<div><small>${esc(raid.name)} · ${esc(String(b.order||''))}</small><strong>${esc(b.name)}</strong><span>选择日志与机制配置 →</span></div></a>`;}).join('')}</div></section>`;}).join('')).join('');
  }).catch(error=>$('homeBossCatalog').textContent=error.message);
  fetch('/assets/demos/manifest.json').then(r=>{if(!r.ok)throw Error('暂无已生成的样例');return r.json();}).then(data=>{
    const demos=data.demos||[];function select(index){$('homeDemoTabs').querySelectorAll('button').forEach((b,i)=>b.classList.toggle('active',i===index));$('homeDemoFrame').src='/demos?embed=1&boss='+encodeURIComponent(demos[index].key);}
    $('homeDemoTabs').innerHTML=demos.map(d=>`<button type="button">${esc(d.label)}</button>`).join('');$('homeDemoTabs').querySelectorAll('button').forEach((b,i)=>b.onclick=()=>select(i));if(demos.length)select(0);
  }).catch(error=>{$('homeDemoTabs').textContent=error.message;$('homeDemoFrame').hidden=true;});
})();
