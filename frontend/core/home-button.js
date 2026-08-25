/* 统一「返回首页」悬浮按钮：注入到所有功能页面右下角 */
(function () {
  if (window.__homeFloatButton) return;
  window.__homeFloatButton = true;
  function mount() {
    if (document.querySelector("a.home-float")) return;
    var link = document.createElement("a");
    link.className = "home-float";
    link.href = "/";
    link.title = "返回首页";
    link.setAttribute("aria-label", "返回首页");
    link.style.cssText = [
      "position:fixed", "right:18px", "bottom:18px", "z-index:99990",
      "display:inline-flex", "align-items:center", "gap:6px",
      "padding:9px 15px", "border-radius:999px",
      "border:1px solid rgba(146,164,192,.5)",
      "background:rgba(10,14,22,.86)", "color:#e3eaf4",
      "font:600 13px/1 Segoe UI,Microsoft YaHei,system-ui,sans-serif",
      "text-decoration:none", "white-space:nowrap",
      "box-shadow:0 6px 22px rgba(0,0,0,.38)",
      "backdrop-filter:blur(6px)", "-webkit-backdrop-filter:blur(6px)"
    ].join(";");
    link.innerHTML = "<span aria-hidden=\"true\" style=\"font-size:14px;line-height:1\">⌂</span>首页";
    link.addEventListener("mouseenter", function () { link.style.borderColor = "#9fc1ff"; link.style.color = "#ffffff"; });
    link.addEventListener("mouseleave", function () { link.style.borderColor = "rgba(146,164,192,.5)"; link.style.color = "#e3eaf4"; });
    document.body.appendChild(link);
  }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
