# HTTP 鉴权与工具控权实施细则

## 身份流与权限交集

```text
HTTP Authorization: Bearer
  → 验证 token/issuer/audience/有效期/撤销状态
  → TrustedContext(subject, client, scopes, tenant, grant)
  → 检查工具所需 scope
  → 检查当前业务角色与动作权限
  → 检查目标对象归属/ACL/租户边界
  → Service 执行业务
```

有效权限是客户端获授 scope、用户当前业务权限和目标对象权限的交集。OAuth 授权客户端访问不等于把用户所有业务能力永久授予客户端。`mcp:tools` 可作为项目自定义入口 scope，但本身不表达 read/write/delete 的区别；是否拆成细粒度 scope 由业务和客户端需求决定，不假定协议有统一工具 scope 名称。

框架无关的授权边界：

```text
call(toolName, args, trustedContext):
  requireAuthenticatedMcpContext(trustedContext)
  policy = registeredToolPolicy(toolName)  // 未注册/无策略即拒绝
  requireScopes(trustedContext.scopes, policy.requiredScopes)
  target = resolveTargetWithinTenant(args, trustedContext.tenant)
  requireCurrentBusinessPermission(trustedContext.subject, policy.action, target)
  return policy.handler(validatedBusinessArgs(args), trustedContext)
```

`tenantId` 可以是待操作目标参数，但必须验证主体有权进入该租户，不能把它直接当可信租户上下文。批量操作必须覆盖每个对象；读权限变化也要生效。

## 认证入口

- 未提供/无效/过期 token 返回 401，并提供可发现的 Bearer challenge；scope 不足返回 403 `insufficient_scope`，直接终止调用。不要仅设置 authenticated 后指望下游自动拒绝。
- resource/audience 使用可信配置的对外 MCP URL；经代理部署时核对路径与尾斜杠的一致性。不要由任意 Host 或 X-Forwarded-* 生成 issuer/resource。
- 使用成熟资源服务器库验证 JWT 的签名、issuer、audience 和有效期；opaque token 通过可信 introspection 或哈希查表验证。不要只 decode JWT，也不要接受发给其他 API 的 token。
- 会话身份至少绑定 subject/client/tenant/resource；刷新令牌后允许同一身份正常续用，不能把绑定等同于 raw access token 不变。跨身份复用应拒绝。注册了一个断言函数不等于 transport 已调用它。
- 无会话入口必须排除 cookie/Basic 等意外回退；路由匹配与过滤器匹配一致。同步 ThreadLocal 假设需验证；异步任务需显式携带受信任上下文，并在执行时按业务策略重新授权。

## OAuth 流程选择

新业务优先对接已有身份平台。需要自建时，采用成熟 OAuth 实现，逐项确认下列契约：

1. 公布真实可用的 protected-resource metadata 和授权服务器发现信息；不要声明未实现的 OIDC、JWKS 或认证方式。
2. 客户端登记方式由协议版本和客户端能力决定，可预注册或使用所支持的发现/注册机制。DCR 不是所有 MCP 的必选项；启用时限制注册滥用、校验回调地址。
3. 授权码流程绑定用户、client、redirect URI、resource、scope 和 PKCE S256；授权码短期且原子单次消费。回调匹配按适用标准处理，不能以“有 PKCE”为理由任意放宽地址。
4. 授权页面使用已登录身份，展示客户端、目标资源和所申请权限。consent 写入需与登录 session 绑定的 CSRF 防护/一次性授权事务；任意非空 OAuth state 不能代替授权页面的 CSRF 验证。
5. access token 短期；refresh token 轮换须检查数据库原子消费结果。旧 refresh 重放后的整族撤销必须实际提交，不能因随后抛运行时异常而被事务回滚。
6. 授权撤销关联到真正签发 token 的 grant；验证撤销后已有 access/refresh 均不可继续使用。用户被禁用或业务权限下降的生效策略应明确并验证。
7. token 不进入 URL、工具输入、日志或返回的调试数据；opaque token 持久化保存哈希。对 token 响应配置禁止缓存。

## 工具与协议错误

认证失败在 HTTP 边界处理。通过认证后的业务拒绝，遵循当前 SDK 的 MCP 错误映射，必要时返回 `isError` 的工具结果；不要假定 Service 抛出的 HTTP 异常在 JSON-RPC/SSE 中仍保持同一 HTTP 状态。测试客户端实际收到的结果，避免把业务异常序列化为成功或泄露栈信息。

若使用 Streamable HTTP，按所选 SDK 检查 Origin、允许的 HTTP 方法、代理缓冲/超时、SSE 保活与取消。不能为了修复流式响应错误而关闭正常请求的鉴权。

## 规范依据

以下是编写时核对的版本；未来实施时重新核对目标客户端/SDK 所支持版本，不把本文件当作永久最新规范。

- [MCP Authorization，2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)：HTTP 资源服务器、发现、resource 绑定及 scope challenge；stdio 使用不同凭据方式。
- [RFC 9700 OAuth 安全最佳实践](https://www.rfc-editor.org/rfc/rfc9700.html)：回调 URI、PKCE、令牌约束和刷新令牌保护。

本文的 Service/ACL 复用、确认事务和业务测试要求是迁移设计指导，不声称均为 MCP 协议条款。
