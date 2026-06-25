# WCLMechanicMiner

轻量 WoW 插件，用于从游戏内地下城手册抓取团队副本、首领、技能 section、名称、描述和手册暴露的 spellID。

## 安装

把整个 `WCLMechanicMiner` 文件夹复制到魔兽插件目录，例如：

```text
World of Warcraft/_retail_/Interface/AddOns/WCLMechanicMiner/
```

目录里应该能看到：

```text
WCLMechanicMiner.toc
WCLMechanicMiner.lua
```

如果版本号不匹配，可以在角色选择界面勾选“加载过期插件”。

## 同步开发版本

项目目录中的插件是 Git 源版本。修改后在项目根目录执行：

```powershell
.\sync_wow_addon.ps1
```

默认会同步到：

```text
D:\World of Warcraft\_retail_\Interface\AddOns\WCLMechanicMiner
```

## 命令

```text
/wmm
```

显示帮助。

```text
/wmm dump current
```

抓取当前最高版本层级里的所有团队副本。建议先用这个。

```text
/wmm dump all
```

抓取地下城手册里所有团队副本，数据会更多。

```text
/wmm summary
```

查看当前缓存统计。

```text
/wmm find 星辰裂片
```

在已抓取的技能名和描述里搜索关键词。

```text
/wmm clear
```

清空缓存。

## 数据位置

执行 `/wmm dump current` 后，输入 `/reload` 或正常退出游戏，数据会写入：

```text
World of Warcraft/_retail_/WTF/Account/<账号>/SavedVariables/WCLMechanicMiner.lua
```

## 数据结构

核心字段：

```lua
WCLMechanicMinerDB = {
  meta = {
    generatedAt = "...",
    locale = "zhCN",
    raidCount = 3,
    bossCount = 8,
    sectionCount = 100,
    spellCount = 80,
  },
  tiers = {
    {
      tierID = 12,
      name = "...",
      raids = {
        {
          instanceID = 123,
          name = "进军奎尔丹纳斯",
          encounters = {
            {
              encounterID = 456,
              name = "至暗之夜降临",
              sections = {
                {
                  sectionID = 789,
                  title = "星辰裂片",
                  description = "...",
                  spellID = 1285510,
                }
              }
            }
          }
        }
      }
    }
  },
  spells = {
    ["1285510"] = {
      spellID = 1285510,
      names = { ["星辰裂片"] = true },
      descriptions = { ["..."] = true },
      sources = {
        {
          instanceName = "进军奎尔丹纳斯",
          encounterName = "至暗之夜降临",
          sectionID = 789,
          title = "星辰裂片",
        }
      }
    }
  }
}
```

## 注意

这个版本只做“方案 1：地下城手册抓取”。

它不能枚举客户端全量法术数据库，也不能直接推断 buffID 和 damageID 的因果关系。后续可以继续做：

- spellID 范围扫描
- combat log 验证
- SavedVariables 转 Python plugin 配置
