(function(){
  'use strict';
  const list=document.getElementById('recent');
  if(!list)return;
  const heading=list.parentElement.querySelector('h2');
  if(heading)heading.textContent='最近打开（最多 10 条）';
  const button=document.createElement('button');
  button.type='button';
  button.className='cosmic-button';
  button.textContent='一键清除全部';
  button.title='清除浏览器中保存的所有本地报告';
  button.style.marginTop='10px';
  list.before(button);
  button.onclick=async()=>{
    button.disabled=true;
    try{
      await window.MythicReportRuntime.clearLocalPayloads();
      await renderRecent();
      document.getElementById('status').textContent='本地报告记录已清除。';
    }catch(error){
      document.getElementById('status').textContent=`清除失败：${error.message}`;
    }finally{button.disabled=false;}
  };
})();
