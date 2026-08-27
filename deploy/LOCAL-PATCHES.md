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
- raid-loot（掉落）页无图标，仅文本链接，不受影响。
