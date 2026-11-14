---
name: mcp-auth
description: 为远程 MCP Server（Streamable HTTP）落地“应用自身同时充当 OAuth 授权服务器与受保护资源”的认证方案：RFC 9728 元数据发现、401 challenge、动态客户端注册（DCR）、Authorization Code + PKCE(S256)、复用现有 Web 登录做 consent、不透明 token 哈希落库、refresh 轮换与整族吊销、grant 撤销管理、独立的 MCP Bearer 安全链。适用于给 MCP 接入 OAuth、排查 MCP 客户端连接授权失败；业务工具级/对象级权限设计见 mcp-service-wrapper。
---

# MCP OAuth 认证（AS + RS 一体）

适用前提：应用已有用户体系与 Web session 登录，且没有可复用的身份平台。**若已有 IdP，优先对接 IdP，只实现资源服务器部分（第 2、7、8 步）**。本 skill 只解决“谁在调用”；工具与数据级授权、确认事务遵循 `mcp-service-wrapper`。

示例以 Spring Boot 3 + Spring Security + Spring AI MCP WebMVC 为主；其他技术栈按同一契约替换为等价组件。

## 端到端流程

```text
agent ──POST /mcp（无 token）───────────────────────► 401 WWW-Authenticate: Bearer resource_metadata="<base>/.well-known/oauth-protected-resource/mcp", scope="mcp:tools"
agent ──GET  /.well-known/oauth-protected-resource/mcp ─► resource / authorization_servers / scopes_supported
agent ──GET  /.well-known/oauth-authorization-server ──► authorize / token / register / revoke + S256
agent ──POST /oauth2/register（DCR，public client）─────► client_id
浏览器 ─GET  /oauth2/authorize?...state, resource, PKCE ─► 302 前端 consent 页（由前端编排登录 → 授权）
前端 ──GET  /oauth2/authorize（Accept: json）──────────► 未登录 401 / 已登录 consent 详情
前端 ──POST /oauth2/consent {decision} ────────────────► {redirect: <redirect_uri>?code=&state=}
agent ──POST /oauth2/token（code + code_verifier）──────► access（短期）+ refresh（可轮换）
agent ──POST /mcp  Authorization: Bearer <access> ─────► Bearer 过滤器 → 可信身份上下文 → 工具
用户  ──撤销授权 ─────────────────────────────────────► grant 与全部 token 吊销，下一次请求 401
```

端点路径为推荐命名，可按项目调整，但 metadata 中公布的 URL 必须与实际一致。

## 实施步骤

每步代码骨架见 [implementation.md](references/implementation.md)。

1. **配置与可信基址**：集中配置公共基址、MCP 路径、scope（如 `mcp:tools`）、code/access/refresh 有效期（参考 5 分钟 / 15 分钟 / 30 天）、DCR 限流、未用 client 过期。issuer、resource、metadata URL 全部由公共基址派生；启动时校验非空、HTTPS（仅 localhost 豁免）。**绝不用 Host / X-Forwarded-* 生成这些 URL。**
2. **发现 + 401 challenge**：发布 protected-resource metadata 与 authorization-server metadata；MCP 链的认证入口统一返回带 `resource_metadata`、`scope` 的 Bearer challenge。客户端依赖这个 401 自动进入 OAuth，不要用“登录工具”代替。
3. **数据模型**：client 注册、grant、authorization code、access token、refresh token 五张表。code/access/refresh 只存 SHA-256 哈希；token 关联 grant，grant 关联用户与 client。迁移走目标项目自身机制（见 `db-migration`）。
4. **DCR**：只接受 public client（`token_endpoint_auth_method=none`、grant 为 `authorization_code`/`refresh_token`、response 为 `code`），scope 强制为配置值。redirect URI：http 仅限 loopback，其他必须 https，自定义 scheme 走管理员可配置的白名单。同名且已注册回调覆盖本次值时复用 client（不改写已有回调），只对新建 client 计限流。
5. **授权 + consent**：授权端点先校验全部参数（client、`response_type=code`、redirect 精确匹配、scope、`resource` 等于规范化 MCP URL、state、`S256`），**任何失败返回 400，不向未验证 URI 重定向**。按 `Accept` 分流：浏览器导航一律 302 到前端 consent 页；前端 JSON 请求未登录返回 401 + 回跳地址，已登录返回 consent 详情。consent 提交需 session + 一次性授权事务（防 CSRF），重新校验全部参数，批准时创建 grant 并签发绑定 user/client/redirect/resource/challenge/grant 的单次 code，回调只带 `code` 与原 `state`。
6. **Token 端点**：`authorization_code` 校验未消费、未过期、client、redirect、resource、PKCE verifier（常量时间比较），**原子条件更新消费 code**，签发 token；`refresh_token` 单事务轮换，旧 refresh 再次出现即整族吊销并返回 `invalid_grant`；revoke 端点恒返回 200。响应加 `Cache-Control: no-store`。
7. **MCP 资源服务器链**：为 MCP 路径建独立、最高优先级、无 session 的安全链，关闭 CSRF/表单/Basic。Bearer 过滤器哈希查表 → 校验未吊销/未过期/grant 有效/用户启用/resource 完全匹配 → 有 scope 时授予 `SCOPE_<scope>` 权限，链上要求该权限；再按用户角色建立认证，让既有业务权限复用。过滤器只挂在该链上，禁止被 Servlet 容器全局注册。流式响应场景只对 REQUEST dispatch 做授权，避免 SSE 结束时的 ASYNC dispatch 报 “response already committed”。
8. **工具身份护栏**：统一装饰所有工具回调：剥离模型可控的身份字段、校验身份上下文已认证，否则拒绝。确认工具在请求线程同步执行（ThreadLocal 可见）；若改为异步/线程池，必须显式传递可信上下文并重新校验。
9. **授权管理与清理**：授权列表/撤销接口挂在 Web session 链，普通用户只看/撤自己的，管理员可看全部；展示 client 名、回调、scope、最近使用，**绝不展示 token**。定时任务禁用过期未用的动态 client、删除过期 code、清理过期/吊销 token，grant 保留做审计。
10. **客户端接入**：只需提供远程 MCP URL（`https://<host>/mcp`），客户端自动完成发现 → DCR → 浏览器授权。可由后端按环境下发 MCP URL，前端生成接入说明。

## 关键约束

- 各认证入口使用独立安全链且互不串用：MCP Bearer、开放 API token、OAuth 端点、Web session。MCP token 不能访问管理后台 API，Web cookie 不能访问 MCP 端点。
- 只在 metadata 中声明已实现的能力，不写未实现的 `jwks_uri`、`openid`、`client_secret_*`。
- token/code 不进入 URL（回调中的 code 除外）、日志、工具参数与返回值；日志只记录 grantId/clientId/userId。
- 用户禁用、grant 撤销要求已签发 access 在下一次请求立即失效——这是选择不透明 token + 查表而非自签 JWT 的主要理由；若改用 JWT，需要额外的吊销检查。

## 常见错误

实现时逐条规避，细节见 [implementation.md#常见错误](references/implementation.md#常见错误)：consent 只靠 OAuth state 防 CSRF；approve 与 token 兑换各建一次 grant；为兼容个别客户端放宽 token 兑换时的 redirect 校验；路径前缀匹配过宽；限流信任任意转发头；声明了 session 身份绑定却未在 transport 调用；scope 不足仍放行；引入未使用的 OAuth starter。

## 验证

按 [verification.md](references/verification.md) 跑最小用例集：发现与 401、DCR 校验、PKCE 失败、code 重放、refresh 重放整族吊销、resource 不匹配、撤销后 401、用户禁用后 401、跨链访问被拒，最后用真实 MCP 客户端端到端连接一次。
