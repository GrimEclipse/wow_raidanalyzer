const $ = selector => document.querySelector(selector);
const ROLE_COLORS = { tank: "#5a91f2", healer: "#48c684", damage: "#e66767" };
const ROLE_SYMBOLS = { tank: "盾", healer: "+", damage: "剑" };
const COMPOSITION_COLORS = { tank: "#5a91f2", melee: "#d9ad58", ranged: "#9b79e6" };
const OFFLINE_KEY = "mythic-analyzer-recruitment-choice-v1";

let state = null;
let backendMode = true;
let listRole = "all";
let pickerRole = "all";
let pickerMode = "primary";
let primarySpecId = null;
let secondarySpecIds = [];

const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const normalized = value => String(value || "").trim().toLocaleLowerCase("zh-CN");

async function api(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `请求失败（${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function specMap() { return new Map((state?.catalog?.specs || []).map(row => [Number(row.id), row])); }
function classMap() { return new Map((state?.catalog?.classes || []).map(row => [row.key, row])); }
function roleMap() { return new Map((state?.catalog?.roles || []).map(row => [row.key, row])); }
function currentEntry() { return state?.entries?.find(row => Number(row.userId) === Number(state.currentUser.id)); }
function specIcon(spec) { return `/assets/specs/${spec.slug}.jpg`; }
function specLabel(spec) {
  const wowClass = classMap().get(spec.classKey);
  return `${wowClass?.name || ""}·${spec.name}`;
}
function classColor(classKey) { return classMap().get(classKey)?.color || "#edf2f7"; }

async function load() {
  try {
    state = await api("/api/recruitment");
    backendMode = true;
  } catch (error) {
    if (![401, 404].includes(error.status) && location.protocol !== "file:") throw error;
    const catalogResponse = await fetch("/assets/specs/catalog.json");
    const catalog = await catalogResponse.json();
    backendMode = false;
    const saved = JSON.parse(localStorage.getItem(OFFLINE_KEY) || "null");
    state = buildOfflineState(catalog, saved);
    showMessage("当前为离线浏览，填写内容只保存在这台设备。");
  }
  renderAll();
}

function buildOfflineState(catalog, saved) {
  const entries = saved ? [{ ...saved, userId: 0, username: "offline", updatedAt: saved.updatedAt || new Date().toISOString() }] : [];
  const specs = new Map(catalog.specs.map(row => [Number(row.id), row]));
  entries.forEach(entry => {
    const spec = specs.get(Number(entry.primarySpecId));
    entry.primaryRole = spec.role;
    entry.primaryClassKey = spec.classKey;
  });
  return { catalog, entries, currentUser: { id: 0, username: "本机玩家", isAdmin: true }, summary: computeSummary(catalog, entries) };
}

function computeSummary(catalog, entries) {
  const roleCounts = Object.fromEntries(catalog.roles.map(row => [row.key, 0]));
  const compositionCounts = { tank: 0, melee: 0, ranged: 0 };
  const melee = new Set(catalog.compositionGroups.find(row => row.key === "melee").specIds);
  const present = new Set();
  entries.forEach(entry => {
    roleCounts[entry.primaryRole] += 1;
    if (entry.primaryRole === "tank") compositionCounts.tank += 1;
    else if (melee.has(Number(entry.primarySpecId))) compositionCounts.melee += 1;
    else compositionCounts.ranged += 1;
    present.add(entry.primaryClassKey);
  });
  return { total: entries.length, roleCounts, compositionCounts, missingClassKeys: catalog.classes.filter(row => !present.has(row.key)).map(row => row.key) };
}

function renderAll() {
  renderFilters();
  renderRoster();
  renderSidebar();
}

function renderFilters() {
  const counts = state.summary.roleCounts;
  const filters = [{ key: "all", name: "全部", count: state.summary.total }, ...state.catalog.roles.map(row => ({ ...row, count: counts[row.key] || 0 }))];
  $("#roleFilters").innerHTML = filters.map(row => `<button type="button" class="filter-tab ${listRole === row.key ? "active" : ""}" data-role="${row.key}">${escapeHtml(row.name)}<b>${row.count}</b></button>`).join("");
  $("#roleFilters").querySelectorAll("button").forEach(button => button.addEventListener("click", () => {
    listRole = button.dataset.role;
    renderAll();
  }));
}

function entryMatches(entry, query) {
  if (!query) return true;
  const specs = specMap();
  const primary = specs.get(Number(entry.primarySpecId));
  const secondary = (entry.secondarySpecIds || []).map(id => specs.get(Number(id))).filter(Boolean);
  return normalized([entry.playerName, entry.username, entry.notes, specLabel(primary), ...secondary.map(specLabel)].join(" ")).includes(query);
}

function renderRoster() {
  const query = normalized($("#listSearch").value);
  const visible = state.entries.filter(entry => (listRole === "all" || entry.primaryRole === listRole) && entryMatches(entry, query));
  $("#resultCount").textContent = `显示 ${visible.length} / ${state.entries.length} 名玩家`;
  if (!visible.length) {
    const isEmpty = state.entries.length === 0;
    $("#rosterList").innerHTML = `<div class="empty-state"><div><span class="empty-state-icon">${isEmpty ? "+" : "···"}</span><h2>${isEmpty ? "还没有人填写职业意向" : "没有找到匹配的条目"}</h2><p>${isEmpty ? "点击右上角按钮，从你的主职选择开始。" : "试试清除搜索关键词或切换职责筛选。"}</p></div></div>`;
    return;
  }
  const roles = state.catalog.roles.filter(role => listRole === "all" || role.key === listRole);
  $("#rosterList").innerHTML = roles.map(role => {
    const rows = visible.filter(entry => entry.primaryRole === role.key);
    if (!rows.length) return "";
    return `<section class="role-section" style="--role-color:${ROLE_COLORS[role.key]}"><header class="role-section-heading"><span class="role-symbol">${ROLE_SYMBOLS[role.key]}</span><h2>${escapeHtml(role.name)}</h2><span>${rows.length} 人</span></header><div class="role-rows">${rows.map(renderEntry).join("")}</div></section>`;
  }).join("");
  $("#rosterList").querySelectorAll("[data-edit-own]").forEach(button => button.addEventListener("click", openEditor));
}

function renderEntry(entry) {
  const specs = specMap();
  const roles = roleMap();
  const primary = specs.get(Number(entry.primarySpecId));
  const wowClass = classMap().get(primary.classKey);
  const role = roles.get(primary.role);
  const own = Number(entry.userId) === Number(state.currentUser.id);
  const secondary = (entry.secondarySpecIds || []).map(id => specs.get(Number(id))).filter(Boolean);
  const chips = secondary.length ? secondary.map(spec => `<span class="secondary-chip" style="--chip-color:${classColor(spec.classKey)}" title="${escapeHtml(specLabel(spec))}"><img src="${specIcon(spec)}" alt=""><span>${escapeHtml(spec.name)}</span></span>`).join("") : `<span class="no-secondary">暂无次选</span>`;
  return `<article class="roster-row" style="--class-color:${wowClass.color}">
    <div class="player-cell"><img class="spec-icon" src="${specIcon(primary)}" alt="${escapeHtml(primary.name)}专精"><div class="player-copy"><strong>${escapeHtml(entry.playerName)}${own ? `<span class="own-badge">我</span>` : ""}</strong><span>${relativeTime(entry.updatedAt)}更新</span></div></div>
    <div class="main-spec-cell"><small>MAIN SPECIALIZATION</small><strong>${escapeHtml(wowClass.name)}·${escapeHtml(primary.name)}<span class="role-pill" style="--role-color:${ROLE_COLORS[primary.role]}">${escapeHtml(role.shortName)}</span></strong></div>
    <div class="secondary-cell">${chips}</div>
    ${entry.notes ? `<div class="notes-cell" title="${escapeHtml(entry.notes)}"><p>${escapeHtml(entry.notes)}</p></div>` : `<div class="notes-cell"><p>—</p></div>`}
    ${own ? `<button type="button" class="edit-row" data-edit-own aria-label="编辑我的职业意向" title="编辑我的条目">✎</button>` : `<span></span>`}
  </article>`;
}

function renderSidebar() {
  const summary = state.summary;
  $("#totalCount").textContent = `${summary.total} 人`;
  const maximum = Math.max(1, ...Object.values(summary.roleCounts));
  $("#roleStats").innerHTML = state.catalog.roles.map(role => {
    const count = summary.roleCounts[role.key] || 0;
    return `<div class="stat-row" style="--stat-color:${ROLE_COLORS[role.key]}"><i></i><span>${escapeHtml(role.name)}</span><span class="stat-bar"><i style="--width:${Math.round(count / maximum * 100)}%"></i></span><b>${count}</b></div>`;
  }).join("");
  $("#compositionStats").innerHTML = state.catalog.compositionGroups.map(group => `<div class="composition-stat" style="--stat-color:${COMPOSITION_COLORS[group.key]}"><span>${escapeHtml(group.name)}</span><strong>${summary.compositionCounts[group.key] || 0}</strong></div>`).join("");

  const classes = classMap();
  const specs = specMap();
  const missing = summary.missingClassKeys.map(key => classes.get(key)).filter(Boolean);
  $("#missingClasses").innerHTML = missing.length ? missing.map(wowClass => {
    const iconSpec = specs.get(Number(wowClass.iconSpecId));
    return `<span class="missing-class" style="--class-color:${wowClass.color}" title="${escapeHtml(wowClass.name)}"><img src="${specIcon(iconSpec)}" alt="${escapeHtml(wowClass.name)}"></span>`;
  }).join("") : `<span class="all-covered">✓ 全职业已覆盖</span>`;
  $("#missingHint").textContent = missing.length ? `主职中尚无 ${missing.length} 个职业；悬停图标可查看职业名。` : "当前每个职业都至少有一名主职意向。";
}

function relativeTime(value) {
  const time = new Date(value).getTime();
  if (!Number.isFinite(time)) return "刚刚";
  const seconds = Math.max(0, Math.floor((Date.now() - time) / 1000));
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)} 天前`;
  return new Date(value).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function openEditor() {
  const entry = currentEntry();
  primarySpecId = entry ? Number(entry.primarySpecId) : null;
  secondarySpecIds = entry ? entry.secondarySpecIds.map(Number) : [];
  $("#playerName").value = entry?.playerName || state.currentUser.username || "";
  $("#notes").value = entry?.notes || "";
  $("#deleteChoice").hidden = !entry;
  $("#drawerBackdrop").hidden = false;
  $("#editorDrawer").classList.add("open");
  $("#editorDrawer").setAttribute("aria-hidden", "false");
  document.body.classList.add("overlay-open");
  renderEditor();
  setTimeout(() => $("#playerName").focus(), 180);
}

function closeEditor() {
  $("#editorDrawer").classList.remove("open");
  $("#editorDrawer").setAttribute("aria-hidden", "true");
  $("#drawerBackdrop").hidden = true;
  if ($("#pickerBackdrop").hidden) document.body.classList.remove("overlay-open");
}

function renderEditor() {
  const specs = specMap();
  const primary = specs.get(primarySpecId);
  if (primary) {
    const wowClass = classMap().get(primary.classKey);
    $("#primarySlot").className = "spec-slot";
    $("#primarySlot").style.setProperty("--class-color", wowClass.color);
    $("#primarySlot").innerHTML = `<img src="${specIcon(primary)}" alt=""><span><strong>${escapeHtml(wowClass.name)}·${escapeHtml(primary.name)}</strong><small>${escapeHtml(roleMap().get(primary.role).name)} · 点击重新选择</small></span><i>→</i>`;
  } else {
    $("#primarySlot").className = "spec-slot empty";
    $("#primarySlot").style.setProperty("--class-color", "#d9ad58");
    $("#primarySlot").innerHTML = `<span class="slot-plus">+</span><span><strong>选择主选专精</strong><small>从 40 个专精中选择</small></span><i>→</i>`;
  }
  $("#secondaryList").innerHTML = secondarySpecIds.map((id, index) => {
    const spec = specs.get(id);
    const wowClass = classMap().get(spec.classKey);
    return `<div class="secondary-choice" style="--class-color:${wowClass.color}"><img src="${specIcon(spec)}" alt=""><span><strong>${escapeHtml(wowClass.name)}·${escapeHtml(spec.name)}</strong><small>${escapeHtml(roleMap().get(spec.role).name)}</small></span><span class="choice-order">0${index + 1}</span><button type="button" class="remove-choice" data-remove-index="${index}" aria-label="移除${escapeHtml(spec.name)}">×</button></div>`;
  }).join("");
  $("#secondaryList").querySelectorAll("[data-remove-index]").forEach(button => button.addEventListener("click", () => {
    secondarySpecIds.splice(Number(button.dataset.removeIndex), 1);
    renderEditor();
  }));
  $("#secondaryCount").textContent = `${secondarySpecIds.length} / 4`;
  $("#addSecondary").disabled = secondarySpecIds.length >= 4;
  $("#notesCount").textContent = `${$("#notes").value.length} / 300`;
}

function openPicker(mode) {
  pickerMode = mode;
  pickerRole = "all";
  $("#specSearch").value = "";
  $("#pickerTitle").textContent = mode === "primary" ? "选择主选专精" : "添加次选专精";
  $("#pickerBackdrop").hidden = false;
  document.body.classList.add("overlay-open");
  renderPicker();
  setTimeout(() => $("#specSearch").focus(), 60);
}

function closePicker() {
  $("#pickerBackdrop").hidden = true;
  if (!$("#editorDrawer").classList.contains("open")) document.body.classList.remove("overlay-open");
}

function renderPicker() {
  const roles = [{ key: "all", name: "全部" }, ...state.catalog.roles];
  $("#pickerRoleFilters").innerHTML = roles.map(role => `<button type="button" class="picker-tab ${pickerRole === role.key ? "active" : ""}" data-picker-role="${role.key}">${escapeHtml(role.name)}</button>`).join("");
  $("#pickerRoleFilters").querySelectorAll("button").forEach(button => button.addEventListener("click", () => {
    pickerRole = button.dataset.pickerRole;
    renderPicker();
  }));
  const query = normalized($("#specSearch").value);
  const disabled = new Set(pickerMode === "secondary" ? [primarySpecId, ...secondarySpecIds] : []);
  const selected = new Set(pickerMode === "primary" ? [primarySpecId] : secondarySpecIds);
  const specs = state.catalog.specs.filter(spec => (pickerRole === "all" || spec.role === pickerRole) && normalized(specLabel(spec)).includes(query));
  $("#specGrid").innerHTML = specs.length ? specs.map(spec => {
    const wowClass = classMap().get(spec.classKey);
    return `<button type="button" class="spec-option ${selected.has(Number(spec.id)) ? "selected" : ""}" data-spec-id="${spec.id}" style="--class-color:${wowClass.color}" ${disabled.has(Number(spec.id)) ? "disabled" : ""}><img src="${specIcon(spec)}" alt=""><span><strong>${escapeHtml(spec.name)}</strong><small>${escapeHtml(wowClass.name)} · ${escapeHtml(roleMap().get(spec.role).name)}</small></span></button>`;
  }).join("") : `<div class="picker-empty">没有找到匹配的专精。</div>`;
  $("#specGrid").querySelectorAll("[data-spec-id]").forEach(button => button.addEventListener("click", () => {
    const id = Number(button.dataset.specId);
    if (pickerMode === "primary") {
      primarySpecId = id;
      secondarySpecIds = secondarySpecIds.filter(value => value !== id);
    } else if (secondarySpecIds.length < 4 && !secondarySpecIds.includes(id) && id !== primarySpecId) {
      secondarySpecIds.push(id);
    }
    closePicker();
    renderEditor();
  }));
}

async function saveChoice(event) {
  event.preventDefault();
  if (!primarySpecId) return toast("请先选择一个主选专精。", true);
  const playerName = $("#playerName").value.trim();
  if (!playerName) return toast("请填写角色名。", true);
  const payload = { playerName, primarySpecId, secondarySpecIds, notes: $("#notes").value.trim() };
  $("#saveChoice").disabled = true;
  try {
    if (backendMode) state = await api("/api/recruitment", { method: "PUT", body: JSON.stringify(payload) });
    else {
      localStorage.setItem(OFFLINE_KEY, JSON.stringify({ ...payload, updatedAt: new Date().toISOString() }));
      state = buildOfflineState(state.catalog, { ...payload, updatedAt: new Date().toISOString() });
    }
    closeEditor();
    renderAll();
    toast("职业意向已保存。");
  } catch (error) { toast(error.message, true); }
  finally { $("#saveChoice").disabled = false; }
}

async function deleteChoice() {
  if (!confirm("确定删除你的职业意向吗？删除后可以重新填写。")) return;
  try {
    if (backendMode) state = await api("/api/recruitment", { method: "DELETE" });
    else {
      localStorage.removeItem(OFFLINE_KEY);
      state = buildOfflineState(state.catalog, null);
    }
    closeEditor();
    renderAll();
    toast("已删除你的职业意向。");
  } catch (error) { toast(error.message, true); }
}

function showMessage(message) {
  $("#message").textContent = message;
  $("#message").hidden = false;
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.hidden = true; }, 3500);
}

$("#openEditor").addEventListener("click", openEditor);
$("#closeEditor").addEventListener("click", closeEditor);
$("#cancelEditor").addEventListener("click", closeEditor);
$("#drawerBackdrop").addEventListener("click", closeEditor);
$("#primarySlot").addEventListener("click", () => openPicker("primary"));
$("#addSecondary").addEventListener("click", () => openPicker("secondary"));
$("#closePicker").addEventListener("click", closePicker);
$("#pickerBackdrop").addEventListener("click", event => { if (event.target === $("#pickerBackdrop")) closePicker(); });
$("#choiceForm").addEventListener("submit", saveChoice);
$("#deleteChoice").addEventListener("click", deleteChoice);
$("#notes").addEventListener("input", renderEditor);
$("#listSearch").addEventListener("input", renderRoster);
$("#specSearch").addEventListener("input", renderPicker);
document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    if (!$("#pickerBackdrop").hidden) closePicker();
    else if ($("#editorDrawer").classList.contains("open")) closeEditor();
  }
  if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    event.preventDefault();
    $("#listSearch").focus();
  }
});

load().catch(error => {
  $("#rosterList").innerHTML = `<div class="empty-state"><div><span class="empty-state-icon">!</span><h2>加载失败</h2><p>${escapeHtml(error.message)}</p></div></div>`;
  showMessage(error.message);
});
