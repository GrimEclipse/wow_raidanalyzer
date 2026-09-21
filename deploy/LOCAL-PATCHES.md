# 本机对 wow_raidanalyzer 的本地补丁（2026-07-31）

> **状态：已被上游吸收（2026-08-02）**。上游 `ee3fea4 feat: integrate auth fixes and
> phase-aware raid tools` 已用自家实现整合了两项功能：邀请码走
> `environment_setting("APP_INVITE_CODE")`（语义与本补丁 A 一致：留空=开放注册、
> `hmac.compare_digest` 定长比较、先限流后校验），account.html 也已是
> `const form=event.currentTarget` 修复版（minified 写法）。
> 本机 main 已于 2026-08-02 快进同步到 `7f65014`，**当前工作树零本地代码补丁**，
> 以下内容仅作历史记录保留。本地补丁分支 `fix/currenttarget-bug-and-invite-code`
> 已过时（fork 远端仍保留，如不需要可删）。

两个改动，均**未提交到上游 GitHub**。若上游后来自己实现/修复了同样的东西，
`git pull` 会冲突——届时优先采用上游版本，删掉本补丁对应部分。

- 补丁 A：注册邀请码（本机需求，上游没有此功能）
- 补丁 B：account 页 `currentTarget` 空引用修复（**上游 bug，建议回推上游**）

---

# 补丁 A：注册邀请码

## 背景

移除 nginx Basic Auth 后，`/api/auth/register` 变成对全互联网开放的自助注册
（实测不带凭据 POST 返回 201）。用户要求加邀请码 `papawind`，无正确邀请码不得注册。

## 改动

### 1. `server.py`

- 顶部 import 增加 `hmac`、`os`（原文件两者都未导入）
- 模块级常量：
  ```python
  INVITE_CODE = str(os.getenv("APP_INVITE_CODE") or "").strip()
  ```
- `handle_register()` 在读取 body 之后、`AUTH.create_user()` 之前插入校验：
  ```python
  if INVITE_CODE:
      supplied = str(payload.get("inviteCode") or payload.get("invite_code") or "").strip()
      if not supplied:
          return self.json_error("请填写邀请码。", HTTPStatus.FORBIDDEN)
      if not hmac.compare_digest(supplied, INVITE_CODE):
          return self.json_error("邀请码不正确。", HTTPStatus.FORBIDDEN)
  ```

设计取舍：

- **邀请码不写死在代码里**，读 `APP_INVITE_CODE` 环境变量（经 unit 的 `EnvironmentFile=.env` 注入）。
  改码只需改 `.env` + `systemctl restart`，不动代码，也不会把码提交进 git。
- `INVITE_CODE` 为空时**不校验**，行为退回开放注册——这样上游用户 clone 下来不受影响。
- 用 `hmac.compare_digest` 而非 `==`：定长比较，不因前缀匹配长度不同而泄露时序信息。
  已实测前缀 `papa` 同样返回 403。
- 同时接受 `inviteCode` 和 `invite_code` 两种字段名，前端/脚本都好接。
- 放在限流计数**之后**：错误邀请码同样消耗该 IP 的 5 次/小时配额，避免被拿来暴力猜码。

### 2. `frontend/auth/login.html`

注册表单加一个 `required` 的邀请码输入框（`name="inviteCode"`，`autocomplete="off"`），
并把 hint 文案改成同时说明密码规则和邀请码要求。

### 3. `.env`

```
APP_INVITE_CODE=papawind
```

`.env` 在 `.gitignore` 里，邀请码不会进版本库。

## 验收（公网实测，全部不带任何其它凭据）

| 请求 | 结果 |
|---|---|
| 无 `inviteCode` | 403 `请填写邀请码。` |
| `inviteCode=wrongcode` | 403 `邀请码不正确。` |
| `inviteCode=PapaWind`（大小写不符） | 403 |
| `inviteCode=papa`（前缀） | 403 |
| `inviteCode=papawind` | **201** 建号成功 |
| 同 IP 第 6 次 | 429 `注册次数过多` |
| `/login` 页面 | 已渲染 `name="inviteCode" ... required` |
| `admin` 登录 | 仍 200，未受影响 |

测试账号 `probe_*` 均已从 `auth.db` 删除，库内现仅 `admin`。

---

# 补丁 B：`frontend/auth/account.html` 的 `currentTarget` 空引用（上游 bug）

## 症状

在 `/account` 保存 WCL 凭据后，页面报
`Cannot read properties of null (reading 'reset')`，
且「我的 WCL 凭据」区域仍显示「尚未配置」，看起来像保存失败。

## 真实原因：凭据其实保存成功了

`event.currentTarget` **只在事件派发期间有值**，事件回调返回后浏览器会把它置为 `null`。
原代码：

```js
onsubmit = async event => {
  await api(...);                    // ← await 让回调先返回，派发结束
  event.currentTarget.reset();       // ← 此时 currentTarget 已是 null → TypeError
  await load();                      // ← 永远执行不到
}
```

所以 `api()` 的 PUT 已经成功（实测 `HTTP 200 {"ok":true,"wcl":{"configured":true,...}}`），
只是 `reset()` 抛错打断了后面的 `load()`，UI 没刷新，`#wclState` 还停在初次加载时的
「尚未配置」。是**纯前端显示 bug，不是保存失败**。

## 修复

在 `await` 之前把引用存进局部变量。`#wclForm` 和 `#passwordForm` 两处同样的写法都改了：

```js
onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;   // ← 派发期间取好
  await api(...);
  form.reset();
  await load();
}
```

（另一个等价写法是用 `event.target`，但表单提交事件里 `target` 就是 form，
用局部变量更明确、也不依赖事件类型。）

## 验收

```
GET /api/auth/me → {"wcl":{"configured":true,"clientIdHint":"a22d…9c92"}}
PUT /api/auth/wcl-credentials → 200 {"ok":true,...}
服务器吐出的 /account 已含 `const form=event.currentTarget` ×2
用账号内加密存的那份凭据打 WCL oauth → 200 token_ok（解密链路完整）
auth/master.key 已生成（600），Fernet 加解密正常
```

**这个 bug 在上游也存在，建议在你本地仓库同样修掉并提交**，
这样以后 `git pull` 不会因为这两行产生冲突。

---

# 回滚

```bash
BK=/root/backups/wow-invite-code-20260731T202114
cp $BK/server.py   /opt/wow_raidanalyzer/
cp $BK/login.html  /opt/wow_raidanalyzer/frontend/auth/
# 仅临时关闭邀请码校验：把 .env 里 APP_INVITE_CODE 置空
systemctl restart wow-raidanalyzer
```

补丁 B 是纯修 bug，没有回滚必要；真要退回原样就把两处 `const form=` 改回
`event.currentTarget`（会重新引入上述报错）。



---

# 补丁 C：wowhead 图标/tooltip 全链路本地化中转（2026-08-14）

## 背景

国内用户（含机主）访问 `https://wow.wuwoapp.com/raid-guide` 时，技能图标依赖三个墙外资源，
不开 VPN 只能看到 fallback `?`：
1. `https://wow.zamimg.com/js/tooltips.js`（渲染脚本，被墙）
2. `https://www.wowhead.com/tooltip/...` / `https://nether.wowhead.com/tooltip/...`（技能数据 API，被墙）
3. `https://wow.zamimg.com/images/wow/icons/...`（图标图片，被墙）

服务器（美国机房）直连三者均 200，故采用「服务器中转 + 本地缓存」：浏览器只访问 wow.wuwoapp.com，
由服务器回源 wowhead。用户零 VPN 看图标。

## 改动

### 1. `frontend/tools/raid-guide/index.html`
`<script src="https://wow.zamimg.com/js/tooltips.js">` → `<script src="assets/vendor/wow-tooltips.js">`
（本地化脚本，base href=../../../ 解析到站点根 assets/vendor/）。

### 2. `assets/vendor/wow-tooltips.js`（新增，198KB）
原版 `wow.zamimg.com/js/tooltips.js`，**直接替换文件内两处定义**（不是末尾追加！）：
- `this.STATIC_URL="https://wow.zamimg.com"` → `this.STATIC_URL="/zamimg"`（图标/universal.css/fonts 全部静态资源）
- `function Se(e){...390字符...}` 整体替换为 `function Se(e){return"/wowhead-tooltip"}`（tooltip 数据 API 与 scaling 数据）
  替换用括号匹配（函数体 `{` 算 depth=1，需处理字符串/正则内的括号），替换后 `node --check` 验证。
⚠ 三个坑（2026-08-14 实测）：
1. **末尾追加覆盖补丁无效**：`window.Se=...` 覆盖不到调用点使用的 Se（压缩 JS 作用域问题），
   `WH.STATIC_URL` 同样——浏览器仍直连 nether.wowhead.com/wow.zamimg.com，国内用户图标全部"正在载入"。
   **必须直接改文件内部定义**。
2. sed 只替换函数开头会留下 `var t` 游离代码 → `Identifier 't' has already been declared`，node --check 可验证。
3. 新版 tooltips.js 的 `Se()` 对第三方站返回 `https://<sub>.wowhead.com`（实测请求落 nether），
   所以 tooltip API 反代目标选 **nether.wowhead.com**。
**升级 tooltips.js 时务必重跑此补丁**（上游 git pull 不涉及此文件，但手动更新时注意）。

### 3. nginx（`/etc/nginx/conf.d/wow-cache.conf` + `sites-available/wow-wuwo.conf`，副本在本目录）
- `proxy_cache_path`：`wow_static`（2g/90d，图标长缓存）+ `wow_api`（500m/14d，API 短缓存）
- `location /zamimg/` → `https://wow.zamimg.com/`（30d 缓存）
  - **sub_filter**（2026-08-14 追加）：`url(/images/` → `url(/zamimg/images/`（含单双引号变体，`sub_filter_once off`）。
    universal.css 里 `.wowhead-tooltip td/th` 背景是绝对路径 `url(/images/wow/tooltip.png)`，
    经本站加载会解析到本站根 → 404 → tooltip 透明无遮罩；改写后走中转，tooltip 恢复深色背景。
- `location /wowhead-tooltip/` → `https://nether.wowhead.com/`（24h 缓存）
  ⚠ tooltip API 端点必须用 **nether.wowhead.com**（www.wowhead.com/tooltip/ 返回 404 法语页面）
- ⚠ 两处都要 `proxy_ssl_server_name on;`——上游是 AWS CloudFront，不发 SNI 直接 SSL handshake failure(40)

## 验收（2026-08-14 headless Chrome 实测）
- 111/111 技能图标加载成功，URL 全部为 `/zamimg/images/wow/icons/small/...`（本站路径）
- fallback `?` 全部隐藏；page errors: none；blocked requests: none
- tooltip API `/wowhead-tooltip/tooltip/spell/1284103` → 200 JSON（含图标名）
- scaling `/wowhead-tooltip/data/item-scaling` → 200（1.1MB）
- 二次请求 `X-Cache-Status: HIT`（缓存生效）
- 本地化 JS 经应用 `/assets/vendor/wow-tooltips.js`（登录态）200、node --check 语法 OK

## 遗留
- raid-guide 页技能名/物品名是**文本链接**（`wowhead.com/cn/spell=...`），点击跳转 wowhead 详情页仍需 VPN
  （图标已本地化；详情页代理成本高，未做）。
- raid-calendar（团本日历与掉落）页无图标，仅文本链接，不受影响。

---

# 补丁 D：wowhead 中转 CSS 的 sub_filter 静默失效 → tooltip 又变透明无遮罩（2026-09-13）

## 症状（机主报「tooltip 缺少遮罩导致文字互相覆盖」）

hover 技能名弹出的 wowhead tooltip 没有深色底图，页面里的表格文字 / 行分隔线从 tooltip 底下透出来，
两组文字叠在一起。

## 根因链（全部 HTTP 回读实证）

1. tooltips.js 给 tooltip 的皮肤只定义了**图片背景**：universal.css 里
   `.wowhead-tooltip td,.wowhead-tooltip th{background:url("/images/wow/tooltip.png")}` —— 绝对路径。
2. 这份 CSS 由本地化脚本按 `WH.STATIC_URL="/zamimg"` 从 `/zamimg/css/universal.css?20` 取；
   nginx `/zamimg/` 的 sub_filter 本该把 `url(/images/` 改写成 `url(/zamimg/images/`。
3. **2026-08-24 16:34 起，nginx 缓存里那份 universal.css 存的是 gzip 压缩体**（CloudFront 对 CSS 自动压缩），
   而 **sub_filter 只能改写明文响应，遇到 gzip 二进制直接静默跳过** → 下发的 CSS 里 46 处
   `url(/images/...)` 一处都没被改写（实测改写 0 处，响应 `content-encoding: gzip`）。
4. 浏览器于是按本站根解析 `/images/wow/tooltip.png` → 落到应用上 → 303/404 → 皮肤图取不到 → tooltip 透明。
5. **为什么 08-14 修好、08-24 又坏、09-13 才被发现**：08-14 验证后浏览器把改写好的 CSS 缓存 30 天
   （`expires 30d`），正好 **09-13 到期**；用户再拉一次就吃到 nginx 缓存里那份坏的，于是「又出现」。

## 改动（线上权威配置 `/etc/nginx/sites-available/wow-wuwo.conf`；sites-enabled 是它的软链）

`location /zamimg/` 内新增一行（关键）：

```nginx
proxy_set_header Accept-Encoding "";
```

回源不带编码协商 → CloudFront 返回明文 CSS → sub_filter 生效。

另新增兜底 location（浏览器里已缓存 30 天的旧 CSS 仍会去请求 `/images/...`）：

```nginx
location /images/ {
    proxy_pass https://wow.zamimg.com/images/;
    proxy_http_version 1.1;
    proxy_ssl_server_name on;
    proxy_set_header Host wow.zamimg.com;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_ignore_headers Cache-Control Expires Set-Cookie Vary;
    proxy_hide_header Set-Cookie;
    proxy_cache wow_static;
    proxy_cache_valid 200 30d;
    proxy_cache_key $host$uri;
    add_header X-Cache-Status $upstream_cache_status always;
    expires 30d;
    proxy_read_timeout 30s;
}
```

应用自身没有 `/images/` 路由（`handle_static` 只放行 `/assets/`、`/frontend/`、`/data/`），不会误伤。

同时删掉缓存里那份坏的 CSS：`rm -f /var/cache/nginx/wow_static/a/b9/48139171906d6c2c1f1ded7dcd4b3b9a`
（cache key = `wow.wuwoapp.com/zamimg/css/universal.css` 的 md5）。

备份：`/root/backups/wow-nginx-20260913T182129/wow-wuwo.conf`（改前原件）。

## 验收（2026-09-13 实测）

- `/zamimg/css/universal.css?20`：46 处 `url(/zamimg/`、0 处裸 `url(/images/`；二次请求
  `X-Cache-Status: HIT` 仍是改写版（缓存里存的已经是明文）。
- `.wowhead-tooltip td` 的 computed `background-image` =
  `url("https://wow.wuwoapp.com/zamimg/images/wow/tooltip.png")`，该 URL 直回 200 `image/png` 6051B。
- 无头 Chrome（playwright + chromium_headless_shell-1234）实拍 A/B：正常态 tooltip 深色底不透明、
  文字清晰；把 `tooltip.png` 请求 abort 掉（复现旧故障）后，页面表格文字与行线从 tooltip 底下透出
  —— 与机主描述一致，修复后消失。截图：`/tmp/wowprobe/crop_{with,no}_skin.png`。

## ⚠ 以后升级 / 排查注意

- 动 `/zamimg/` 的缓存或 sub_filter 时**必须回读 CSS 内容确认改写真的生效**，只看 HTTP 200 会漏。
- 上游 `wow-tooltips.js` 升级后要重跑 08-14 那套本地化补丁（`STATIC_URL` / `Se()` 两处替换）。
- 本目录的 `deploy/nginx-wow-wuwo.conf` 是**上游模板**（还停在 07-31 的 127.0.0.1:8444 版），
  不是线上配置；线上权威 = `/etc/nginx/sites-available/wow-wuwo.conf`。

---

# 补丁 E：斯索拉克机制脚本的前端缓存版本号（2026-09-18）

## 症状

上游 `e89f782 fix(sszorak): audit tactical fury checkpoints` 改了
`frontend/report/plugins/venomous_abyss/sszorak/mechanics.js`（毒蛇之怒面板从「怒满时未进印记」
改成「战术集合点」，新增轮次 / 战术板时间 / Combo 漂移列），但**没有动引用它的
`progression/report.html`**：`<script src="…/sszorak/mechanics.js?v=20260912">` 仍是 09-12 那版。

## 根因

本项目的静态资源没有内容哈希，靠 URL 上的 `?v=` 做缓存失效。版本号不升 = 浏览器（和任何中间缓存）
继续用旧脚本渲染新数据：后端已经产出 `checkCount` / `round` / `plannedTime` / `comboDriftMs`，
页面却还是旧标题与旧字段，机主会以为「同步没生效」。

## 改动

`frontend/report/plugins/venomous_abyss/progression/report.html`：

```text
- <script src="frontend/report/plugins/venomous_abyss/sszorak/mechanics.js?v=20260912">
+ <script src="frontend/report/plugins/venomous_abyss/sszorak/mechanics.js?v=20260918">
```

纯缓存失效，不改任何逻辑；上游下次自己升版本号时以较大者为准（本补丁可删）。

## 验收（2026-09-18 实测）

- 回环 `GET /frontend/report/plugins/venomous_abyss/progression/report.html`（带登录 cookie）
  回读含 `mechanics.js?v=20260918`。
- 无头 Chrome 打开斯索拉克报告页：面板标题为「毒蛇之怒 · 战术集合点」，
  计数行显示「已检查 N 个集合点 · 实际怒不可遏 M 次 · 豁免 K 次」，控制台无报错。

## ⚠ 以后升级 / 排查注意

- **上游改 `frontend/**/*.js` 而没升 `report.html` 里的 `?v=` 时，必须自己升一次**，
  否则「同步了但页面没变」。判据是回读线上 HTML 的版本串，不是看文件时间。
- 同类历史坑：`assets/vendor/zone54-raid-guide-data.js?v=N`（手册数据，2026-09-12/09-14 踩过两次）。

## 后续（2026-09-20，上游 709e46a 同步时）

上游从这版起**自己也会升 `report.html` 的脚本清单**（新增 `twinfangs/mechanics.js?v=20260920-death-names`、
`report.js?v=1.3.7-20260912 → ?v=20260920`、`overview.js?v=20260920-health-colors`），与补丁 E 改的
`sszorak/mechanics.js?v=20260918` 在**同一行**，于是每次同步必冲突。

**解决方式（已实测两次：分支 + main 镜像）**：整行取上游版，然后把 `sszorak/mechanics.js` 的版本串改回
`20260918`（或当天日期）。判据是合并后回读线上 HTML，四个版本串都要对；只看「合并成功」会漏。
上游哪天自己升了 sszorak 那一串，本补丁即可删除。

## 后续（2026-09-20 晚，上游 78663b0 + e0ea3d1 同步时）

本次上游同样自带 `report.html` 脚本清单升级（`twinfangs/mechanics.js?v=20260920-venom-rounds`、
新增 `twinfangs/mechanics.css?v=20260920-venom-rounds`、`report.js?v=20260920`），冲突行与上轮相同，
按同一方式解决：整行取上游 + sszorak 保留 `?v=20260918`。两分支 `report.html` 已核对完全一致、
冲突标记清零。⚠ 这次解决时手工替换把一行 `=======` 残留进了 main，靠「逐文件 grep 冲突标记」
抓到并单独提交修复（`11ddf82` / `b9d169f`）——**合并后除了 diff 还要 grep 三种标记**。

## 后续（2026-09-21，上游 73a10a5 同步时）

`fix: refine raid night reviews and report library access`（50 文件，含后端 5 插件 + server.py + config/wcl_paths）：
- `report.html` 冲突照旧整行取上游 + sszorak 保留 `?v=20260918`；上游这轮自升
  `report-plugin-runtime.js?v=20260921-recent-reports`、`twinfangs/mechanics.js?v=20260921-generic-immunity`。
- **新冲突点**：`frontend/tools/mythic-dungeon/app.js` 的 S2 `skillSelection` 提示文案与上游改写的
  season-notice 逻辑撞在同一函数——本地 S2 试点是超集，**保留本地版**，上游文案改动不取。
- ⚠ `server.py` 这轮给 `/api/data-files`、`/api/data/list` 加了 `canModify` 编辑权限校验：
  未登录/只读账号调用会拿 403「需要编辑权限才能检索服务器报告」。本机 admin 是 admin 角色不受影响，
  但**任何用只读账号拉数据文件列表的脚本/外部工具从这版起会 403**。
- 合并后 grep 三种冲突标记照旧抓到 `report.html` 一行 `=======` 残留（同样只在 main 侧出现），
  已单独提交修净（`00121b9` / `24e5453`）。
