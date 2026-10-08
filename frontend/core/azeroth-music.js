/* Azeroth UI · 背景音乐（各版本主题与代表曲，跨页续播）
 * 曲目：《魔兽世界》各版本官方主题曲 + 各版本最具代表性的 Boss 战曲：
 *   巫妖王之怒 · A Call to Arms（佛丁代表曲）
 *   熊猫人之谜 · The Wandering Isle（浮岛）
 *   争霸艾泽拉斯 · 达萨罗之战 拉斯塔哈大王 / 吉安娜 Boss 战
 *   地心之战 · 迪门修斯 Vita Mundus Devora（最终 Boss）
 *   至暗之夜 · March On Quel'Danas（鲁拉 Boss 战）
 *
 * 进站自动播放策略（浏览器铁律：无任何用户交互前不一定允许出声）：
 *   1) 脚本一挂载就立刻尝试播放，失败 1.5s 后再试一次（媒体元素已被预热，
 *      老访客/有媒体参与度的一律放行）；
 *   2) 仍被拦下就挂一次性手势监听：你在这一页第一次点/滚/按键时自动接上，
 *      不必去点播放器；
 *   3) 点「更新公告 / 版本更新信息」（关闭公告那一刻）直接出声；
 *   4) 切回标签页 / 元素卡顿时补播；
 *   5) 曲目、进度、音量、开关写 localStorage，换页面不中断，下次进站续播。
 */
(function () {
  if (window.__azerothMusic) return;
  window.__azerothMusic = true;

  // 各版本主题曲 + 各版本最具代表性的 Boss 战曲 / 剧情曲
  var TRACKS = [
    { f: "01-classic-legends-of-azeroth.mp3",    n: "Legends of Azeroth",              c: "经典" },
    { f: "02-tbc-the-burning-legion.mp3",        n: "The Burning Legion",              c: "燃烧的远征" },
    { f: "03-wotlk-lich-king.mp3",               n: "Wrath of the Lich King 主标题",   c: "巫妖王之怒" },
    { f: "wotlk-a-call-to-arms.mp3",             n: "A Call to Arms · 佛丁",           c: "巫妖王之怒" },
    { f: "04-cataclysm-the-shattering.mp3",      n: "The Shattering",                  c: "大地的裂变" },
    { f: "05-mop-heart-of-pandaria.mp3",         n: "Heart of Pandaria",               c: "熊猫人之谜" },
    { f: "mop-wandering-isle.mp3",               n: "The Wandering Isle · 浮岛",       c: "熊猫人之谜" },
    { f: "06-wod-times-change.mp3",              n: "Times Change",                    c: "德拉诺之王" },
    { f: "07-legion-kingdoms-will-burn.mp3",     n: "Kingdoms Will Burn",              c: "军团再临" },
    { f: "08-bfa-before-the-storm.mp3",          n: "Before the Storm",                c: "争霸艾泽拉斯" },
    { f: "bfa-king-rasthakan.mp3",               n: "King Rasthakan · 达萨罗 Boss 战", c: "争霸艾泽拉斯" },
    { f: "bfa-lady-jaina-proudmoore.mp3",        n: "Lady Jaina · 达萨罗 Boss 战",     c: "争霸艾泽拉斯" },
    { f: "09-shadowlands-king-and-queen.mp3",    n: "The King & The Queen",            c: "暗影国度" },
    { f: "10-dragonflight-isles-awaken.mp3",     n: "The Isles Awaken",                c: "巨龙时代" },
    { f: "11-tww-the-war-within.mp3",            n: "The War Within 主标题",           c: "地心之战" },
    { f: "tww-vita-mundus-devora.mp3",           n: "Vita Mundus Devora · 迪门修斯",   c: "地心之战" },
    { f: "12-midnight-main-title.mp3",           n: "Midnight 主标题",                 c: "至暗之夜" },
    { f: "midnight-march-on-queldanas.mp3",      n: "March On Quel'Danas · 鲁拉",      c: "至暗之夜" }
  ];
  var DIR = "/frontend/assets/music/";
  var LS = "azerothMusic.v4";
  var st = { on: true, i: 0, t: 0, v: 0.45, open: false };   // on 默认 true：进站就尝试播放
  try {
    var raw = localStorage.getItem(LS);
    if (raw) {
      var saved = JSON.parse(raw);
      // 曲库换过（曲目数变了），旧索引按曲目名对齐，找不到就回 0
      if (saved.i >= TRACKS.length) st.i = 0;
      else st = Object.assign(st, saved);
    }
  } catch (e) {}
  if (!(st.i >= 0 && st.i < TRACKS.length)) st.i = 0;
  if (!(st.v >= 0 && st.v <= 1)) st.v = 0.5;
  function save() { try { localStorage.setItem(LS, JSON.stringify(st)); } catch (e) {} }

  var audio = new Audio();
  audio.preload = "auto";
  audio.volume = st.v;
  audio.loop = false;

  var css = document.createElement("style");
  css.textContent = [
    ".aze-mu{position:fixed;left:18px;bottom:18px;z-index:99991;font:500 13px/1.35 'Segoe UI','Microsoft YaHei',system-ui,sans-serif;color:#ede4d3}",
    ".aze-mu-bar{display:flex;align-items:center;gap:8px;padding:7px 12px 7px 9px;border:1px solid #6b5334;border-radius:24px;",
    "background:linear-gradient(180deg,rgba(38,29,20,.94),rgba(18,14,10,.96));box-shadow:0 8px 24px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,209,0,.14);",
    "backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);cursor:pointer;user-select:none}",
    ".aze-mu-bar:hover{border-color:#c69b6d}",
    ".aze-mu-ico{width:24px;height:24px;flex:0 0 24px;display:grid;place-items:center;border-radius:50%;",
    "background:radial-gradient(circle at 35% 30%,#8c2a17,#4d0f07);border:1px solid #c69b6d;color:#ffd100;font-size:11px}",
    ".aze-mu-txt{max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#d8cbb6}",
    ".aze-mu.on .aze-mu-txt{color:#ffd100}",
    ".aze-mu-panel{position:absolute;left:0;bottom:calc(100% + 8px);width:300px;max-height:62vh;overflow:auto;padding:10px;border:1px solid #6b5334;border-radius:5px;",
    "background:linear-gradient(180deg,rgba(32,25,18,.97),rgba(15,12,9,.98));box-shadow:0 14px 34px rgba(0,0,0,.6);display:none}",
    ".aze-mu.open .aze-mu-panel{display:block}",
    ".aze-mu-title{display:flex;align-items:center;justify-content:space-between;font-family:Cinzel,Georgia,serif;color:#c69b6d;font-size:11px;letter-spacing:.08em;margin:0 0 7px 2px}",
    ".aze-mu-ctl{display:flex;align-items:center;gap:6px;margin:0 2px 8px}",
    ".aze-mu-ctl button{min-width:30px;height:28px;border:1px solid #6b5334;border-radius:4px;background:#241a12;color:#e8ddc9;cursor:pointer;font:600 12px/1 inherit}",
    ".aze-mu-ctl button:hover{border-color:#c69b6d}",
    ".aze-mu-row{display:flex;align-items:center;gap:7px;padding:5px 7px;border-radius:3px;cursor:pointer;color:#cbbda6}",
    ".aze-mu-row:hover{background:rgba(255,209,0,.07);color:#ede4d3}",
    ".aze-mu-row.active{background:rgba(255,128,0,.13);color:#ffd100}",
    ".aze-mu-row i{font-style:normal;width:15px;color:#c69b6d}",
    ".aze-mu-row em{margin-left:auto;padding:1px 6px;border:1px solid #57452f;border-radius:999px;color:#a08e76;font-size:10px;font-style:normal}",
    ".aze-mu-vol{display:flex;align-items:center;gap:8px;margin-top:8px;padding:0 2px;color:#a2917a}",
    ".aze-mu-vol input{flex:1;accent-color:#b8291b}",
    ".aze-mu-cred{margin:8px 2px 0;padding-top:7px;border-top:1px solid #3a2e20;color:#8f7f6c;font-size:10px;line-height:1.5}",
    "@media(max-width:720px){.aze-mu{left:12px;bottom:12px}.aze-mu-txt{max-width:104px}.aze-mu-panel{width:min(88vw,300px)}}",
    "@media(max-width:520px){.aze-mu-txt{display:none}.aze-mu-bar{padding:7px 9px}}"
  ].join("");
  document.head.appendChild(css);

  var wrap = document.createElement("div");
  wrap.className = "aze-mu";
  wrap.innerHTML =
    '<div class="aze-mu-panel">' +
      '<div class="aze-mu-title"><span>\u5404\u7248\u672c\u4e3b\u9898\u66f2</span><span class="aze-mu-cnt"></span></div>' +
      '<div class="aze-mu-ctl">' +
        '<button type="button" data-act="prev" title="\u4e0a\u4e00\u9996">&#8249;</button>' +
        '<button type="button" data-act="play" title="\u64ad\u653e / \u6682\u505c">&#9654;</button>' +
        '<button type="button" data-act="next" title="\u4e0b\u4e00\u9996">&#8250;</button>' +
      '</div>' +
      TRACKS.map(function (t, i) {
        return '<div class="aze-mu-row" data-i="' + i + '"><i>' + (i + 1) + '</i><span>' + t.n + '</span><em>' + t.c + '</em></div>';
      }).join("") +
      '<div class="aze-mu-vol"><span>\u97f3\u91cf</span><input type="range" min="0" max="100" value="' + Math.round(st.v * 100) + '"></div>' +
      '<div class="aze-mu-cred">\u66f2\u76ee\uff1a\u300a\u9b54\u5c16\u4e16\u754c\u300b\u5404\u7248\u672c\u5b98\u65b9\u4e3b\u9898\u66f2\uff08\u539f\u58f0\u4e13\u8f91\u4e3b\u6807\u9898\u66f2\u9769\uff09\u3002</div>' +
    '</div>' +
    '<div class="aze-mu-bar"><span class="aze-mu-ico">&#9835;</span><span class="aze-mu-txt">\u80cc\u666f\u97f3\u4e50</span></div>';

  function q(s) { return wrap.querySelector(s); }
  var rows = [].slice.call(wrap.querySelectorAll(".aze-mu-row"));

  function src(i) { return DIR + encodeURIComponent(TRACKS[i].f); }
  var armed = false, fire = null;
  function paint() {
    var txt = q(".aze-mu-txt"), ico = q(".aze-mu-ico");
    wrap.classList.toggle("on", st.on);
    wrap.classList.toggle("open", st.open);
    q(".aze-mu-cnt").textContent = (st.i + 1) + " / " + TRACKS.length;
    q('[data-act="play"]').innerHTML = audio.paused ? "&#9654;" : "&#10074;&#10074;";
    ico.innerHTML = audio.paused ? "&#9835;" : "&#9834;";
    if (!st.on) txt.textContent = "\u80cc\u666f\u97f3\u4e50";
    else if (!audio.paused && !audio.muted) txt.textContent = TRACKS[st.i].n + " \u00b7 " + TRACKS[st.i].c;
    else if (!audio.paused && audio.muted) txt.textContent = "\u9759\u97f3\u9884\u70ed\u4e2d\u00b7\u70b9\u4e00\u4e0b\u5f00\u59cb";
    else txt.textContent = armed ? "\u70b9\u4e00\u4e0b\u5f00\u59cb" : "\u80cc\u666f\u97f3\u4e50";
    rows.forEach(function (r, i) { r.classList.toggle("active", st.on && i === st.i); });
    if ("mediaSession" in navigator && window.MediaMetadata) {
      try { navigator.mediaSession.metadata = new window.MediaMetadata({ title: TRACKS[st.i].n, artist: "\u5404\u7248\u672c\u4e3b\u9898\u66f2", album: "\u9b54\u5c16\u4e16\u754c \u80cc\u666f\u97f3\u4e50" }); } catch (e) {}
    }
  }

  // 静音预热：浏览器铁律是「无交互不放行有声播放，但静音播放永远放行」。
  // 进站先把音乐无声跑起来（解码、缓冲、进度都走起来），等用户第一次
  // 滚动/点击/按键时直接取消静音 —— 无缝出声，不用重载、不用从头再来。
  var warmed = false;
  function warmStart() {
    if (warmed || !audio.paused) return;
    try {
      audio.muted = true;
      var p = audio.play();
      if (p && p.catch) p.then(function () { warmed = true; }).catch(function () {});
    } catch (e) {}
  }
  function unMute() {
    try { audio.muted = st.v === 0; } catch (e) {}
    paint();
  }

  // 手势兜底：没有任何交互前浏览器禁止出声，这里等第一次交互再自动开始
  var EVS = ["pointerdown", "click", "keydown", "touchstart", "wheel", "scroll"];
  function disarm() {
    if (!armed || !fire) return;
    EVS.forEach(function (e) { window.removeEventListener(e, fire, true); });
    armed = false; fire = null;
  }
  function arm() {
    if (armed) return;
    armed = true;
    fire = function () {
      disarm();
      if (!audio.paused) { unMute(); return; }  // 静音预热中 → 直接取消静音
      start(st.i, st.t);
    };
    EVS.forEach(function (e) { window.addEventListener(e, fire, true); });
  }
  var retries = 0;
  function tryPlay() {
    try { audio.muted = st.v === 0; } catch (e) {}   // 先取消静音再请求有声播放
    var p = audio.play();
    if (p && p.catch) {
      p.then(function () {
        st.on = true; save(); disarm();
        paint();
      }).catch(function () {
        // 被拦下：静音预热（元素跑起来），1.5s 后再试一次有声的，
        // 仍不行就等本页第一次点/滚/按键时无缝取消静音
        warmStart();
        if (retries < 1) {
          retries++;
          setTimeout(function () {
            if (!st.on || audio.paused || audio.muted) tryPlay();
          }, 1500);
        }
        arm(); paint();
      });
    }
    return p;
  }
  function load(i, seek) {
    st.i = (i + TRACKS.length) % TRACKS.length;
    st.t = seek || 0;
    audio.src = src(st.i);
    if (seek) {
      audio.addEventListener("loadedmetadata", function once() {
        audio.removeEventListener("loadedmetadata", once);
        try { audio.currentTime = seek; } catch (e) {}
      });
    }
    paint();
  }
  function start(i, seek) {
    st.on = true; retries = 0; save();
    load(i, seek || 0);
    tryPlay();
  }
  function toggle() {
    if (audio.paused) tryPlay(); else audio.pause();
    paint();
  }

  q(".aze-mu-bar").addEventListener("click", function (e) {
    e.stopPropagation();
    st.open = !st.open;
    if (!st.on || audio.paused) { st.on = true; save(); start(st.i, st.t); }
    save(); paint();
  });
  rows.forEach(function (r) {
    r.addEventListener("click", function (e) { e.stopPropagation(); start(Number(r.dataset.i), 0); });
  });
  q('[data-act="play"]').addEventListener("click", function (e) {
    e.stopPropagation();
    if (audio.paused) { st.on = true; save(); tryPlay(); }
    else { st.on = false; save(); audio.pause(); paint(); }
  });
  q('[data-act="prev"]').addEventListener("click", function (e) { e.stopPropagation(); start(st.i - 1, 0); });
  q('[data-act="next"]').addEventListener("click", function (e) { e.stopPropagation(); start(st.i + 1, 0); });
  q(".aze-mu-vol input").addEventListener("input", function (e) { audio.volume = st.v = Number(e.target.value) / 100; save(); });
  q(".aze-mu-vol input").addEventListener("click", function (e) { e.stopPropagation(); });
  document.addEventListener("click", function () { if (st.open) { st.open = false; save(); paint(); } });
  audio.addEventListener("ended", function () { start(st.i + 1, 0); });
  audio.addEventListener("error", function () {
    // 当前文件没加载出来时跳到下一首，别卡死
    if (!audio.paused || st.on) { if (retries < 2) { retries++; start(st.i + 1, 0); } else { st.on = false; save(); paint(); } }
  });
  audio.addEventListener("stalled", function () { if (st.on && !audio.paused) { tryPlay(); } });
  audio.addEventListener("play", paint);
  audio.addEventListener("pause", function () { st.t = audio.currentTime; save(); paint(); });
  audio.addEventListener("timeupdate", function () { if (!audio.paused) st.t = audio.currentTime; });
  setInterval(function () { if (!audio.paused) { st.t = audio.currentTime; save(); } }, 4000);
  window.addEventListener("pagehide", function () { st.t = audio.currentTime; save(); });
  // 切回标签页时补播（部分浏览器切走会自动暂停）
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && st.on && audio.paused) tryPlay();
  });

  function mount() {
    document.body.appendChild(wrap);
    load(st.i, st.t > 3 ? st.t : 0);
    var noticeOk = 0;
    try { noticeOk = Number(sessionStorage.getItem("azeMu.noticeOk") || 0); } catch (e) {}
    // 「版本更新公告」是进站后用户做的第一件事：点「关闭公告」那一刻就是第一声。
    // 若是从登录页关公告跨页跳过来的（30 秒内标记），直接出声，不再等滚动。
    if (st.on) {
      tryPlay();                          // 第一枪：允许就直接响
      if (noticeOk && Date.now() - noticeOk < 30000) {
        var gun = function () {          // 跨页后：正在静音播就直接开声，卡住就补一枪
          if (!st.on) return;
          if (!audio.paused && audio.muted) { try { audio.muted = st.v === 0; } catch (e) {} paint(); }
          else if (audio.paused) tryPlay();
        };
        setTimeout(gun, 1200);
        setTimeout(gun, 2800);
        setTimeout(gun, 5200);
      } else {
        setTimeout(function () {            // 第二枪：预热后重试
          if (st.on && audio.paused) tryPlay();
        }, 1500);
      }
    }
    arm();                               // 被浏览器拦下时，本页第一次点/滚就自动接上
    paint();
  }
  if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount);

  window.AzerothMusic = {
    play: function () { st.on = true; save(); return tryPlay(); },
    pause: function () { audio.pause(); },
    next: function () { start(st.i + 1, 0); },
    // 「点关闭公告」专用：把这次点击当作手势，立刻出声。
    // 正在静音预热 → 直接取消静音；没播 → 带着手势直接播。
    unlock: function () {
      st.on = true; save();
      if (!audio.paused && audio.muted) { try { audio.muted = st.v === 0; } catch (e) {} paint(); }
      else if (audio.paused) tryPlay();
      paint();
    },
    current: function () { return { title: TRACKS[st.i].n, paused: audio.paused, time: audio.currentTime, on: st.on, muted: audio.muted, readyState: audio.readyState, networkState: audio.networkState }; }
  };
})();
