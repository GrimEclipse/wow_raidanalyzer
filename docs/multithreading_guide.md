# 多线程使用指南


## 执行模型

当前多线程分为三层：

1. 服务端任务线程

   在线页面每次提交 `/api/analyze` 后，`server.py` 会创建一个后台线程执行分析任务。任务不会阻塞 HTTP 请求，前端通过 SSE 读取进度。

   真正同时运行的完整分析任务数量由 `WCL_MAX_JOB_THREADS` 控制，默认是 `1`。默认配置下，多个用户同时提交时会排队执行。

2. Fight 级线程池

   单个分析任务内部会用 `ThreadPoolExecutor` 并发分析多场 Fight。默认最多同时分析 `4` 场。

   目前已接入 Fight 级并发的插件：

   - `boss_plugins/march_on_queldanas/midnight_falls_core.py`
   - `boss_plugins/void_spire/crown_of_the_cosmos.py`
   - `boss_plugins/void_spire/lightblinded_vanguard.py`

3. WCL 请求级并发与限流

   插件拉取多种法术事件时，会并发请求 WCL API。所有请求统一走 `request_post()`，并通过信号量限制总并发请求数，默认最多 `6` 个请求同时进行。

   对 `429`、`500`、`502`、`503`、`504` 会自动重试。

## 配置项

所有配置都通过环境变量设置。

| 环境变量 | 默认值 | 作用 |
| --- | ---: | --- |
| `WCL_MAX_JOB_THREADS` | `1` | 同时运行的完整分析任务数 |
| `WCL_MAX_FIGHT_THREADS` | `4` | 单个分析任务内同时分析的 Fight 数 |
| `WCL_MAX_REQUEST_THREADS` | `6` | 同时请求 WCL API 的最大请求数 |
| `WCL_MAX_REQUEST_RETRIES` | `3` | WCL 请求最大重试次数 |
| `WCL_REQUEST_RETRY_BASE_SECONDS` | `0.8` | 重试退避基础秒数 |

配置值小于 `1` 时会自动按 `1` 处理；非整数值会回退到默认值。



## 相关代码

- `analyzer_core/concurrency.py`：线程池、请求信号量、重试逻辑。
- `server.py`：在线任务队列和任务级信号量。
- `boss_plugins/*`：插件内 Fight 并发和请求并发接入点。
