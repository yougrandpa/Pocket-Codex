# Pocket-Codex 安全与稳定性审计报告（黑盒 + 白盒）

审计时间：2026-03-02
目标：`http://127.0.0.1:3000`（Next.js）与后端 API（FastAPI，`http://127.0.0.1:8000`）

## Executive Summary

本次审计发现 10 项问题，其中：
- P0：1 项（可被未认证请求直接触发的资源耗尽链路）
- P1：5 项（鉴权会话设计、SSE 资源控制、输入边界等）
- P2：4 项（token 存储、边界最小化与稳定性改进）

重点风险集中在：**登录接口防刷缺失 + 审计日志无配额**、**刷新 token 可重放**、**输入无上限导致存储/内存增长**、**SSE 连接和回放缺少资源上限**。

---

## P0

### [P0-01] 未认证登录接口可高频写审计日志，导致存储 DoS
- 类别：鉴权、DoS/timeout
- 位置：
  - `backend/app/api/auth.py:144`（`_verify_credentials` 失败即写审计）
  - `backend/app/storage.py:81`（每次 `append_audit` 直接 `commit`）
  - `backend/app/api/auth.py:155`、`backend/app/api/auth.py:186`（`/auth/login`、`/auth/mobile/request` 都走该路径）
- 黑盒证据：
  - 200 次错误登录在约 0.24s 完成，`audit_logs` 行数同步增加 200（`delta=200`）。
- 影响：
  - 任何未认证来源都可持续写库，快速放大 SQLite 文件、占用 I/O，最终拖垮服务。
- 修复建议：
  1. 为 `POST /api/v1/auth/login` 与 `POST /api/v1/auth/mobile/request` 增加 **IP + username 维度限流**（漏桶/令牌桶）。
  2. 失败登录审计改为异步批量写入，且设置写入速率上限与采样。
  3. 增加账号锁定/指数退避（例如 5 次失败后冷却 1-5 分钟）。
  4. 审计日志表做 TTL/归档与体积告警。
- 影响范围：认证模块、数据库层、告警与运维容量。

---

## P1

### [P1-01] Refresh Token 可重放，且短时间内刷新得到相同 token
- 类别：鉴权、token 生命周期
- 位置：
  - `backend/app/api/auth.py:346`（`/auth/refresh` 不做旧 token 失效）
  - `backend/app/auth.py:35`、`backend/app/auth.py:16`（无 `jti`/nonce，按秒级时间戳签发）
- 黑盒证据：
  - 使用同一个 `refresh_token` 可重复调用 `/auth/refresh` 成功。
  - 连续刷新返回 `refresh1_eq_refresh2=True`（同秒签发同 token）。
- 影响：
  - 一旦 refresh token 泄露，可在有效期内反复换新 access token；难以实现会话吊销。
- 修复建议：
  1. 引入 `jti` + 服务端会话存储（Redis/DB），实施 **refresh token rotation**。
  2. 每次刷新使旧 refresh token 立刻失效；检测复用即封禁该会话链。
  3. 缩短 refresh TTL，并支持用户主动登出后全局吊销。
- 影响范围：鉴权服务、会话存储、前端刷新流程。

### [P1-02] 输入体缺乏上限，且响应回显原始大字段，易触发内存/磁盘放大
- 类别：输入校验、DoS/timeout
- 位置：
  - `backend/app/schemas.py:86`（`prompt` 仅 `min_length=1`）
  - `backend/app/schemas.py:122`（`message` 无 `max_length`）
  - `backend/app/schemas.py:135`（`detail` 无大小约束）
  - `backend/app/schemas.py:233`、`backend/app/schemas.py:273`（`TaskResponse` 回显完整 `prompt`）
- 黑盒证据：
  - 提交 2,000,000 字符 `prompt`，接口 0.04s 返回 201，响应体约 2,001,350 bytes。
  - 300KB `detail` 被成功写入审计日志，`detail_json_size`≈300,009。
- 影响：
  - 可快速放大带宽、DB 体积与内存占用；重启时还会把全部历史任务载入内存。
- 修复建议：
  1. 为 `prompt/message/detail` 增加明确上限（如 8KB/8KB/16KB）。
  2. 统一请求体大小限制（反向代理 + ASGI 应用双层）。
  3. `TaskResponse` 默认不回显完整 prompt，改为摘要/截断字段。
  4. 审计字段超长时截断并打标。
- 影响范围：任务创建、消息接口、审计接口、前端渲染。

### [P1-03] SSE 缺乏连接与订阅配额，回放读取成本高，易被会话滥用
- 类别：SSE、DoS/timeout
- 位置：
  - `backend/app/api/stream.py:37`（连接可长期保持）
  - `backend/app/services/task_service.py:560`（每连接分配队列并注册订阅）
  - `backend/app/services/task_service.py:592`（回放遍历全部任务事件后排序）
  - `backend/app/services/task_service.py:1714`（广播仅丢弃队列头，无全局配额）
- 黑盒证据：
  - 并发 20 条 SSE 连接均可成功建立（均返回 200）。
  - `last_event_id=0` 回放可返回 500 条事件（达配置上限）。
- 影响：
  - 被盗 token 可用于制造大量长连接、持续回放和广播压力，拖慢 worker 与主事件循环。
- 修复建议：
  1. 增加每用户/IP 的 SSE 并发连接上限与全局连接上限。
  2. 回放改为按 task_id + stream_id 索引查询，避免全量扫描排序。
  3. 增加服务器端连接生命周期和空闲策略（如 5-10 分钟重协商）。
- 影响范围：实时流服务、任务事件总线、前端实时体验。

### [P1-04] 移动授权“高风险”仅提示不强制，且令牌消费未绑定请求上下文
- 类别：移动授权风控、鉴权
- 位置：
  - `backend/app/services/mobile_auth_service.py:339`（能计算风险等级）
  - `backend/app/api/auth.py:246`（approve 未做风险门槛）
  - `backend/app/services/mobile_auth_service.py:195`（仅校验 `request_token`）
- 黑盒证据：
  - 伪造公网来源创建请求后，`risk_level=HIGH`，仍可直接 `approve` 成功（200）。
  - 在不同来源 IP 调用状态接口，仍可成功 `COMPLETED` 并下发 token。
- 影响：
  - 风控信号仅做展示，无法在服务端阻断高风险放行；request token 泄露后的滥用门槛偏低。
- 修复建议：
  1. 服务端对 `HIGH` 风险增加强制二次确认（额外 PIN/TOTP/短效签名）。
  2. 将 request token 绑定 `device_name + 首次请求 IP/UA`（允许小范围漂移策略）。
  3. 为 approve/reject 增加审批原因与高风险审计标签。
- 影响范围：移动登录流程、审批端 UI 与后端策略。

### [P1-05] 任务/事件无限保留，启动全量加载，长期运行后稳定性风险高
- 类别：DoS/timeout、稳定性
- 位置：
  - `backend/app/services/task_service.py:213`（启动即 `_load_persisted_tasks`）
  - `backend/app/services/task_service.py:217`（全量加载任务）
  - `backend/app/models.py`（Task 内含完整 events/messages）
- 黑盒/运行证据：
  - 当前库中 `task_count=190`，`max_prompt_len=2000000`。
- 影响：
  - 数据规模增长后，重启变慢、内存水位升高，SSE 回放和列表接口成本上升。
- 修复建议：
  1. 任务与事件分层存储：热数据内存、冷数据分页查询。
  2. 增加 retention（按天数/条数）和归档作业。
  3. `Task` 对象中限制 `events/messages` 最大保留窗口。
- 影响范围：存储层、任务查询、SSE 回放。

---

## P2

### [P2-01] 前端 token 存于 sessionStorage，且兼容读取 legacy localStorage
- 类别：token 存储
- 位置：`frontend/lib/api.ts:193`、`frontend/lib/api.ts:267`、`frontend/lib/api.ts:280`、`frontend/lib/api.ts:302`
- 影响：
  - 一旦前端发生 XSS，token 可直接被脚本读取；历史 localStorage 兼容路径增加暴露面。
- 修复建议：
  1. 优先改为 HttpOnly + SameSite Cookie 会话。
  2. 若必须 header token，改为内存态 + 短 TTL + 强刷新策略，禁用 localStorage 迁移读取。
- 影响范围：前端认证态、跨标签页行为、后端鉴权方式。

### [P2-02] 已认证 API 请求路径缺少统一超时控制
- 类别：DoS/timeout、稳定性
- 位置：`frontend/lib/api.ts:526`-`frontend/lib/api.ts:567`（`authorizedFetchJson` 直接 `fetch`，无 Abort 超时）
- 影响：
  - 后端慢响应或连接半开时，前端操作可能长时间挂起，影响可用性。
- 修复建议：
  1. 复用 `fetchJson` 的 AbortController 超时机制到 `authorizedFetchJson`。
  2. 按接口类型设置分级超时（读/写/流）。
- 影响范围：前端所有需要登录态的 API 调用。

### [P2-03] workdir 边界逻辑可阻断穿越，但默认授权范围过大且可被健康检查暴露
- 类别：workdir 边界
- 位置：
  - `backend/app/config.py:199`（默认白名单为项目根目录）
  - `backend/app/services/task_service.py:1003`（边界校验）
  - `backend/app/main.py:71`（`/healthz` 回显 `workdir_whitelist`）
- 黑盒证据：
  - `/tmp` 与符号链接逃逸均被拒绝（边界校验有效）。
  - `/healthz` 未认证返回白名单真实路径。
- 影响：
  - 边界虽有效，但最小权限不足；路径情报外泄会降低攻击成本。
- 修复建议：
  1. 生产环境改为最小化白名单（仅必要子目录）。
  2. `/healthz` 去敏（不返回路径、CLI 绝对位置等内部信息）。
- 影响范围：执行器安全边界、运维观测接口。

### [P2-04] CORS 对私网/.local 源放行较宽，未来若引入 cookie 会放大跨站风险
- 类别：鉴权（边界策略）
- 位置：`backend/app/main.py:17`、`backend/app/main.py:35`-`backend/app/main.py:41`
- 黑盒证据：
  - `Origin: http://evil.local` 预检返回 `Access-Control-Allow-Origin: http://evil.local`。
- 影响：
  - 当前主要使用 Bearer header，风险可控；但若后续迁移 Cookie，会显著扩大可被跨站调用面。
- 修复建议：
  1. 生产关闭 `allow_origin_regex`，仅保留显式白名单域名。
  2. 将本地开发 CORS 与生产 CORS 分离配置。
- 影响范围：跨域调用链路、未来认证迁移方案。

---

## 复现命令（节选）

```bash
# 1) 未授权访问任务接口
curl -i http://127.0.0.1:8000/api/v1/tasks

# 2) CORS 预检放行 .local
curl -i -X OPTIONS 'http://127.0.0.1:8000/api/v1/tasks' \
  -H 'Origin: http://evil.local' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: authorization,content-type'

# 3) SSE 回放（会返回大量事件）
curl -N -H "Authorization: Bearer <access_token>" \
  "http://127.0.0.1:8000/api/v1/stream?last_event_id=0"
```

---

## 修复优先级建议（7 天内）

1. 先处理 P0-01：给登录相关接口加限流 + 审计落盘治理。
2. 同步处理 P1-01/P1-02：refresh rotation 与输入上限。
3. 再处理 P1-03/P1-05：SSE 与任务保留策略的容量治理。
4. 最后收口 P2：token 存储、CORS、healthz 去敏、前端统一超时。
