/* Kith'ix owns add lifetimes and the P1/P2 overlays drawn on the shared tracks. */
(function (root) {
  "use strict";
  const WIDTH = 1093, HEIGHT = 614;
  function lastSample(rows, t) {
    let lo = 0, hi = rows.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (rows[mid][0] <= t) lo = mid + 1; else hi = mid; }
    return lo - 1;
  }
  function facingAt(unit, t) {
    const rows = unit?.facingSamples || [], index = lastSample(rows, t);
    if (index < 0) return null;
    return { angle: rows[index][1] / 100, stale: t - rows[index][0] > 1000 };
  }
  function projectPoint(point, arena) {
    if (!point || !arena || arena.centerX == null) return null;
    const radius = Number(arena.radius || 1);
    const dx = Number(point.x) - Number(arena.centerX);
    const dy = Number(point.y) - Number(arena.centerY);
    return {
      x: (50 + dx / radius * Number(arena.plotScaleX || 22.69)) / 100 * WIDTH,
      y: (50 - dy / radius * Number(arena.plotScaleY || 40.39)) / 100 * HEIGHT,
    };
  }
  function yardScale(arena) {
    return Number(arena.unitsPerYard || 100) / Number(arena.radius || 1) * Number(arena.plotScaleX || 22.69) / 100 * WIDTH;
  }
  function active(row, cursor, startKey, endKey) {
    const start = row[startKey], end = row[endKey];
    return start != null && cursor >= start && (end == null || cursor < end);
  }
  function addState(add, unit, cursor) {
    if (unit == null && typeof cursor !== "number") { cursor = unit; unit = null; }
    const samples = unit?.samples || [];
    const first = samples.length ? samples[0][0] : null;
    const last = samples.length ? samples[samples.length - 1][0] : null;
    const marked = [];
    if (add?.explodeTimeMs != null) marked.push(add.explodeTimeMs);
    if (add?.deathTimeMs != null) marked.push(add.deathTimeMs);
    for (const row of unit?.states || []) if (row[1] === "dead") marked.push(row[0]);
    marked.sort((a, b) => a - b);
    const start = add?.spawnTimeMs != null ? add.spawnTimeMs : first;
    if (start != null && cursor < start) return null;
    const deaths = marked.filter(time => time >= (start || 0) - 300).sort((a, b) => a - b);
    const death = deaths.length ? deaths[0] : null;
    const end = death != null ? death : last;
    const explodeGone = add?.kind === "bomber" && add?.explodeTimeMs != null && cursor >= add.explodeTimeMs;
    if (explodeGone) return null;
    if (end != null && cursor >= end + 900) return null;
    const fading = end != null && cursor >= end;
    return { dead: fading, opacity: fading ? Math.max(0, 1 - (cursor - end) / 900) : 1, positionTime: fading ? end : cursor };
  }
  function conePath(origin, facing, radiusPx, halfAngle) {
    const points = [origin];
    for (let i = 0; i <= 24; i++) {
      const angle = facing - halfAngle + 2 * halfAngle * i / 24;
      points.push({ x: origin.x + Math.cos(angle) * radiusPx, y: origin.y - Math.sin(angle) * radiusPx });
    }
    return `M ${points.map(point => `${point.x} ${point.y}`).join(" L ")} Z`;
  }
  function mount(host, mechanics, durationMs) {
    const api = root.MechanicWorkbench;
    const replay = mechanics.combatReplay || {};
    const arena = mechanics.arena || {};
    const units = replay.units || [];
    const unitOf = (id, instance) => units.find(unit => unit.actorID === id && (instance == null || unit.instance === instance)) || units.find(unit => unit.actorID === id);
    const position = (id, t, instance) => { const unit = unitOf(id, instance); return unit && api.trackPosition(unit, t, replay.interpolateMaxGapMs || 5000); };
    const trackPoint = (id, time) => { const point = position(id, time); return point && { x: point.x, y: point.y }; };
    const waveEnd = row => {
      if (row.endTimeMs != null) return row.endTimeMs;
      const start = row.startTimeMs ?? row.timeMs ?? 0;
      const radiance = (mechanics.radiances || []).find(cast => (cast.timeMs ?? 0) >= start);
      return radiance ? radiance.timeMs : durationMs;
    };
    const savedScars = (mechanics.voidscars || []).filter(row => row.x != null && row.y != null);
    const fromTanks = (mechanics.devastations || []).map((row, index) => {
      const landed = row.timeMs ?? row.startTimeMs ?? 0;
      const point = trackPoint(row.tankID, landed) || row.targetPosition;
      if (!point) return null;
      return { ...point, key: `dev:${index}:${landed}`, startTimeMs: landed, tank: row.tank, tankID: row.tankID };
    }).filter(Boolean);
    const scarSource = fromTanks.length ? fromTanks : savedScars;
    const scarRows = scarSource.map(row => ({ ...row, endTimeMs: durationMs, volleyTimesMs: row.volleyTimesMs || (mechanics.darkness || []).filter(wave => row.startTimeMs < (wave.startTimeMs ?? wave.timeMs ?? 0)).map(wave => wave.startTimeMs ?? wave.timeMs) }));
    const liadrinPoint = arena.centerX == null ? null : { x: arena.centerX, y: arena.centerY };
    const alongLine = (scar, player) => {
      if (!liadrinPoint) return null;
      const dx = liadrinPoint.x - scar.x, dy = liadrinPoint.y - scar.y, length2 = dx * dx + dy * dy;
      if (length2 < 1) return null;
      const px = player.x - scar.x, py = player.y - scar.y, progress = (px * dx + py * dy) / length2;
      if (progress < -0.05 || progress > 1.15) return null;
      const clamped = Math.min(1, Math.max(0, progress));
      return { progress, offset: Math.hypot(px - dx * clamped, py - dy * clamped) / Number(arena.unitsPerYard || 100) };
    };
    const fittedPaths = (() => {
      if (!liadrinPoint) return [];
      const windows = (mechanics.darkness || []).map(row => ({ ...row, startTimeMs: row.startTimeMs ?? row.timeMs ?? 0, endTimeMs: waveEnd(row) }));
      const hits = [];
      for (const row of mechanics.fragments || []) {
        const point = row.position || trackPoint(row.playerID, row.applyTimeMs);
        if (point) hits.push({ playerID: row.playerID, player: row.player, timeMs: row.applyTimeMs, ...point });
      }
      const paths = [];
      windows.forEach(window => {
        const pool = new Map();
        hits.filter(hit => window.startTimeMs <= hit.timeMs && hit.timeMs <= window.endTimeMs + 500).forEach(hit => { if (!pool.has(hit.playerID) || hit.timeMs < pool.get(hit.playerID).timeMs) pool.set(hit.playerID, hit); });
        const firing = scarRows.filter(scar => (scar.volleyTimesMs || []).includes(window.startTimeMs));
        const candidates = [];
        pool.forEach(hit => firing.forEach(scar => { const scored = alongLine(scar, hit); if (scored && scored.offset <= 8) candidates.push({ ...scored, hit, scar }); }));
        candidates.sort((a, b) => a.offset - b.offset || a.hit.timeMs - b.hit.timeMs);
        const usedScars = new Set(), usedPlayers = new Set();
        candidates.forEach(row => {
          if (usedScars.has(row.scar.key) || usedPlayers.has(row.hit.playerID)) return;
          usedScars.add(row.scar.key); usedPlayers.add(row.hit.playerID);
          paths.push({ key: `${row.scar.key}:${row.hit.playerID}:${row.hit.timeMs}`, playerID: row.hit.playerID, player: row.hit.player, timeMs: row.hit.timeMs, launchTimeMs: window.timeMs ?? window.startTimeMs, darknessTimeMs: window.startTimeMs, scarKey: row.scar.key, scar: { x: row.scar.x, y: row.scar.y }, soak: { x: row.hit.x, y: row.hit.y }, liadrin: liadrinPoint, offsetYards: Math.round(row.offset * 100) / 100 });
        });
      });
      return paths;
    })();
    const events = [{ id: "start", timeMs: 0, label: "战斗开始", layer: "全场" }];
    for (const row of mechanics.phaseTimeline || []) if (row.timeMs) events.push({ id: `phase:${row.key}:${row.timeMs}`, timeMs: row.timeMs, label: row.key === "p2" ? "第二阶段" : "第一阶段", layer: "阶段" });
    for (const row of mechanics.devastations || []) events.push({ id: `dev:${row.timeMs}`, timeMs: row.startTimeMs, label: "黑暗毁灭", layer: "坦克", problem: false });
    for (const row of mechanics.eggs || []) events.push({ id: `egg:${row.key}`, timeMs: row.spawnTimeMs, label: "缚脑者之卵", layer: "虫群", actor: row.name, problem: row.missed });
    for (const row of mechanics.grasps || []) events.push({ id: `grasp:${row.playerID}:${row.applyTimeMs}`, timeMs: row.applyTimeMs, label: "深渊攫取", layer: "窒息黑暗", actor: row.player, problem: row.missed });
    for (const row of mechanics.darkness || []) if (row.leaked) for (const timeMs of row.fadeTimesMs || [row.startTimeMs]) events.push({ id: `fade:${timeMs}`, timeMs, label: "辉光消逝", layer: "窒息黑暗", problem: true });
    for (const row of mechanics.gates || []) events.push({ id: `gate:${row.playerID}:${row.applyTimeMs}`, timeMs: row.applyTimeMs, label: "虚无之门", layer: "第二阶段", actor: row.player });
    for (const row of mechanics.finalLights || []) if (!row.radiantGrace) events.push({ id: `light:${row.playerID}`, timeMs: (mechanics.phaseTimeline || []).find(phase => phase.key === "p2")?.timeMs || 0, label: "缺少光耀恩典", layer: "第二阶段", actor: row.player, problem: true });
    const workbench = api.mount(host, {
      key: "kithix-replay",
      title: "基希克斯战斗回放",
      combatReplay: replay,
      durationMs,
      events,
      note: mechanics.evidenceNote || "",
    }, {
      video: true,
      handlesPlayers: true,
      project: point => { const drawn = projectPoint(point, arena); return drawn && { x: drawn.x / WIDTH * 100, y: drawn.y / HEIGHT * 100 }; },
      renderMap(_selected, _filtered, cursor) {
        const scale = yardScale(arena);
        const phase = [...(mechanics.phaseTimeline || [])].reverse().find(row => row.timeMs <= cursor);
        const scars = scarRows.filter(row => cursor >= row.startTimeMs && cursor <= (row.endTimeMs ?? durationMs)).map(row => {
          const point = projectPoint(row, arena);
          return point ? `<g data-key="scar:${row.key || row.startTimeMs}"><circle cx="${point.x}" cy="${point.y}" r="22" fill="#4c1d95" fill-opacity=".82" stroke="#c4b5fd" stroke-width="2"/><title>虚空之痕${row.tank ? `，${api.escape(row.tank)}` : ""}</title></g>` : "";
        }).join("");
        const waves = (mechanics.darkness || []).map(row => ({ ...row, startTimeMs: row.startTimeMs ?? row.timeMs ?? 0, launchTimeMs: row.timeMs ?? row.startTimeMs ?? 0, endTimeMs: waveEnd(row) }));
        const wave = waves.find(row => cursor >= row.launchTimeMs && cursor <= row.endTimeMs);
        const sameWave = (row, current) => current && (row.darknessTimeMs === current.startTimeMs || row.darknessTimeMs === current.launchTimeMs);
        const launchOf = path => waves.find(row => row.startTimeMs === path.darknessTimeMs || row.launchTimeMs === path.darknessTimeMs)?.launchTimeMs ?? path.launchTimeMs;
        const flown = new Set(fittedPaths.filter(row => sameWave(row, wave)).map(row => row.scarKey));
        const medianSpeed = (() => {
          const speeds = fittedPaths.filter(row => sameWave(row, wave)).map(row => {
            const launch = launchOf(row);
            const dist = Math.hypot(row.soak.x - row.scar.x, row.soak.y - row.scar.y);
            return row.timeMs > launch ? dist / (row.timeMs - launch) : 0;
          }).filter(value => value > 0).sort((a, b) => a - b);
          return speeds.length ? speeds[Math.floor((speeds.length - 1) / 2)] : 2;
        })();
        const beams = wave && liadrinPoint ? scarRows.filter(row => (row.volleyTimesMs || []).includes(wave.startTimeMs) && !flown.has(row.key)).map(row => {
          const from = projectPoint(row, arena);
          const dist = Math.hypot(liadrinPoint.x - row.x, liadrinPoint.y - row.y);
          const launch = wave.launchTimeMs;
          const fade = (wave.fadeTimesMs || []).find(time => time >= launch);
          const arrival = fade || launch + dist / medianSpeed;
          if (!from || cursor >= arrival) return "";
          const progress = Math.min(1, Math.max(0, (cursor - launch) / Math.max(400, arrival - launch)));
          const dot = projectPoint({ x: row.x + (liadrinPoint.x - row.x) * progress, y: row.y + (liadrinPoint.y - row.y) * progress }, arena);
          if (!dot) return "";
          return `<g data-key="fragment:${row.key || row.startTimeMs}"><line x1="${from.x}" y1="${from.y}" x2="${dot.x}" y2="${dot.y}" stroke="#ddd6fe" stroke-width="3"/><circle cx="${dot.x}" cy="${dot.y}" r="7" fill="#c4b5fd" stroke="#f5f3ff"/></g>`;
        }).join("") : "";
        const flights = fittedPaths.filter(row => { const launch = launchOf(row); return cursor >= launch && cursor < row.timeMs + 700; }).map(row => {
          const launch = launchOf(row);
          const soaked = cursor >= row.timeMs;
          const from = projectPoint(row.scar, arena);
          const soak = projectPoint(row.soak, arena);
          if (!from || !soak) return "";
          if (soaked) {
            const burst = 1 - (cursor - row.timeMs) / 700;
            return `<g data-key="flight:${row.key}"><circle cx="${soak.x}" cy="${soak.y}" r="${14 + burst * 20}" fill="#7c3aed" fill-opacity="${.45 * burst}" stroke="#ddd6fe" stroke-opacity="${burst}"/></g>`;
          }
          const progress = Math.min(1, Math.max(0, (cursor - launch) / Math.max(400, row.timeMs - launch)));
          const dot = projectPoint({ x: row.scar.x + (row.soak.x - row.scar.x) * progress, y: row.scar.y + (row.soak.y - row.scar.y) * progress }, arena);
          if (!dot) return "";
          return `<g data-key="flight:${row.key}"><line x1="${from.x}" y1="${from.y}" x2="${dot.x}" y2="${dot.y}" stroke="#ddd6fe" stroke-width="3"/><circle cx="${dot.x}" cy="${dot.y}" r="7" fill="#c4b5fd" stroke="#f5f3ff"/></g>`;
        }).join("");
        const devs = (mechanics.devastations || []).filter(row => cursor >= row.startTimeMs && cursor < row.timeMs + 1200).map(row => {
          const point = projectPoint(position(row.tankID, Math.min(cursor, row.timeMs)) || row.targetPosition || row.position, arena);
          return point ? `<circle data-key="dev:${row.timeMs}" cx="${point.x}" cy="${point.y}" r="${15 * scale}" fill="#6d28d9" fill-opacity=".16" stroke="#c4b5fd" stroke-width="3"/>` : "";
        }).join("");
        const roars = (mechanics.roars || []).filter(row => cursor >= row.startTimeMs && cursor < row.timeMs + 600).map(row => {
          const unit = unitOf(row.sourceID, row.sourceInstance);
          const life = unit && api.lifeState(unit, Math.min(cursor, row.timeMs));
          const origin = projectPoint(unit && api.trackPosition(unit, life.positionTime, 5000), arena);
          const facing = unit && facingAt(unit, Math.min(cursor, row.timeMs));
          if (!origin || !facing) return "";
          return `<path data-key="roar:${row.timeMs}" d="${conePath(origin, facing.angle, 60 * scale, 30 * Math.PI / 180)}" fill="#86efac" fill-opacity="${cursor < row.timeMs ? .16 : .28}" stroke="#bbf7d0" stroke-width="2"/>`;
        }).join("");
        const gates = (mechanics.gates || []).filter(row => {
          const place = row.placeTimeMs ?? row.dropTimeMs;
          return place != null && cursor >= place && (row.clearedTimeMs == null || cursor < row.clearedTimeMs + 700);
        }).map(row => {
          const place = row.placeTimeMs ?? row.dropTimeMs;
          const point = projectPoint(row.position || position(row.playerID, place), arena);
          if (!point) return "";
          const fading = row.clearedTimeMs != null && cursor >= row.clearedTimeMs;
          const icon = arena.nullGateIcon || "/assets/raids/unbinding_of_kithix/null-gate.png";
          const size = 8;
          return `<g data-key="gate:${row.key || `${row.playerID}:${place}`}" opacity="${fading ? 1 - (cursor - row.clearedTimeMs) / 700 : 1}"><image href="${icon}" x="${point.x - size / 2}" y="${point.y - size / 2}" width="${size}" height="${size}"/><title>虚无之门，${api.escape(row.player || "")}</title></g>`;
        }).join("");
        const nullOrbs = (mechanics.nullVolleys || []).flatMap(volley => {
          const end = volley.clearedTimeMs != null ? Math.min(volley.clearedTimeMs, volley.expireTimeMs) : volley.expireTimeMs;
          if (cursor < volley.launchTimeMs || cursor > end + 200) return [];
          const elapsed = Math.max(0, Math.min(cursor, end) - volley.launchTimeMs) / 1000;
          const fading = volley.clearedTimeMs != null && cursor >= volley.clearedTimeMs;
          return (volley.angles || []).map((angle, index) => {
            const world = {
              x: volley.origin.x + Math.cos(angle) * elapsed * (volley.speedYards || 20) * (arena.unitsPerYard || 100),
              y: volley.origin.y - Math.sin(angle) * elapsed * (volley.speedYards || 20) * (arena.unitsPerYard || 100),
            };
            const point = projectPoint(world, arena);
            if (!point) return "";
            return `<circle data-key="null-orb:${volley.key}:${index}" cx="${point.x}" cy="${point.y}" r="5" fill="#c4b5fd" fill-opacity="${fading ? .2 : .9}" stroke="#f5f3ff" stroke-width="1.5"/>`;
          });
        }).join("");
        const axis = mechanics.nullAxis || {};
        const axisLine = (() => {
          if (!axis.liadrin || !axis.bossInitial || (mechanics.phaseTimeline || []).every(row => row.key !== "p2" || cursor < row.timeMs)) return "";
          const from = projectPoint(axis.liadrin, arena), to = projectPoint(axis.bossInitial, arena);
          if (!from || !to) return "";
          return `<g data-key="null-axis" opacity=".35"><line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke="#fde68a" stroke-width="2" stroke-dasharray="10 8"/><title>0°/180° 基准：莉亚德琳 → Boss 开场</title></g>`;
        })();
        const blasts = (mechanics.restabilizations || []).filter(row => cursor >= row.timeMs && cursor < row.timeMs + 800).map(row => {
          const point = projectPoint(row.position || position(row.sourceID, row.timeMs), arena);
          if (!point) return "";
          const progress = (cursor - row.timeMs) / 800;
          return `<circle data-key="blast:${row.timeMs}" cx="${point.x}" cy="${point.y}" r="${10 * scale * progress}" fill="#fde68a" fill-opacity="${.35 * (1 - progress)}" stroke="#fbbf24" stroke-width="3"/>`;
        }).join("");
        const beetleByKey = Object.fromEntries((mechanics.beetles || []).map(row => [row.key, row]));
        const beetleBlasts = (mechanics.beetles || []).map(beetle => {
          if (beetle.explodeTimeMs == null || cursor < beetle.explodeTimeMs || cursor >= beetle.explodeTimeMs + 700) return "";
          const unit = units.find(row => row.actorID === beetle.actorID && row.instance === beetle.instance) || unitOf(beetle.actorID);
          if (!unit) return "";
          const origin = projectPoint(api.trackPosition(unit, beetle.explodeTimeMs, 5000), arena);
          if (!origin) return "";
          const progress = (cursor - beetle.explodeTimeMs) / 700;
          const radius = (beetle.contactRadiusYards || 4) * scale * (0.6 + progress);
          return `<g data-key="beetle-blast:${beetle.key}"><circle cx="${origin.x}" cy="${origin.y}" r="${radius}" fill="#fb7185" fill-opacity="${.45 * (1 - progress)}" stroke="#fecaca" stroke-width="2"/></g>`;
        }).join("");
        const adds = (mechanics.adds || []).filter(add => add.kind !== "liadrin" && add.kind !== "kithix").map(add => {
          const unit = units.find(row => row.actorID === add.actorID && row.instance === add.instance) || (units.filter(row => row.actorID === add.actorID).length === 1 ? unitOf(add.actorID) : null);
          if (!unit) return "";
          const beetle = add.kind === "bomber" ? (beetleByKey[add.key] || add) : add;
          const state = addState(beetle, unit, cursor);
          if (!state) return "";
          const point = projectPoint(api.trackPosition(unit, state.positionTime, 5000), arena);
          if (!point) return "";
          const frenzy = (mechanics.frenzies || []).some(row => row.playerID === add.actorID && active(row, cursor, "applyTimeMs", "removeTimeMs"));
          const egg = add.kind === "egg" ? (mechanics.eggs || []).find(row => row.key === add.key) : null;
          const remain = egg ? Math.max(0, egg.deadlineMs - cursor) : null;
          const late = egg && cursor > egg.deadlineMs && !state.dead;
          const timer = egg && !state.dead ? `<text x="${point.x}" y="${point.y - 28}" text-anchor="middle" fill="${late ? "#fda4af" : "#fde68a"}" font-size="14">${(remain / 1000).toFixed(1)}s</text>` : "";
          const contactYards = beetle.contactRadiusYards || 4;
          const contact = add.kind === "bomber" && !state.dead
            ? `<circle cx="${point.x}" cy="${point.y}" r="${contactYards * scale}" fill="#fb7185" fill-opacity=".12" stroke="#fda4af" stroke-width="2" stroke-dasharray="6 4"/>`
            : "";
          const chaseId = beetle.chaseTargetID || beetle.triggerPlayerID;
          const chasePoint = chaseId != null && !state.dead ? projectPoint(position(chaseId, cursor), arena) : null;
          const tether = chasePoint
            ? `<path d="M ${point.x} ${point.y} L ${chasePoint.x} ${chasePoint.y}" fill="none" stroke="#fb7185" stroke-width="2" opacity=".75" stroke-dasharray="8 8" stroke-dashoffset="${-(cursor * .025) % 16}"/><title>甲虫追逐 ${api.escape(beetle.triggerPlayer || "")}</title>`
            : "";
          const castSource = { ...(unit || {}), casts: beetle.casts || add.casts || unit?.casts || [], actorID: add.actorID };
          const cast = !state.dead ? api.castBar(castSource, cursor, point, add.kind === "hulk" ? 160 : 132) : "";
          return `<g data-key="add:${add.key}" opacity="${state.opacity}">${tether}${contact}${frenzy ? `<circle cx="${point.x}" cy="${point.y}" r="26" fill="#ef4444" fill-opacity=".25" stroke="#fecaca"/>` : ""}${api.avatar({ ...unit, key: add.key, name: add.name, icon: add.icon, color: frenzy ? "#f87171" : "#ddd6fe" }, point, add.kind === "hulk" ? 22 : 16, false, state.dead, state.opacity)}${timer}${cast}</g>`;
        }).join("");
        const bosses = (replay.bosses || []).map(boss => {
          const unit = unitOf(boss.actorID);
          const life = api.lifeState(boss, cursor);
          const point = projectPoint(unit && api.trackPosition(unit, life.positionTime, 5000), arena);
          if (!point || !life.opacity) return "";
          const portrait = boss.gameID === 267861 || /kith/i.test(boss.name || "") ? arena.bossPortrait : null;
          return portrait ? `<g data-key="boss:${boss.actorID}" opacity="${life.opacity}"><circle cx="${point.x}" cy="${point.y}" r="28" fill="#1e1030" stroke="#e9d5ff"/><image href="${portrait}" x="${point.x - 26}" y="${point.y - 26}" width="52" height="52" style="clip-path:circle(50%)"/></g>` : api.avatar({ ...boss, key: `boss:${boss.actorID}`, icon: null, color: "#e9d5ff" }, point, 24, false, life.dead, life.opacity);
        }).join("");
        const players = units.filter(unit => unit.kind === "player").map(unit => {
          const life = api.lifeState(unit, cursor);
          const point = projectPoint(api.trackPosition(unit, life.positionTime, replay.interpolateMaxGapMs || 5000), arena);
          if (!point || !life.opacity) return "";
          const fragmentAuras = (mechanics.fragments || []).filter(row => row.playerID === unit.actorID && active(row, cursor, "applyTimeMs", "removeTimeMs"));
          const stacks = fragmentAuras.reduce((max, row) => Math.max(max, Number(row.stacks) || 1), 0);
          const grasp = (mechanics.grasps || []).find(row => row.playerID === unit.actorID && active(row, cursor, "applyTimeMs", "removeTimeMs"));
          const embrace = (mechanics.embraces || []).some(row => row.playerID === unit.actorID && active(row, cursor, "applyTimeMs", "removeTimeMs"));
          const horror = (mechanics.horrors || []).some(row => row.playerID === unit.actorID && row.spellID === 1304045 && active(row, cursor, "applyTimeMs", "removeTimeMs"));
          const stunned = (mechanics.stuns || []).some(row => row.playerID === unit.actorID && active(row, cursor, "applyTimeMs", "removeTimeMs"));
          const grace = (mechanics.finalLights || []).find(row => row.playerID === unit.actorID);
          const lightOn = grace && (mechanics.phaseTimeline || []).some(phase => phase.key === "p2" && cursor >= phase.timeMs);
          const graspArc = grasp ? `<circle cx="${point.x}" cy="${point.y}" r="24" fill="none" stroke="${grasp.missed ? "#fb7185" : "#67e8f9"}" stroke-width="3" stroke-dasharray="${2 * Math.PI * 24 * Math.min(1, (cursor - grasp.applyTimeMs) / 8000)} ${2 * Math.PI * 24}" transform="rotate(-90 ${point.x} ${point.y})"/>` : "";
          const fragmentBadge = stacks ? `<g><circle cx="${point.x + 16}" cy="${point.y - 16}" r="10" fill="#5b21b6" stroke="#ddd6fe"/><text x="${point.x + 16}" y="${point.y - 12}" text-anchor="middle" fill="#f5f3ff" font-size="12">${stacks}</text></g>` : "";
          return `<g data-key="player:${unit.actorID}">${embrace ? `<circle cx="${point.x}" cy="${point.y}" r="22" fill="#fde68a" fill-opacity=".2" stroke="#facc15"/>` : ""}${horror ? `<circle cx="${point.x}" cy="${point.y}" r="30" fill="none" stroke="#c084fc" stroke-dasharray="4 4"/>` : ""}${lightOn ? `<circle cx="${point.x}" cy="${point.y}" r="20" fill="none" stroke="${grace.radiantGrace ? "#fef3c7" : "#fb7185"}"/>` : ""}${stunned ? `<circle cx="${point.x}" cy="${point.y}" r="16" fill="#94a3b8" fill-opacity=".24" stroke="#cbd5e1" stroke-width="2"><title>冥河嚎叫：昏迷</title></circle>` : ""}${graspArc}${api.avatar(unit, point, 10, !!grasp?.missed, life.dead, life.opacity)}${fragmentBadge}</g>`;
        }).join("");
        const barrierNow = (mechanics.barriers || []).find(row => cursor >= row.startTimeMs && cursor < row.endTimeMs);
        const barrierRadius = barrierNow ? (() => {
          const elapsed = Math.max(0, cursor - (barrierNow.shrinkStartTimeMs ?? barrierNow.startTimeMs)) / 1000;
          const start = Number(barrierNow.startRadiusYards);
          const end = Number(barrierNow.endRadiusYards);
          const shrink = Number(barrierNow.shrinkYardsPerSec || 1);
          if (start >= end) return Math.max(end, start - elapsed * shrink);
          return Math.min(end, start + elapsed * shrink);
        })() : null;
        const liadrinPortrait = arena.liadrinPortrait || "/assets/raids/unbinding_of_kithix/liadrin.png";
        const liadrinAdds = (mechanics.adds || []).filter(add => add.kind === "liadrin");
        const liadrinFallbackPoint = barrierNow?.position || mechanics.nullAxis?.liadrin || (arena.centerX == null ? null : { x: arena.centerX, y: arena.centerY });
        const liadrin = (liadrinAdds.length ? liadrinAdds : [{ key: "liadrin-fallback" }]).map(add => {
          const unit = add.actorID != null ? unitOf(add.actorID, add.instance) : null;
          const state = unit ? addState(add, unit, cursor) : { opacity: 1 };
          const tracked = state && unit && projectPoint(api.trackPosition(unit, state.positionTime, 5000), arena);
          const point = tracked || projectPoint(liadrinFallbackPoint, arena);
          if (!point) return "";
          const faded = (mechanics.darkness || []).some(row => (row.fadeTimesMs || []).some(time => cursor >= time && cursor < time + 2000));
          const shield = barrierRadius != null
            ? `<circle cx="${point.x}" cy="${point.y}" r="${barrierRadius * scale * 2}" fill="#fde68a" fill-opacity=".10" stroke="#fbbf24" stroke-width="3"/><title>神圣光辉屏障，第 ${barrierNow.index} 次，当前半径约 ${barrierRadius.toFixed(1)} 码</title>`
            : "";
          return `<g data-key="liadrin" opacity="${state?.opacity ?? 1}">${shield}<circle cx="${point.x}" cy="${point.y}" r="22" fill="#1e1030" stroke="${faded ? "#fecdd3" : "#fbbf24"}" stroke-width="2"/><image href="${liadrinPortrait}" x="${point.x - 20}" y="${point.y - 20}" width="40" height="40" style="clip-path:circle(50%)"/><title>莉亚德琳</title></g>`;
        }).join("");
        return `<div class="kithix-map" data-replay-field><svg viewBox="0 0 ${WIDTH} ${HEIGHT}" role="img" aria-label="基希克斯战斗回放"><image href="${arena.image || "/assets/raids/venomous_abyss/the-unbinding-of-kith-ix.png"}" width="${WIDTH}" height="${HEIGHT}"/>${devs}${roars}${scars}${beams}${flights}${axisLine}${gates}${nullOrbs}${blasts}${liadrin}<g data-key="adds">${adds}</g>${beetleBlasts}<g data-key="bosses">${bosses}</g><g data-key="players">${players}</g><text x="24" y="36" fill="#f8fafc" font-size="22">${api.escape(phase?.key === "p2" ? "第二阶段" : "第一阶段")}</text></svg></div>`;
      },
    });
    return workbench;
  }
  root.KithixReplay = { projectPoint, facingAt, conePath, addState, active, mount };
})(typeof window === "undefined" ? globalThis : window);
