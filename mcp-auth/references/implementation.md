# 实现骨架（Spring Boot 3 + Spring Security + Spring AI MCP WebMVC）

依赖：`spring-ai-starter-mcp-server-webmvc`（Streamable HTTP）、`spring-boot-starter-security`、持久层（如 JPA）。授权服务器与令牌逻辑可手写；若不使用 `spring-boot-starter-oauth2-authorization-server` / `oauth2-resource-server` 的能力，就不要引入它们。实施前核对所选 SDK 版本的配置键与 API。

类名、表名、路径均为示例，按目标项目命名规范替换。

## 1. 配置

```java
@ConfigurationProperties(prefix = "app.mcp.oauth")
public class McpOAuthProperties {
    private String publicBaseUrl;                 // https://<host>
    private String mcpEndpoint = "/mcp";
    private String scope = "mcp:tools";
    private Duration authorizationCodeValidity = Duration.ofMinutes(5);
    private Duration accessTokenValidity = Duration.ofMinutes(15);
    private Duration refreshTokenValidity = Duration.ofDays(30);
    private int dcrRateLimit = 10;
    private Duration dcrRateWindow = Duration.ofHours(1);
    private Duration unusedClientValidity = Duration.ofDays(30);

    public String issuer()      { return trimSlash(publicBaseUrl); }
    public String resourceUrl() { return issuer() + mcpEndpoint; }
    public String protectedResourceMetadataUrl() { return issuer() + "/.well-known/oauth-protected-resource" + mcpEndpoint; }

    @PostConstruct void validate() { /* 非空；https，仅 http + localhost 例外；mcpEndpoint 以 / 开头 */ }
}
```

部署时通过环境变量注入公共基址。经反向代理时，确认外部访问路径与 `resourceUrl()` 逐字一致（含尾斜杠）。

## 2. 发现与 challenge

```java
@GetMapping("/.well-known/oauth-protected-resource/mcp")
Map<String,Object> protectedResource() {
    return Map.of("resource", p.resourceUrl(),
                  "authorization_servers", List.of(p.issuer()),
                  "bearer_methods_supported", List.of("header"),
                  "scopes_supported", List.of(p.getScope()));
}

@GetMapping("/.well-known/oauth-authorization-server")
Map<String,Object> authorizationServer() {
    String i = p.issuer();
    return Map.of("issuer", i,
        "authorization_endpoint", i + "/oauth2/authorize",
        "token_endpoint",        i + "/oauth2/token",
        "registration_endpoint", i + "/oauth2/register",
        "revocation_endpoint",   i + "/oauth2/revoke",
        "response_types_supported", List.of("code"),
        "grant_types_supported", List.of("authorization_code", "refresh_token"),
        "token_endpoint_auth_methods_supported", List.of("none"),
        "code_challenge_methods_supported", List.of("S256"),
        "scopes_supported", List.of(p.getScope()));
}

// MCP 链的 AuthenticationEntryPoint
res.setStatus(401);
res.setHeader("WWW-Authenticate", "Bearer resource_metadata=\"" + p.protectedResourceMetadataUrl()
        + "\", error=\"invalid_token\", scope=\"" + p.getScope() + "\"");

// MCP 链的 AccessDeniedHandler（scope 不足）
res.setStatus(403);
res.setHeader("WWW-Authenticate", "Bearer error=\"insufficient_scope\", scope=\"" + p.getScope()
        + "\", resource_metadata=\"" + p.protectedResourceMetadataUrl() + "\"");
```

## 3. 数据模型要点

| 表 | 关键字段 |
|----|---------|
| oauth_client_registration | client_id（唯一）、client_name、redirect_uris、token_endpoint_auth_method、scope、dynamic、registered_from、disabled、last_used_at、expires_at |
| oauth_authorization_grant | user_id、client_id、registration_id、scope、resource_uri、revoked、revoked_at、revoke_reason、created_at、last_used_at |
| oauth_authorization_code | code_hash（唯一）、grant_id、user_id、client_id、redirect_uri、resource_uri、scope、code_challenge、expires_at、consumed、consumed_at |
| oauth_access_token | token_hash（唯一）、grant_id、subject、client_id、scope、resource_uri、expires_at、revoked、last_used_at |
| oauth_refresh_token | token_hash（唯一）、grant_id、client_id、expires_at、consumed、revoked |

凭据生成：`SecureRandom` 32 字节 → base64url 无填充；落库 `sha256Hex`。PKCE：`base64url(sha256(ascii(verifier))) == challenge`，常量时间比较。

原子消费（code 与 refresh 同理）：

```java
@Modifying
@Query("update OAuthAuthorizationCode c set c.consumed = true, c.consumedAt = :now where c.id = :id and c.consumed = false")
int consume(Long id, Instant now);   // 返回 0 即并发/重放 → invalid_grant
```

refresh 重放后的整族吊销必须真正提交：在独立事务（`REQUIRES_NEW`）中执行吊销，或先提交再返回错误，不要在同一事务里吊销后抛出运行时异常导致回滚。

## 4. redirect URI 规则

- 注册：http 仅 `localhost` / `127.0.0.1` / `[::1]`；其余必须 https；非 http(s) 的自定义 scheme（桌面 agent 回调）必须在管理员可配置的白名单内。
- 匹配：精确匹配，不做前缀匹配；loopback 按 RFC 8252 忽略端口，scheme/host/path/query 仍需一致。
- DCR 去重：按 `client_name` 查已启用的动态 client，若其已注册回调覆盖本次全部回调则复用，否则新建；不修改已有 client 的回调，防止冒名改写。

## 5. authorize 的 Accept 分流与 consent

```java
validateAll(params);   // 失败 400，不重定向
boolean browserNav = accept == null || accept.contains("text/html");
if (browserNav) return found(frontendBase + "/oauth/consent" + originalQuery);
if (currentUser == null) return status(401, Map.of("loginRequired", true, "authorizeUrl", consentUrl));
String txId = authTx.create(session, user, params);        // 一次性授权事务，绑定 session + 参数，短期有效
return ok(consentView(params, user, txId));                 // clientName、redirectUri、scope、resource、username、txId
```

consent 提交：

```java
@PostMapping("/oauth2/consent")   // 需 session
Map<String,Object> consent(@RequestBody ConsentRequest body) {
    var tx = authTx.consume(session, body.txId());          // 原子消费，参数以事务记录为准
    if (!body.approve()) return Map.of("redirect", errorRedirect(tx, "access_denied"));
    var grant = grants.create(user, tx);                    // grant 只在这里创建一次
    String code = codes.issue(grant, tx);                   // code 记录 grant_id
    return Map.of("redirect", tx.redirectUri() + "?code=" + enc(code) + "&state=" + enc(tx.state()));
}
```

前端 consent 页：带原 query 以 JSON 请求授权端点，401 跳登录页并携带返回地址；用户确认后提交 consent，拿到 `redirect` 后整页跳转回 agent 回调。前端基址来自可信配置，不取请求头。

## 6. Bearer 过滤器与安全链

```java
@Bean @Order(1)
SecurityFilterChain mcpChain(HttpSecurity http, McpBearerAuthFilter f, McpOAuthProperties p) throws Exception {
    return http.securityMatcher(p.getMcpEndpoint(), p.getMcpEndpoint() + "/**")
        .csrf(c -> c.disable())
        .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
        .formLogin(x -> x.disable()).httpBasic(x -> x.disable())
        .exceptionHandling(e -> e.authenticationEntryPoint(new McpBearerEntryPoint(p))
                                 .accessDeniedHandler(new McpInsufficientScopeHandler(p)))
        .authorizeHttpRequests(a -> a.shouldFilterAllDispatcherTypes(false)
                                     .anyRequest().hasAuthority("SCOPE_" + p.getScope()))
        .addFilterBefore(f, UsernamePasswordAuthenticationFilter.class)
        .build();
}

@Bean   // @Component 形式的 Filter 会被 Servlet 容器自动全局注册，需显式禁用
FilterRegistrationBean<McpBearerAuthFilter> disableGlobal(McpBearerAuthFilter f) {
    var r = new FilterRegistrationBean<>(f); r.setEnabled(false); return r;
}
```

过滤器核心：

```java
String raw = header.substring("Bearer ".length()).trim();
var ctx = tokenService.validateAccessToken(raw, props.resourceUrl()); // 哈希查表 + 吊销/过期/grant/用户启用/resource
if (ctx.isEmpty()) { SecurityContextHolder.clearContext(); chain.doFilter(req, res); return; } // → 401
List<GrantedAuthority> auths = new ArrayList<>(roleAuthorities(ctx.user()));
if (hasScope(ctx.token().getScope(), props.getScope())) auths.add(new SimpleGrantedAuthority("SCOPE_" + props.getScope()));
var auth = new UsernamePasswordAuthenticationToken(ctx.user().getUsername(), null, auths);
SecurityContextHolder.getContext().setAuthentication(auth);   // 无 scope → 链上 403 insufficient_scope
chain.doFilter(req, res);
```

路径判断与 `securityMatcher` 保持一致：`path.equals(mcp) || path.startsWith(mcp + "/")`。

## 7. 工具身份护栏

```java
@Bean
ToolCallbackProvider mcpTools(BusinessTools tools) {
    var delegate = MethodToolCallbackProvider.builder().toolObjects(tools).build();
    return () -> Arrays.stream(delegate.getToolCallbacks()).map(this::guard).toArray(ToolCallback[]::new);
}
// guard.call(input): 删除输入 JSON 中的身份类字段 → 校验 SecurityContext 已认证且非匿名 → delegate.call
```

工具内部从安全上下文取当前用户，再走既有 Service 的权限判断；工具参数里不得出现 userId/token 等身份字段。

若 transport 使用 `Mcp-Session-Id` 复用会话：会话建立时记录 subject + client，后续每个请求比对；不一致直接拒绝。

## 常见错误

1. **consent CSRF 只靠 state**：关闭 OAuth 端点 CSRF 后仅依赖 OAuth `state` 与 session，无法防止跨站提交 consent。必须使用绑定 session 与请求参数的一次性授权事务（见第 5 节），Cookie 设 `SameSite=Lax` 或更严。
2. **重复 grant**：批准时建一个 grant、兑换 code 时再建一个，导致授权列表重复、撤销不彻底。grant 只在批准时创建，code 记录 `grant_id`，兑换时复用。
3. **放宽 token 兑换的 redirect 校验**：为兼容个别客户端而允许 token 请求的 `redirect_uri` 与 code 绑定值不同。标准要求一致；确需兼容时限定到具体 client 并告警，不要对所有动态 client 放开。
4. **路径匹配过宽**：`startsWith("/mcp")` 会误匹配 `/mcpxxx`。
5. **限流信任转发头**：直接取 `X-Forwarded-For` 第一段可被伪造绕过 DCR 限流；只信任已知代理设置的值。
6. **声明了 session 身份绑定却没接入 transport**：写了断言函数不等于每次请求都调用了它，必须有测试证明跨身份复用被拒。
7. **scope 不足仍放行**：过滤器在 scope 缺失时仍建立认证、链上只要求 `authenticated()`，403 分支形同虚设。用 `SCOPE_*` 权限控制。
8. **metadata 虚报能力**：声明未实现的 `jwks_uri`、`openid`、`client_secret_post`，会让客户端走错流程。
9. **依赖冗余**：引入 OAuth starter 却不用，可能自动装配额外过滤器链或默认端点，造成冲突。
