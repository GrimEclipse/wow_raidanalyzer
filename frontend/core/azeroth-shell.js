/* Azeroth UI · 全站外壳（ui/wow-reskin）
 * 唯一入口：给任意页面加一行 <script src=".../frontend/core/azeroth-shell.js?v=4"></script>，
 * 由它按 <base> 或脚本自身位置解析出站点根，再挂载：
 *   1) 换皮样式 azeroth-skin.css（暖石+黄铜）
 *   2) 标题字体 Cinzel / 思源宋体子集
 *   3) 炉石酒馆式背景音乐（azeroth-music.js，跨页续播）
 * 这样分发面的每页改动最小，后续改皮只动 core 一个文件。
 */
(function () {
  if (window.__azerothShell) return;
  window.__azerothShell = true;

  var root;
  var base = document.querySelector("base[href]");
  if (base) {
    root = new URL(base.href, location.href).href;
  } else {
    var self = document.currentScript || (function () {
      var s = document.getElementsByTagName("script");
      for (var i = s.length - 1; i >= 0; i--) { if (/azeroth-shell\.js/.test(s[i].src || "")) return s[i]; }
      return null;
    })();
    var src = self ? self.src : location.href;
    root = src.replace(/frontend\/core\/azeroth-shell\.js.*$/, "");
    if (root === src) root = location.origin + "/";
  }
  if (!/\/$/.test(root)) root += "/";

  function abs(p) { return root + p; }

  function addCss() {
    if (document.querySelector('link[data-azeroth-skin]')) return;
    var l = document.createElement("link");
    l.rel = "stylesheet"; l.href = abs("frontend/core/azeroth-skin.css?v=3");
    l.setAttribute("data-azeroth-skin", "1");
    document.head.appendChild(l);
  }
  function addFonts() {
    if (document.querySelector('style[data-azeroth-fonts]')) return;
    var s = document.createElement("style");
    s.setAttribute("data-azeroth-fonts", "1");
    s.textContent =
      '@font-face{font-family:"Cinzel";src:url("' + abs("frontend/assets/fonts/cinzel.woff2") + '") format("woff2");font-weight:400 900;font-display:swap}' +
      '@font-face{font-family:"Azeroth Serif SC";src:url("' + abs("frontend/assets/fonts/serif-sc-700.woff2") + '") format("woff2");font-weight:700;font-display:swap}';
    document.head.appendChild(s);
  }
  function loadScript(url, cb) {
    var s = document.createElement("script");
    s.src = url; s.async = false;
    if (cb) s.onload = cb;
    document.head.appendChild(s);
  }

  addCss(); addFonts();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { loadScript(abs("frontend/core/azeroth-music.js?v=6")); });
  } else {
    loadScript(abs("frontend/core/azeroth-music.js?v=6"));
  }
})();
