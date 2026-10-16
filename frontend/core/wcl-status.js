/* Small shared-service indicator. The server owns admission decisions. */
(() => {
  'use strict';
  if (window.top !== window || document.querySelector('[data-wcl-status]')) return;
  const host=document.createElement('section');host.className='wcl-status';host.dataset.wclStatus='';
  host.setAttribute('aria-label','WCL 共享额度');
  host.innerHTML='<div class="wcl-status__row"><strong>共享额度</strong><span data-points>查询中</span></div><progress aria-label="共享 WCL 剩余额度" max="100"></progress><div class="wcl-status__note" data-note role="status"></div>';
  (document.querySelector('main>.topbar,main>header,main>.head')||document.body).appendChild(host);
  const css=document.createElement('style');css.textContent='.wcl-status{position:fixed;left:16px;bottom:16px;z-index:90;width:250px;max-width:calc(100vw - 32px);padding:10px 13px;border:1px solid var(--space-line,#69543d);border-radius:9px;background:rgba(24,19,14,.94);color:var(--space-text,#ede4d3);box-shadow:0 4px 20px #0006;font:12px/1.5 system-ui,"Microsoft YaHei",sans-serif}.wcl-status__row{display:flex;justify-content:space-between;gap:12px}.wcl-status progress{display:block;width:100%;height:7px;margin:7px 0;accent-color:#9dc36d}.wcl-status__note{color:var(--space-muted,#c0b1a0)}.wcl-status[data-low="true"] progress{accent-color:#e9ad4b}@media(max-width:650px){.wcl-status{position:static;box-sizing:border-box;width:calc(100% - 32px);max-width:none;margin:12px 16px}}';
  document.head.appendChild(css);
  const progress=host.querySelector('progress'),points=host.querySelector('[data-points]'),note=host.querySelector('[data-note]');
  const number=v=>Math.floor(v).toLocaleString('zh-CN');let busy=false;
  async function refresh(){
    if(busy||document.hidden)return;busy=true;
    try{
      const response=await fetch('/api/wcl/status',{cache:'no-store'});if(!response.ok)throw Error();
      const data=await response.json();
      if(data.remaining==null){progress.removeAttribute('value');points.textContent='暂不可用';note.textContent=data.configured?'额度查询暂不可用':'共享服务尚未配置';return;}
      progress.max=data.limitPerHour;progress.value=data.remaining;
      points.textContent=`${number(data.remaining)} / ${number(data.limitPerHour)}`;
      host.dataset.low=String(!data.available);
      const reset=data.pointsResetIn!=null?`约 ${Math.ceil(data.pointsResetIn/60)} 分钟恢复`:'';
      const usage=data.analysisUsage;
      let access=data.status==='exhausted'?'额度已耗尽':!data.available?'低额度，仅 admin 可发起新请求':usage?'可发起分析':'共享服务可用';
      if(usage&&!usage.available)access=`本小时已达 ${usage.limit} 场，已有任务继续运行`;
      note.textContent=[access,usage&&!usage.exempt?`本小时 ${usage.used} / ${usage.limit} 场`:usage?.exempt?'admin 无场次限制':`普通账户每小时 ${data.analysisLimit} 场`,reset].filter(Boolean).join('，');
      window.dispatchEvent(new CustomEvent('wcl-service-status',{detail:data}));
    }catch(_){points.textContent='查询失败';progress.removeAttribute('value');note.textContent='稍后自动重试';}
    finally{busy=false;}
  }
  refresh();setInterval(refresh,30000);document.addEventListener('visibilitychange',refresh);
})();
