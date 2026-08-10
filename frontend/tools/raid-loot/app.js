const CLASS_OPTIONS = [
  ["death-knight", "死亡骑士", "plate"], ["demon-hunter", "恶魔猎手", "leather"],
  ["druid", "德鲁伊", "leather"], ["evoker", "唤魔师", "mail"],
  ["hunter", "猎人", "mail"], ["mage", "法师", "cloth"], ["monk", "武僧", "leather"],
  ["paladin", "圣骑士", "plate"], ["priest", "牧师", "cloth"], ["rogue", "潜行者", "leather"],
  ["shaman", "萨满祭司", "mail"], ["warlock", "术士", "cloth"], ["warrior", "战士", "plate"]
];
const DIFFICULTY_NAMES = { lfr: "随机团队", normal: "普通", heroic: "英雄", mythic: "史诗" };
const MODE_NAMES = { need: "需求", greed: "贪婪", transmog: "幻化收藏", alt: "小号提升" };
const ATTENDANCE_NAMES = { present: "出勤", late: "迟到", leave: "请假", absent: "缺勤" };
const ARMOR_NAMES = { cloth: "布甲", leather: "皮甲", mail: "锁甲", plate: "板甲", accessory: "首饰", weapon: "武器", token: "套装兑换物", other: "其他" };

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const today = new Date();
let selectedDate = localDate(today);
let displayedMonth = new Date(today.getFullYear(), today.getMonth(), 1);
let documentState = null;

function localDate(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败（${response.status}）`);
  return payload;
}

function notify(message, error = false) {
  const box = $("#message");
  box.textContent = message;
  box.classList.toggle("error", error);
  box.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { box.hidden = true; }, 4500);
}

function roster() { return documentState?.state?.roster || []; }
function raids() { return documentState?.catalog?.raids || []; }
function selectedRaid() { return raids().find(row => row.key === $("#dayRaid").value) || raids()[0]; }
function selectedBoss() { return selectedRaid()?.bosses?.find(row => row.key === $("#bossSelect").value); }
function playerName(id) { return roster().find(row => row.id === id)?.name || id; }

async function load() {
  const difficulty = $("#difficultySelect").value;
  documentState = await api(`/api/loot?date=${selectedDate}&difficulty=${difficulty}`);
  renderAll();
}

function renderAll() {
  renderRaidOptions();
  renderCalendar();
  renderDay();
  renderRoster();
  renderRecipientOptions();
  renderClassFilter();
  renderBossOptions();
  renderEligibility();
  renderRequests();
  renderAllocations();
}

function renderRaidOptions() {
  const select = $("#dayRaid");
  const currentDay = documentState.state.days.find(row => row.date === selectedDate);
  const desired = currentDay?.raidKey || select.value || raids()[0]?.key || "";
  select.innerHTML = raids().map(raid => `<option value="${escapeHtml(raid.key)}">${escapeHtml(raid.name)}</option>`).join("");
  select.value = desired;
}

function renderCalendar() {
  const year = displayedMonth.getFullYear();
  const month = displayedMonth.getMonth();
  $("#monthTitle").textContent = `${year} 年 ${month + 1} 月`;
  const first = new Date(year, month, 1);
  const mondayOffset = (first.getDay() + 6) % 7;
  const start = new Date(year, month, 1 - mondayOffset);
  const dataDates = new Set([
    ...documentState.state.days.map(row => row.date),
    ...documentState.state.allocations.map(row => row.date)
  ]);
  $("#calendar").innerHTML = Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + index);
    const key = localDate(date);
    const weekday = date.getDay();
    const classes = ["calendar-day"];
    if (date.getMonth() !== month) classes.push("other");
    if ([4, 5, 6].includes(weekday)) classes.push("raid");
    if (key === selectedDate) classes.push("selected");
    if (dataDates.has(key)) classes.push("has-data");
    return `<button class="${classes.join(" ")}" data-date="${key}">${date.getDate()}</button>`;
  }).join("");
  $("#calendar").querySelectorAll("button").forEach(button => button.addEventListener("click", () => selectDate(button.dataset.date)));
}

function selectDate(value) {
  captureDay();
  selectedDate = value;
  const parsed = new Date(`${value}T12:00:00`);
  displayedMonth = new Date(parsed.getFullYear(), parsed.getMonth(), 1);
  refreshForSelection();
}

async function refreshForSelection() {
  try {
    const difficulty = $("#difficultySelect").value;
    const fresh = await api(`/api/loot?date=${selectedDate}&difficulty=${difficulty}`);
    documentState.eligibility = fresh.eligibility;
    documentState.state.allocations = fresh.state.allocations;
    documentState.state.days = fresh.state.days;
    renderCalendar(); renderDay(); renderEligibility(); renderAllocations(); renderRaidOptions(); renderBossOptions();
  } catch (error) { notify(error.message, true); }
}

function currentDayRecord(create = true) {
  let day = documentState.state.days.find(row => row.date === selectedDate);
  if (!day && create) {
    day = { date: selectedDate, raidKey: raids()[0]?.key || "venomous_abyss", notes: "", attendance: [] };
    documentState.state.days.push(day);
  }
  return day;
}

function renderDay() {
  const date = new Date(`${selectedDate}T12:00:00`);
  $("#selectedDateTitle").textContent = `${date.getMonth() + 1} 月 ${date.getDate()} 日 · 周${"日一二三四五六"[date.getDay()]}`;
  const day = currentDayRecord(false);
  $("#dayNotes").value = day?.notes || "";
  if (day?.raidKey && $("#dayRaid").querySelector(`option[value="${CSS.escape(day.raidKey)}"]`)) $("#dayRaid").value = day.raidKey;
  const attendanceMap = new Map((day?.attendance || []).map(row => [row.playerId, row]));
  const activePlayers = roster().filter(row => row.active);
  $("#attendance").innerHTML = activePlayers.length ? activePlayers.map(player => {
    const value = attendanceMap.get(player.id)?.status || "present";
    return `<div class="attendance-card" data-player="${escapeHtml(player.id)}"><div><strong>${escapeHtml(player.name)}</strong><small>${escapeHtml(player.className || "未设置职业")}</small></div><select>${Object.entries(ATTENDANCE_NAMES).map(([key, name]) => `<option value="${key}" ${key === value ? "selected" : ""}>${name}</option>`).join("")}</select></div>`;
  }).join("") : `<div class="empty">请先在页面底部添加团队成员</div>`;
}

function captureDay() {
  if (!documentState) return;
  const day = currentDayRecord(true);
  day.raidKey = $("#dayRaid").value || day.raidKey;
  day.notes = $("#dayNotes").value.trim();
  day.attendance = [...$("#attendance").querySelectorAll(".attendance-card")].map(card => ({
    playerId: card.dataset.player, status: card.querySelector("select").value, note: ""
  }));
}

function renderRoster() {
  const classOptions = CLASS_OPTIONS.map(([key, name]) => `<option value="${key}">${name}</option>`).join("");
  $("#rosterRows").innerHTML = roster().length ? roster().map(player => `<div class="roster-row" data-id="${escapeHtml(player.id)}">
    <label>角色名<input class="player-name" value="${escapeHtml(player.name)}"></label>
    <label>职业<select class="player-class"><option value="">未设置</option>${classOptions}</select></label>
    <label>护甲类型<select class="player-armor">${Object.entries(ARMOR_NAMES).filter(([key]) => ["cloth","leather","mail","plate"].includes(key)).map(([key,name]) => `<option value="${key}">${name}</option>`).join("")}</select></label>
    <label class="active"><input type="checkbox" ${player.active ? "checked" : ""}>活动</label>
    <button class="button danger remove-player">移除</button>
  </div>`).join("") : `<div class="empty">还没有团队成员，点击“添加成员”开始配置</div>`;
  $("#rosterRows").querySelectorAll(".roster-row").forEach(row => {
    const player = roster().find(item => item.id === row.dataset.id);
    row.querySelector(".player-class").value = player.classKey || "";
    row.querySelector(".player-armor").value = player.armorType || "other";
    row.querySelector(".player-class").addEventListener("change", event => {
      const meta = CLASS_OPTIONS.find(item => item[0] === event.target.value);
      if (meta) row.querySelector(".player-armor").value = meta[2];
    });
    row.querySelector(".remove-player").addEventListener("click", () => {
      documentState.state.roster = roster().filter(item => item.id !== row.dataset.id);
      renderAll();
    });
  });
}

function captureRoster() {
  documentState.state.roster = [...$("#rosterRows").querySelectorAll(".roster-row")].map(row => {
    const classKey = row.querySelector(".player-class").value;
    const meta = CLASS_OPTIONS.find(item => item[0] === classKey);
    return {
      id: row.dataset.id,
      name: row.querySelector(".player-name").value.trim(),
      classKey,
      className: meta?.[1] || "",
      armorType: row.querySelector(".player-armor").value,
      active: row.querySelector(".active input").checked,
      notes: ""
    };
  }).filter(row => row.name);
}

function renderRecipientOptions() {
  const options = roster().filter(row => row.active).map(row => `<option value="${escapeHtml(row.id)}">${escapeHtml(row.name)} · ${escapeHtml(row.className || "未设置职业")}</option>`).join("");
  $("#recipientSelect").innerHTML = options || `<option value="">请先添加成员</option>`;
}

function renderClassFilter() {
  const value = $("#classFilter").value;
  $("#classFilter").innerHTML = `<option value="">全部职业</option>${CLASS_OPTIONS.map(([key, name]) => `<option value="${key}">${name}</option>`).join("")}`;
  $("#classFilter").value = value;
}

function renderBossOptions() {
  const raid = selectedRaid();
  const current = $("#bossSelect").value;
  $("#bossSelect").innerHTML = (raid?.bosses || []).map(boss => `<option value="${escapeHtml(boss.key)}">${escapeHtml(boss.name)}</option>`).join("");
  if ([...$("#bossSelect").options].some(option => option.value === current)) $("#bossSelect").value = current;
  renderItemOptions();
}

function filteredItems() {
  const query = $("#itemSearch").value.trim().toLowerCase();
  const armor = $("#armorFilter").value;
  const classKey = $("#classFilter").value;
  return (selectedBoss()?.items || []).filter(item => {
    const haystack = [item.nameZh, item.nameEn, item.slot, ...(item.tags || [])].join(" ").toLowerCase();
    return (!query || haystack.includes(query))
      && (!armor || item.armorType === armor)
      && (!classKey || !(item.classes || []).length || item.classes.includes(classKey));
  });
}

function renderItemOptions() {
  const boss = selectedBoss();
  const previous = $("#itemSelect").value;
  const items = filteredItems();
  $("#itemSelect").innerHTML = items.length ? items.map(item => `<option value="${item.id}">${escapeHtml(item.nameZh)} · ${escapeHtml(item.slot)}${item.translationStatus === "temporary" ? "（暂译）" : ""}</option>`).join("") : `<option value="">暂无符合条件的装备</option>`;
  if (items.some(item => String(item.id) === previous)) $("#itemSelect").value = previous;
  const note = $("#lootSourceNote");
  if (!boss) { note.textContent = ""; return; }
  if (boss.lootStatus === "ptr-verified") {
    note.className = "source-note";
    note.innerHTML = `PTR 掉落已核验 · 中文名为工作暂译 · <a href="${escapeHtml(boss.sourceUrl)}" target="_blank" rel="noreferrer">查看 Wowhead 来源</a>`;
  } else {
    note.className = "source-note warning";
    note.textContent = "该 Boss 尚未取得可靠的 PTR NPC 掉落来源，当前不提供旧版或推测装备。";
  }
}

function renderEligibility() {
  $("#difficultyBadge").textContent = DIFFICULTY_NAMES[$("#difficultySelect").value];
  const rows = documentState.eligibility || [];
  $("#eligibility").classList.toggle("empty", !rows.length);
  $("#eligibility").innerHTML = rows.length ? rows.map(row => `<div class="eligibility-row"><strong>${escapeHtml(playerName(row.playerId))}</strong><span class="status ${row.needEligible ? "yes" : "no"}">${row.needEligible ? "可需求" : "仅贪婪"}</span><small>${escapeHtml(row.reason)}</small></div>`).join("") : "请先添加团队成员";
}

function renderRequests() {
  $("#requestRows").innerHTML = roster().filter(row => row.active).map(player => `<div class="request-row" data-player="${escapeHtml(player.id)}"><strong>${escapeHtml(player.name)}</strong><select><option value="">未登记</option>${Object.entries(MODE_NAMES).map(([key,name]) => `<option value="${key}">${name}</option>`).join("")}</select><input placeholder="备注（可选）"></div>`).join("");
}

function renderAllocations() {
  const rows = documentState.state.allocations.filter(row => row.date === selectedDate);
  $("#allocationCount").textContent = `${rows.length} 件`;
  const container = $("#allocationList");
  container.classList.toggle("empty", !rows.length);
  container.innerHTML = rows.length ? rows.map(row => {
    const boss = raids().flatMap(raid => raid.bosses || []).find(item => item.key === row.bossKey);
    const requestText = (row.requests || []).map(request => `${playerName(request.playerId)}：${MODE_NAMES[request.mode]}`).join(" · ");
    return `<div class="allocation-card"><div><h3>${escapeHtml(row.itemNameZh || row.itemName)}</h3><div class="allocation-meta"><span>${row.sourceType === "boe" ? "BOE" : escapeHtml(boss?.name || row.bossKey)}</span><span>${DIFFICULTY_NAMES[row.difficulty]}</span><span>${escapeHtml(playerName(row.recipientId))} · ${MODE_NAMES[row.awardType]}</span></div>${requestText ? `<div class="allocation-requests">需求详情：${escapeHtml(requestText)}</div>` : ""}${row.notes ? `<div class="allocation-requests">备注：${escapeHtml(row.notes)}</div>` : ""}</div><button class="button danger delete-allocation" data-id="${escapeHtml(row.id)}">删除</button></div>`;
  }).join("") : "当天还没有装备分配记录";
  container.querySelectorAll(".delete-allocation").forEach(button => button.addEventListener("click", () => deleteAllocation(button.dataset.id)));
}

async function saveSetup() {
  try {
    captureDay(); captureRoster();
    await api("/api/loot/setup", { method: "PUT", body: JSON.stringify({ roster: roster(), days: documentState.state.days }) });
    notify("团队名单与出勤已保存。最多一次需求和缺勤限制会自动重新计算。");
    await load();
  } catch (error) { notify(error.message, true); }
}

async function addAllocation() {
  try {
    const isBoe = $("#isBoe").checked;
    const item = isBoe ? null : (selectedBoss()?.items || []).find(row => String(row.id) === $("#itemSelect").value);
    const requests = [...$("#requestRows").querySelectorAll(".request-row")].map(row => ({ playerId: row.dataset.player, mode: row.querySelector("select").value, note: row.querySelector("input").value.trim() })).filter(row => row.mode);
    const payload = {
      date: selectedDate,
      raidKey: $("#dayRaid").value,
      bossKey: isBoe ? "boe" : $("#bossSelect").value,
      difficulty: $("#difficultySelect").value,
      sourceType: isBoe ? "boe" : "boss",
      itemId: item?.id || "",
      itemName: item?.nameEn || $("#boeName").value.trim(),
      itemNameZh: item?.nameZh || $("#boeName").value.trim(),
      itemTags: item?.tags || ["BOE"],
      recipientId: $("#recipientSelect").value,
      awardType: $("#awardType").value,
      requests,
      notes: $("#allocationNotes").value.trim()
    };
    await api("/api/loot/allocations", { method: "POST", body: JSON.stringify(payload) });
    $("#allocationNotes").value = ""; $("#boeName").value = "";
    notify("装备分配已登记。");
    await load();
  } catch (error) { notify(error.message, true); }
}

async function deleteAllocation(id) {
  if (!confirm("确定删除这条装备分配记录？")) return;
  try {
    await api(`/api/loot/allocations/${encodeURIComponent(id)}`, { method: "DELETE" });
    notify("分配记录已删除。");
    await load();
  } catch (error) { notify(error.message, true); }
}

function toggleBoe() {
  const checked = $("#isBoe").checked;
  $("#itemSelectWrap").hidden = checked;
  $("#boeNameWrap").hidden = !checked;
  $("#itemFilters").hidden = checked;
  $("#bossSelect").disabled = checked;
  $("#lootSourceNote").hidden = checked;
}

$("#prevMonth").addEventListener("click", () => { displayedMonth = new Date(displayedMonth.getFullYear(), displayedMonth.getMonth() - 1, 1); renderCalendar(); });
$("#nextMonth").addEventListener("click", () => { displayedMonth = new Date(displayedMonth.getFullYear(), displayedMonth.getMonth() + 1, 1); renderCalendar(); });
$("#dayRaid").addEventListener("change", () => { currentDayRecord(true).raidKey = $("#dayRaid").value; renderBossOptions(); });
$("#bossSelect").addEventListener("change", renderItemOptions);
$("#difficultySelect").addEventListener("change", refreshForSelection);
$("#itemSearch").addEventListener("input", renderItemOptions);
$("#armorFilter").addEventListener("change", renderItemOptions);
$("#classFilter").addEventListener("change", renderItemOptions);
$("#isBoe").addEventListener("change", toggleBoe);
$("#saveSetup").addEventListener("click", saveSetup);
$("#addAllocation").addEventListener("click", addAllocation);
$("#addPlayer").addEventListener("click", () => {
  captureRoster();
  documentState.state.roster.push({ id: `p-${Date.now().toString(36)}`, name: "", classKey: "", className: "", armorType: "other", active: true, notes: "" });
  renderRoster();
  $("#rosterRows .roster-row:last-child .player-name")?.focus();
});

load().catch(error => notify(error.message, true));
