/* Nymrissa field replay: mid bubble, 8-way surge, ice orbs/puddles, water jet. */
(function (root) {
  "use strict";
  const WIDTH = 1000, HEIGHT = 620;
  const DIRS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"];
  const BOSS_ICON = "/assets/raids/tidebound_grotto/icons/nymrissa.png";
  const BIG_ICON = "/assets/raids/tidebound_grotto/icons/frostscale.png";

  function boundsOf(replay, arena) {
    if (arena && Number.isFinite(arena.minX) && Number.isFinite(arena.maxX)) {
      return { minX: arena.minX, maxX: arena.maxX, minY: arena.minY, maxY: arena.maxY, centerX: arena.centerX, centerY: arena.centerY, unitsPerYard: arena.unitsPerYard || 100 };
    }
    const xs = [], ys = [];
    for (const unit of replay?.units || []) {
      if (unit.kind !== "player" && unit.kind !== "enemy") continue;
      for (const row of unit.samples || []) { xs.push(row[1]); ys.push(row[2]); }
    }
    if (!xs.length) return null;
    const pad = 800;
    const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad;
    const minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
    return { minX, maxX, minY, maxY, centerX: (minX + maxX) / 2, centerY: (minY + maxY) / 2, unitsPerYard: 100 };
  }

  function project(point, box) {
    if (!point || !box) return null;
    const dx = box.maxX - box.minX || 1, dy = box.maxY - box.minY || 1;
    return { x: ((point.x - box.minX) / dx) * WIDTH, y: (1 - (point.y - box.minY) / dy) * HEIGHT };
  }

  function yardToPx(yards, box) {
    const units = (yards || 10) * (box.unitsPerYard || 100);
    return (units / (box.maxX - box.minX || 1)) * WIDTH;
  }

  function bossUnit(replay) {
    return (replay?.units || []).find(u => u.gameID === 252959 || String(u.name || "").includes("Nymrissa"))
      || (replay?.units || []).find(u => u.actorID === replay?.bosses?.[0]?.actorID);
  }

  function wedgePath(cx, cy, r, index, count = 8) {
    const a0 = -Math.PI / 2 + index * (2 * Math.PI / count) - Math.PI / count;
    const a1 = a0 + 2 * Math.PI / count;
    const pts = [`${cx},${cy}`];
    for (let i = 0; i <= 8; i++) {
      const a = a0 + (a1 - a0) * i / 8;
      pts.push(`${cx + Math.cos(a) * r},${cy + Math.sin(a) * r}`);
    }
    return `M ${pts.join(" L ")} Z`;
  }

  /** Alive only: hide as soon as dead, and drop after samples end. */
  function livingAdd(unit, cursor) {
    const samples = unit.samples || [];
    if (!samples.length) return null;
    const first = samples[0][0], last = samples[samples.length - 1][0];
    if (cursor < first - 400) return null;
    const death = (unit.states || []).find(row => row[1] === "dead" && row[0] >= first - 500);
    if (death && cursor >= death[0]) return null;
    if (!death && cursor > last + 600) return null;
    return { positionTime: Math.min(cursor, last) };
  }

  function portrait(href, x, y, r, key, title) {
    return `<g data-key="${key}"><circle cx="${x}" cy="${y}" r="${r + 1}" fill="#0b1726" stroke="#7dd3fc" stroke-width="2"/><image href="${href}" x="${x - r}" y="${y - r}" width="${r * 2}" height="${r * 2}" style="clip-path:circle(50%)"/><title>${title || ""}</title></g>`;
  }

  function mount(host, mechanics, durationMs) {
    const api = root.MechanicWorkbench;
    const replay = mechanics.combatReplay;
    if (!replay?.units?.length) {
      host.innerHTML = '<div class="empty">这份报告没有整场位置记录，请重新分析后播放场地推演。</div>';
      return null;
    }
    const field = mechanics.fieldReplay || {};
    const bubbles = field.bubbles || mechanics.alluringBubbles || [];
    const surges = mechanics.surgingVortex?.rounds || [];
    const orbReview = mechanics.orbReview || mechanics.frostBarrage?.orbReview || {};
    const frostRounds = mechanics.frostBarrage?.rounds || [];
    const touches = orbReview.touches || [];
    const bursts = orbReview.bursts || [];
    const groundOrbs = field.groundOrbs || mechanics.groundOrbs || [];
    const puddles = field.orbPuddles || mechanics.orbPuddles || [];
    const waterJets = field.waterJets || mechanics.waterJets || [];
    const box = boundsOf(replay, field.arena) || { minX: 0, maxX: 1, minY: 0, maxY: 1, unitsPerYard: 100 };
    // Bubble / surge origin: always the projected map center (arena bounding-box midpoint).
    const midQ = { x: WIDTH / 2, y: HEIGHT / 2 };
    const boss = bossUnit(replay);
    const bossPortrait = field.bossPortrait || mechanics.portraits?.boss || BOSS_ICON;
    const bigPortrait = field.bigMurlocPortrait || mechanics.portraits?.bigMurloc || BIG_ICON;
    const unitOf = id => (replay.units || []).find(u => u.actorID === id && u.kind === "player");
    const posOf = (id, t) => {
      const unit = unitOf(id);
      return unit && api.trackPosition(unit, t, replay.interpolateMaxGapMs || 5000);
    };

    const events = [{ id: "start", timeMs: 0, label: "战斗开始", layer: "全场" }];
    for (const row of bubbles) {
      events.push({ id: `bubble:${row.index}`, timeMs: row.startTimeMs, label: "诱人水泡", layer: "转场", spellID: 1284015 });
      if (row.popTimeMs != null) events.push({ id: `pop:${row.index}`, timeMs: row.popTimeMs, label: "嘭！", layer: "转场", spellID: 1258150 });
    }
    for (const row of surges) {
      events.push({ id: `surge:${row.index}`, timeMs: row.castEndTimeMs ?? row.timeMs, label: "激荡漩涡预兆", layer: "激荡漩涡", spellID: 1258673 });
      events.push({ id: `surgeMove:${row.index}`, timeMs: row.foreshadowEndTimeMs ?? ((row.castEndTimeMs ?? row.timeMs) + 5000), label: "漩涡涌入", layer: "激荡漩涡" });
      events.push({ id: `surgeArrive:${row.index}`, timeMs: row.arrivalTimeMs ?? row.castEndTimeMs, label: `抵达中心${row.safeDirection ? `（安全：${row.safeDirection}）` : ""}`, layer: "激荡漩涡", problem: row.problem });
    }
    for (const row of frostRounds) {
      events.push({ id: `frost:${row.index}`, timeMs: row.timeMs, label: "冰霜点名放球", layer: "冰球", spellID: row.spellID || 1257614 });
    }
    for (const row of touches) {
      events.push({ id: `touch:${row.playerID}:${row.timeMs}`, timeMs: row.timeMs, label: row.underAbyssalRain ? "雨中踩球" : "踩球", layer: "冰球踩踏", actor: row.player, problem: Boolean(row.problem) });
    }
    for (const row of bursts) {
      events.push({ id: `burst:${row.index}`, timeMs: row.timeMs, label: row.outcome || (row.timedOut ? "超时自爆" : "踩球触发"), layer: "冰球结算", actor: row.triggerPlayer || "场地球", problem: Boolean(row.problem) });
    }
    for (const row of waterJets) {
      events.push({ id: `jet:${row.index}`, timeMs: row.startTimeMs, label: `水流喷射 → ${row.target || "坦克"}`, layer: "水流喷射", spellID: 1281951 });
    }
    for (const row of mechanics.rainOrbTouches?.players || []) {
      events.push({ id: `raintouch:${row.playerID}:${row.timeMs}`, timeMs: row.timeMs, label: "雨中踩球", layer: "深渊之雨踩球", actor: row.player, problem: true });
    }

    const bigMurlocs = (replay.units || []).filter(u => u.gameID === 257892);

    const wb = api.mount(host, {
      key: "nymrissa-replay",
      title: "尼姆瑞莎场地推演",
      combatReplay: replay,
      durationMs: durationMs || replay.durationMs,
      arenaImage: field.arenaImage || "/assets/raids/tidebound_grotto/01-nymrissa.jpg",
      events,
      note: field.note || "",
      projection: "relative",
    }, {
      video: true,
      handlesPlayers: true,
      project: point => {
        const q = project(point, box);
        return q && { x: q.x / WIDTH * 100, y: q.y / HEIGHT * 100 };
      },
      bossPosition: (b, t) => {
        const unit = (replay.units || []).find(u => u.actorID === b.actorID) || boss;
        const pos = unit && api.trackPosition(unit, t, replay.interpolateMaxGapMs);
        const q = project(pos, box);
        return q && { x: q.x / WIDTH * 100, y: q.y / HEIGHT * 100 };
      },
      renderMap(_selected, _filtered, cursor) {
        const players = (replay.units || []).filter(u => u.kind === "player");
        const hitIDs = new Set(
          surges.flatMap(row => (row.players || []).filter(p => Math.abs((p.firstTimeMs ?? row.arrivalTimeMs) - cursor) < 900).map(p => p.playerID))
        );
        const touchHit = new Set(touches.filter(row => cursor >= row.timeMs && cursor - row.timeMs < 1200).map(row => row.playerID));

        const bubble = bubbles.find(row => cursor >= row.startTimeMs && cursor < (row.endTimeMs ?? row.popTimeMs ?? Infinity));
        let bubbleSvg = "";
        if (bubble) {
          const r = yardToPx(bubble.radiusYards || 10, box);
          const popping = bubble.popTimeMs != null && cursor >= bubble.popTimeMs - 400;
          bubbleSvg = `<g data-key="alluring-bubble"><circle cx="${midQ.x}" cy="${midQ.y}" r="${r}" fill="#67e8f9" fill-opacity="${popping ? 0.3 : 0.14}" stroke="#a5f3fc" stroke-width="3"/><title>诱人水泡（场地正中央，约 ${bubble.radiusYards || 10} 码）</title></g>`;
        }

        const surge = surges.find(row => cursor >= (row.castEndTimeMs ?? row.timeMs) && cursor < (row.popTimeMs ?? row.endTimeMs ?? Infinity));
        let surgeSvg = "";
        if (surge) {
          const castEnd = surge.castEndTimeMs ?? surge.timeMs;
          const foreshadowEnd = surge.foreshadowEndTimeMs ?? castEnd + 5000;
          const arrival = surge.arrivalTimeMs ?? foreshadowEnd + 3500;
          const foreshadow = cursor < foreshadowEnd;
          const rushing = cursor >= foreshadowEnd && cursor < arrival;
          const progress = foreshadow ? 0 : rushing ? Math.min(1, (cursor - foreshadowEnd) / Math.max(1, arrival - foreshadowEnd)) : 1;
          const outer = Math.min(WIDTH, HEIGHT) * 0.48;
          const safe = surge.safeDirectionIndex;
          for (let i = 0; i < 8; i++) {
            if (i === safe) continue;
            const lead = outer * (1 - progress * 0.92);
            const opacity = foreshadow ? 0.12 : rushing ? 0.2 : 0.14;
            surgeSvg += `<path data-key="surge:${i}" d="${wedgePath(midQ.x, midQ.y, outer, i)}" fill="#38bdf8" fill-opacity="${opacity}" stroke="#7dd3fc" stroke-width="1"/>`;
            // Rim foreshadow markers, then inward fronts while traveling.
            const a = -Math.PI / 2 + i * (Math.PI / 4);
            surgeSvg += `<circle data-key="surge-front:${i}" cx="${midQ.x + Math.cos(a) * lead}" cy="${midQ.y + Math.sin(a) * lead}" r="${foreshadow ? 12 : 10}" fill="#e0f2fe" fill-opacity="${foreshadow ? 0.85 : 0.7}" stroke="#38bdf8" stroke-width="1.5"/>`;
          }
          if (safe != null && cursor >= foreshadowEnd - 200) {
            surgeSvg += `<path data-key="surge-safe" d="${wedgePath(midQ.x, midQ.y, outer, safe)}" fill="#34d399" fill-opacity=".2" stroke="#6ee7b7" stroke-width="2"><title>安全：${api.escape(DIRS[safe] || surge.safeDirection || "")}（按抵达时站位）</title></path>`;
          }
        }

        const puddleR = yardToPx(field.puddleRadiusYards || 5, box);
        const puddleSvg = puddles.filter(row => cursor >= row.startTimeMs && cursor < row.endTimeMs).map(row => {
          const q = project(row, box);
          if (!q) return "";
          return `<g data-key="${row.key}"><circle cx="${q.x}" cy="${q.y}" r="${puddleR}" fill="#0ea5e9" fill-opacity=".22" stroke="#38bdf8" stroke-width="1.5" stroke-dasharray="4 3"/><title>残留水面（约 5 码），${api.escape(row.source || "")}</title></g>`;
        }).join("");

        const orbSvg = groundOrbs.filter(orb => cursor >= orb.startTimeMs && cursor < orb.endTimeMs).map(orb => {
          const q = project(orb, box);
          if (!q) return "";
          const age = cursor - orb.startTimeMs;
          const pulse = 1 + 0.08 * Math.sin(age / 180);
          return `<g data-key="${orb.key}"><circle cx="${q.x}" cy="${q.y}" r="${11 * pulse}" fill="#bae6fd" fill-opacity=".65" stroke="#38bdf8" stroke-width="2"/><circle cx="${q.x}" cy="${q.y}" r="4" fill="#f0f9ff"/><title>冰球，${api.escape(orb.dropper || "")}</title></g>`;
        }).join("");

        const touchSvg = touches.filter(row => cursor >= row.timeMs && cursor - row.timeMs < 1400).map(row => {
          const pos = posOf(row.playerID, row.timeMs) || posOf(row.playerID, cursor);
          const q = project(pos, box);
          if (!q) return "";
          const fade = 1 - (cursor - row.timeMs) / 1400;
          const color = row.underAbyssalRain ? "#fb7185" : "#67e8f9";
          return `<g data-key="touch:${row.playerID}:${row.timeMs}" opacity="${fade}"><circle cx="${q.x}" cy="${q.y}" r="${18 + (1 - fade) * 22}" fill="none" stroke="${color}" stroke-width="3"/><text x="${q.x}" y="${q.y - 22}" text-anchor="middle" fill="${color}" font-size="12">${row.underAbyssalRain ? "雨中踩球" : "踩球"}</text></g>`;
        }).join("");

        const burstSvg = bursts.filter(row => cursor >= row.timeMs && cursor - row.timeMs < 1600).map(row => {
          const pos = row.triggerPlayerID
            ? (posOf(row.triggerPlayerID, row.timeMs) || posOf(row.triggerPlayerID, cursor))
            : null;
          const q = project(pos, box) || midQ;
          if (!q) return "";
          const fade = 1 - (cursor - row.timeMs) / 1600;
          const color = row.timedOut ? "#fbbf24" : (row.triggerUnderAbyssalRain ? "#fb7185" : "#7dd3fc");
          return `<g data-key="burst:${row.index}" opacity="${fade}"><circle cx="${q.x}" cy="${q.y}" r="${28 + (1 - fade) * 40}" fill="${color}" fill-opacity=".2" stroke="${color}" stroke-width="3"/><text x="${q.x}" y="${q.y + 4}" text-anchor="middle" fill="#f8fafc" font-size="13">${row.timedOut ? "超时自爆" : "踩球触发"}</text></g>`;
        }).join("");

        const bossPos = boss && api.trackPosition(boss, cursor, replay.interpolateMaxGapMs);
        const bossQ = project(bossPos, box);
        let jetSvg = "";
        for (const jet of waterJets) {
          if (cursor < jet.startTimeMs || cursor >= jet.endTimeMs) continue;
          const tankPos = posOf(jet.targetID, cursor) || posOf(jet.targetID, jet.castEndTimeMs || jet.startTimeMs);
          const tankQ = project(tankPos, box);
          if (!bossQ || !tankQ) continue;
          const fade = cursor < (jet.castEndTimeMs || jet.startTimeMs) ? 0.45 : 0.85;
          jetSvg += `<g data-key="jet:${jet.index}" opacity="${fade}"><line x1="${bossQ.x}" y1="${bossQ.y}" x2="${tankQ.x}" y2="${tankQ.y}" stroke="#67e8f9" stroke-width="6" stroke-linecap="round" stroke-opacity=".55"/><line x1="${bossQ.x}" y1="${bossQ.y}" x2="${tankQ.x}" y2="${tankQ.y}" stroke="#e0f2fe" stroke-width="2.5" stroke-linecap="round"/><circle cx="${tankQ.x}" cy="${tankQ.y}" r="16" fill="none" stroke="#67e8f9" stroke-width="2" stroke-dasharray="4 3"/><title>水流喷射 → ${api.escape(jet.target || "坦克")}</title></g>`;
        }

        const bossLife = boss ? api.lifeState(boss, cursor) : { opacity: 0, dead: true };
        const bossSvg = bossQ && bossLife.opacity && !bossLife.dead
          ? portrait(api.escape(bossPortrait), bossQ.x, bossQ.y, 20, "boss", "尼姆瑞莎")
          : "";

        const addSvg = bigMurlocs.map(unit => {
          const alive = livingAdd(unit, cursor);
          if (!alive) return "";
          const pos = api.trackPosition(unit, alive.positionTime, replay.interpolateMaxGapMs);
          const q = project(pos, box);
          if (!q) return "";
          return portrait(api.escape(bigPortrait), q.x, q.y, 14, `murloc-big:${unit.key}`, "大鱼人 · 泡鳍霜鳞");
        }).join("");

        const avatars = players.map(unit => {
          const life = api.lifeState(unit, cursor);
          const pos = api.trackPosition(unit, life.positionTime, replay.interpolateMaxGapMs);
          const q = project(pos, box);
          if (!q || !life.opacity) return "";
          return `<g data-key="player:${unit.actorID}" opacity="${life.opacity}">${api.avatar(unit, { ...q, stale: pos?.stale }, 12, hitIDs.has(unit.actorID) || touchHit.has(unit.actorID), life.dead, 1)}</g>`;
        }).join("");

        return `<div class="mw-map" data-replay-field style="aspect-ratio:${WIDTH}/${HEIGHT}"><img src="${api.escape(field.arenaImage || "/assets/raids/tidebound_grotto/01-nymrissa.jpg")}" alt="尼姆瑞莎场地" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.5"><svg viewBox="0 0 ${WIDTH} ${HEIGHT}" role="img" aria-label="尼姆瑞莎场地推演" style="position:relative;z-index:1">${bubbleSvg}${surgeSvg}${puddleSvg}${orbSvg}${jetSvg}${touchSvg}${burstSvg}${addSvg}${bossSvg}${avatars}</svg></div>`;
      },
    });

    const jumps = [
      ...bubbles.map(row => ({ timeMs: row.startTimeMs, label: `诱人水泡 #${row.index}` })),
      ...bubbles.filter(row => row.popTimeMs != null).map(row => ({ timeMs: row.popTimeMs, label: `嘭！ #${row.index}` })),
      ...frostRounds.map(row => ({ timeMs: row.timeMs, label: `冰霜放球 #${row.index}` })),
      ...touches.slice(0, 12).map(row => ({ timeMs: row.timeMs, label: `${row.underAbyssalRain ? "雨中踩球" : "踩球"} · ${row.player}` })),
      ...bursts.slice(0, 12).map(row => ({ timeMs: row.timeMs, label: row.outcome || "冰球结算" })),
      ...surges.map(row => ({ timeMs: row.castEndTimeMs ?? row.timeMs, label: `激荡漩涡 #${row.index}` })),
      ...waterJets.map(row => ({ timeMs: row.startTimeMs, label: `水流喷射 #${row.index}` })),
    ].filter(row => row.timeMs != null).sort((a, b) => a.timeMs - b.timeMs);
    if (jumps.length) {
      const clock = ms => `${Math.floor(ms / 60000)}:${(ms / 1000 % 60).toFixed(1).padStart(4, "0")}`;
      host.insertAdjacentHTML("afterbegin", `<label class="hint">回放片段 <select aria-label="尼姆瑞莎回放片段">${jumps.map(row => `<option value="${row.timeMs}">${api.escape(row.label)}，${clock(row.timeMs)}</option>`).join("")}</select></label>`);
      host.querySelector('select[aria-label="尼姆瑞莎回放片段"]').onchange = event => wb.seek(Number(event.target.value));
    }
    wb.refreshMap?.();
    return wb;
  }

  root.NymrissaReplay = { mount, project, boundsOf };
})(typeof window === "undefined" ? globalThis : window);
