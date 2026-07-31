# 项目规整分支合并说明

## 分支信息

- 来源：项目瘦身集成分支
- 基线：`origin/main` 的 `8d7c621`
- 目的：清理误入项目的本地产物，明确源码、工具、运行数据和离线包的边界。
- 本分支不包含后续奥蕾莉亚机制调整。

## Git 中的改动

### `.gitignore`

保留并补充以下规则：

- `dist/`：离线包构建产物，不再纳入源码版本管理。
- `data/*`：WCL 分析 JSON 等运行数据；仅保留 `data/.gitkeep`。
- `data/wcl_hardcore_api.json`：兼容输出，不纳入版本管理。
- `tmp/`、`verdict_data.json`、`verdicts/`、`scoreboard/*.db`：本地临时或持久化数据。
- `.tools/`、`.video_work/`、`audio_material_license_notes.txt`：防止其他任务的素材再次误入项目。
- `*.zip`、`*.rar`、`*.exe`：发布产物和本地工具二进制。
- `*.doc`、`*.docx`：本地生成的 Word 文档。

如果合并时 `.gitignore` 冲突，应保留上述规则，尤其不要把 `dist/`、`data/*`、`tmp/` 改回可跟踪状态。

### 删除

- `assets/crown_of_cosmos_arena_p2.svg`
  - 页面实际使用 PNG。
  - 源码中已无该 SVG 的引用。

### 新增说明

- `mythic_dungeon_export/README.md`
  - 保留未来大秘境导出工具的目录规划。
  - 当前历史 `__pycache__` 不视为正式实现。
- `tools/README.md`
  - 说明正式分析入口与各开发、探针、离线修复、导出脚本的用途。

## 仅发生在本地磁盘的清理

以下内容此前只是误暂存或未跟踪文件，因此不会显示为本分支的删除 diff：

- `.tools/`：FFmpeg 压缩包、可执行文件和文档，约 408 MB。
- `.video_work/`：视频、音频和帧图片，约 120 MB。
- `audio_material_license_notes.txt`。
- `tmp/` 中未跟踪的合并备份。

这些文件已从当前工作区永久删除，并由 `.gitignore` 防止再次进入 Git。

## 合并建议

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
git merge --no-ff <项目瘦身分支>
```

如果远端在合并前继续修改了 `.gitignore`，按本文“`.gitignore`”一节保留双方有效规则。

## 验证记录

- 工作区中已不存在 `.tools/`、`.video_work/`、`audio_material_license_notes.txt`、`tmp/` 和 P2 SVG。
- `dist/`、`data/*`、根目录兼容 JSON 与本地数据库均命中忽略规则。
- `mythic_dungeon_export/` 目录规划与原有 `__pycache__` 均保留。
- `git diff --check` 通过。
- 合并后的完整测试套件已使用 Python 3.9 执行，30 项测试全部通过。
