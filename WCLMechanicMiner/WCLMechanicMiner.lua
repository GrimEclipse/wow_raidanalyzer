local ADDON_NAME = ...

WCLMechanicMinerDB = WCLMechanicMinerDB or {}

local Miner = {}
local DEFAULT_LOCALE = GetLocale and GetLocale() or "unknown"

local function now()
    return date and date("%Y-%m-%d %H:%M:%S") or tostring(time())
end

local function printf(...)
    print("|cff7dd3fcWMM|r " .. string.format(...))
end

local function trimText(text)
    if not text then return "" end
    text = tostring(text)
    text = text:gsub("|c%x%x%x%x%x%x%x%x", "")
    text = text:gsub("|r", "")
    text = text:gsub("\r\n", "\n")
    return text
end

local function safeCall(fn, ...)
    if type(fn) ~= "function" then
        return false
    end
    return pcall(fn, ...)
end

local function getTierInfo(index)
    if EJ_GetTierInfo then
        return EJ_GetTierInfo(index)
    end
end

local function selectTier(tierIndex)
    if EJ_SelectTier then
        return safeCall(EJ_SelectTier, tierIndex)
    end
    return false
end

local function getNumTiers()
    if EJ_GetNumTiers then
        return EJ_GetNumTiers() or 0
    end
    return 0
end

local function getInstanceByIndex(index, isRaid)
    if EJ_GetInstanceByIndex then
        return EJ_GetInstanceByIndex(index, isRaid)
    end
end

local function selectInstance(instanceID)
    if EJ_SelectInstance then
        EJ_SelectInstance(instanceID)
    end
end

local function selectEncounter(encounterID)
    if EJ_SelectEncounter then
        EJ_SelectEncounter(encounterID)
    end
end

local function getEncounterInfoByIndex(index)
    if EJ_GetEncounterInfoByIndex then
        return EJ_GetEncounterInfoByIndex(index)
    end
end

local function getInstanceInfo(instanceID)
    if EJ_GetInstanceInfo then
        return EJ_GetInstanceInfo(instanceID)
    end
end

local function getCreatureInfo(index, encounterID)
    if EJ_GetCreatureInfo then
        return EJ_GetCreatureInfo(index, encounterID)
    end
end

local function getSectionInfo(sectionID)
    if not sectionID or not EJ_GetSectionInfo then
        return nil
    end

    local title, description, headerType, abilityIcon, creatureDisplayID, uiModelSceneID,
          siblingSectionID, firstChildSectionID, filteredByDifficulty, link, startsOpen,
          flag1, flag2, flag3, flag4, spellID, iconFlags, difficultyMask = EJ_GetSectionInfo(sectionID)

    if not title and not description and not firstChildSectionID and not siblingSectionID then
        return nil
    end

    return {
        sectionID = sectionID,
        title = trimText(title),
        description = trimText(description),
        headerType = headerType,
        abilityIcon = abilityIcon,
        creatureDisplayID = creatureDisplayID,
        uiModelSceneID = uiModelSceneID,
        siblingSectionID = siblingSectionID,
        firstChildSectionID = firstChildSectionID,
        filteredByDifficulty = filteredByDifficulty and true or false,
        link = link,
        startsOpen = startsOpen and true or false,
        flags = { flag1, flag2, flag3, flag4 },
        spellID = spellID,
        iconFlags = iconFlags,
        difficultyMask = difficultyMask,
    }
end

local function addSpellIndex(db, section, instance, encounter)
    local spellID = tonumber(section.spellID)
    if not spellID or spellID <= 0 then
        return
    end

    db.spells[tostring(spellID)] = db.spells[tostring(spellID)] or {
        spellID = spellID,
        names = {},
        descriptions = {},
        sources = {},
    }

    local row = db.spells[tostring(spellID)]
    if section.title and section.title ~= "" then
        row.names[section.title] = true
    end
    if section.description and section.description ~= "" then
        row.descriptions[section.description] = true
    end

    table.insert(row.sources, {
        instanceID = instance.instanceID,
        instanceName = instance.name,
        encounterID = encounter.encounterID,
        encounterName = encounter.name,
        sectionID = section.sectionID,
        title = section.title,
    })
end

local function collectSections(db, instance, encounter, rootSectionID)
    local sections = {}
    local visited = {}

    local function visit(sectionID, depth)
        if not sectionID or visited[sectionID] then
            return
        end
        visited[sectionID] = true

        local section = getSectionInfo(sectionID)
        if not section then
            return
        end

        section.depth = depth or 0
        table.insert(sections, section)
        addSpellIndex(db, section, instance, encounter)

        if section.firstChildSectionID then
            visit(section.firstChildSectionID, (depth or 0) + 1)
        end
        if section.siblingSectionID then
            visit(section.siblingSectionID, depth or 0)
        end
    end

    visit(rootSectionID, 0)
    return sections
end

local function collectCreatures(encounterID)
    local creatures = {}
    for i = 1, 20 do
        local name, description, displayInfo, iconImage = getCreatureInfo(i, encounterID)
        if not name then
            break
        end
        table.insert(creatures, {
            name = trimText(name),
            description = trimText(description),
            displayInfo = displayInfo,
            iconImage = iconImage,
        })
    end
    return creatures
end

local function collectEncounter(db, instance, encounterIndex)
    local name, description, encounterID, rootSectionID, link = getEncounterInfoByIndex(encounterIndex)
    if not encounterID then
        return nil
    end

    selectEncounter(encounterID)

    local encounter = {
        encounterID = encounterID,
        name = trimText(name),
        description = trimText(description),
        rootSectionID = rootSectionID,
        link = link,
        creatures = collectCreatures(encounterID),
        sections = {},
    }

    encounter.sections = collectSections(db, instance, encounter, rootSectionID)
    return encounter
end

local function collectInstance(db, tier, instanceID, name, description, bgImage, buttonImage, loreImage, dungeonAreaMapID, link)
    local instance = {
        instanceID = instanceID,
        name = trimText(name),
        description = trimText(description),
        bgImage = bgImage,
        buttonImage = buttonImage,
        loreImage = loreImage,
        dungeonAreaMapID = dungeonAreaMapID,
        link = link,
        encounters = {},
    }

    selectInstance(instanceID)

    local infoName, infoDescription, _, _, _, _, _, mapID = getInstanceInfo(instanceID)
    if infoName then instance.name = trimText(infoName) end
    if infoDescription then instance.description = trimText(infoDescription) end
    if mapID then instance.mapID = mapID end

    for encounterIndex = 1, 50 do
        local encounter = collectEncounter(db, instance, encounterIndex)
        if not encounter then
            break
        end
        table.insert(instance.encounters, encounter)
    end

    return instance
end

function Miner:Reset()
    WCLMechanicMinerDB = {
        meta = {
            addon = ADDON_NAME or "WCLMechanicMiner",
            version = "0.1.1",
            locale = DEFAULT_LOCALE,
            generatedAt = now(),
        },
        tiers = {},
        spells = {},
    }
end

function Miner:Dump(options)
    options = options or {}
    self:Reset()

    local db = WCLMechanicMinerDB
    local tierCount = getNumTiers()
    local currentTierOnly = options.currentTierOnly
    local requestedTier = options.tierID

    printf("开始抓取地下城手册。tiers=%s mode=%s", tostring(tierCount), currentTierOnly and "current" or "all")

    for tierIndex = 1, tierCount do
        local tierName = getTierInfo(tierIndex)
        local tierID = tierIndex
        if tierName and (not requestedTier or requestedTier == tierIndex) then
            if not currentTierOnly or tierIndex == tierCount then
                local selected, selectError = selectTier(tierIndex)
                if not selected then
                    printf("无法选择版本层级 %s：%s", tostring(tierIndex), tostring(selectError or "EJ_SelectTier unavailable"))
                    return
                end

                local tier = {
                    tierID = tierID,
                    tierIndex = tierIndex,
                    name = trimText(tierName),
                    raids = {},
                }

                printf("抓取版本层级：%s / %s", tostring(tierID), tier.name ~= "" and tier.name or ("tier " .. tierIndex))

                for instanceIndex = 1, 100 do
                    local instanceID, name, description, bgImage, buttonImage, loreImage, dungeonAreaMapID, link = getInstanceByIndex(instanceIndex, true)
                    if not instanceID then
                        break
                    end

                    local instance = collectInstance(db, tier, instanceID, name, description, bgImage, buttonImage, loreImage, dungeonAreaMapID, link)
                    table.insert(tier.raids, instance)
                    printf("  raid %s: %s, boss=%d", tostring(instanceID), instance.name, #instance.encounters)
                end

                table.insert(db.tiers, tier)
            end
        end
    end

    db.meta.generatedAt = now()
    db.meta.tierCount = #db.tiers

    local raidCount, bossCount, sectionCount, spellCount = 0, 0, 0, 0
    for _, tier in ipairs(db.tiers) do
        raidCount = raidCount + #tier.raids
        for _, raid in ipairs(tier.raids) do
            bossCount = bossCount + #raid.encounters
            for _, encounter in ipairs(raid.encounters) do
                sectionCount = sectionCount + #encounter.sections
            end
        end
    end
    for _ in pairs(db.spells) do
        spellCount = spellCount + 1
    end

    db.meta.raidCount = raidCount
    db.meta.bossCount = bossCount
    db.meta.sectionCount = sectionCount
    db.meta.spellCount = spellCount

    printf("抓取完成：raid=%d boss=%d section=%d spell=%d", raidCount, bossCount, sectionCount, spellCount)
    printf("数据会保存到 SavedVariables/WCLMechanicMiner.lua。请 /reload 或正常退出后查看。")
end

function Miner:Summary()
    local db = WCLMechanicMinerDB or {}
    local meta = db.meta or {}
    printf("当前缓存：generatedAt=%s raid=%s boss=%s section=%s spell=%s",
        tostring(meta.generatedAt),
        tostring(meta.raidCount or 0),
        tostring(meta.bossCount or 0),
        tostring(meta.sectionCount or 0),
        tostring(meta.spellCount or 0))
end

function Miner:Find(query)
    query = query and query:lower() or ""
    if query == "" then
        printf("用法：/wmm find 星辰裂片")
        return
    end

    local count = 0
    for spellID, row in pairs((WCLMechanicMinerDB or {}).spells or {}) do
        local matched = false
        for name in pairs(row.names or {}) do
            if name:lower():find(query, 1, true) then matched = true end
        end
        for desc in pairs(row.descriptions or {}) do
            if desc:lower():find(query, 1, true) then matched = true end
        end
        if matched then
            count = count + 1
            local firstName = ""
            for name in pairs(row.names or {}) do firstName = name break end
            printf("%s %s sources=%d", tostring(spellID), firstName, #(row.sources or {}))
            if count >= 20 then
                printf("结果超过 20 条，已截断。")
                break
            end
        end
    end
    if count == 0 then
        printf("没有找到：%s", query)
    end
end

local function showHelp()
    printf("/wmm dump current  - 抓取当前最高版本层级的所有团队副本")
    printf("/wmm dump all      - 抓取地下城手册全部团队副本")
    printf("/wmm summary       - 查看当前缓存规模")
    printf("/wmm find 关键词   - 在已抓取的技能名称/描述中搜索")
    printf("/wmm clear         - 清空 SavedVariables 缓存")
end

SLASH_WCLMECHANICMINER1 = "/wmm"
SlashCmdList.WCLMECHANICMINER = function(msg)
    msg = msg or ""
    local cmd, rest = msg:match("^(%S*)%s*(.-)$")
    cmd = (cmd or ""):lower()
    rest = rest or ""

    if cmd == "dump" then
        local mode = rest:lower()
        Miner:Dump({ currentTierOnly = mode ~= "all" })
    elseif cmd == "summary" then
        Miner:Summary()
    elseif cmd == "find" then
        Miner:Find(rest)
    elseif cmd == "clear" then
        Miner:Reset()
        printf("缓存已清空。")
    else
        showHelp()
    end
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:SetScript("OnEvent", function(_, event, addonName)
    if event == "ADDON_LOADED" and addonName == ADDON_NAME then
        WCLMechanicMinerDB = WCLMechanicMinerDB or {}
        printf("已加载。输入 /wmm 查看命令。")
    end
end)
