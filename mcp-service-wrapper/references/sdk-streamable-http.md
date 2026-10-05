# MCP SDK + Streamable HTTP 实施方法

## 选择 SDK 并固定版本

使用 MCP SDK 或其框架集成处理 initialize、能力协商、tools/list、tools/call、JSON-RPC、会话和流式响应，不自行编写一套 MCP 协议 Controller。

| 现有技术栈 | 接入方式 |
|---|---|
| Spring MVC | Spring AI MCP WebMVC starter，底层使用 Java MCP SDK |
| Spring WebFlux | Spring AI MCP WebFlux starter，使用 Reactor 上下文传递身份 |
| 普通 Java | 官方 Java MCP SDK，配置 HTTP transport provider 与工具 specification |
| Python | 官方 `mcp` SDK，按所锁定主版本注册工具并启用 Streamable HTTP |
| TypeScript/其他 | 对应官方 SDK 的 server、工具注册和 Streamable HTTP transport，沿用业务运行时 |

先检查项目依赖与 SDK 对应版本文档，再锁定兼容版本。下文 Java 示例使用 Spring AI 1.1.x 的 `@Tool + ToolCallbackProvider` 接口，不强制升级其他项目，也不要与不同主版本的注解扫描接口混用。示例里的 `OrderService`、`BusinessAuthorization`、`McpIdentity` 是需要对接目标业务的接口，不是 SDK 自带类。

## Spring MVC：依赖、端点、工具注册

在现有 Maven 工程加入依赖，用兼容的 `spring-ai-bom` 管理版本。`spring-ai.version` 必须设置为与项目 Spring Boot 版本兼容的具体正式版本。

```xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.springframework.ai</groupId>
      <artifactId>spring-ai-bom</artifactId>
      <version>${spring-ai.version}</version>
      <type>pom</type>
      <scope>import</scope>
    </dependency>
  </dependencies>
</dependencyManagement>
```

加入 `org.springframework.ai:spring-ai-starter-mcp-server-webmvc` 和 `org.springframework.boot:spring-boot-starter-oauth2-resource-server`。已有 BOM/依赖则合并，不重复创建。只有自己承担 OAuth 授权服务器职责时才增加 authorization-server 依赖。

```yaml
spring:
  ai:
    mcp:
      server:
        name: business-mcp
        version: 1.0.0
        protocol: STREAMABLE
        type: SYNC
        streamable-http:
          mcp-endpoint: /mcp
```

`server.version` 是服务信息，不是依赖版本。`SYNC` 不保证所有 SDK 版本的工具都在 Servlet 请求线程执行，必须验证身份传播。`STREAMABLE` 使用单一 MCP 入口；不要配置成旧 SSE 的消息/事件双端点。

```java
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.stereotype.Component;

@Component
class OrderTools {
    private final OrderService orders;
    private final BusinessAuthorization authorization;
    private final McpIdentity identity;

    OrderTools(OrderService orders, BusinessAuthorization authorization,
               McpIdentity identity) {
        this.orders = orders;
        this.authorization = authorization;
        this.identity = identity;
    }

    @Tool(name = "get_order", description = "查询当前用户有权查看的订单详情")
    public OrderView getOrder(@ToolParam(description = "订单 ID") String orderId) {
        var actor = identity.requireActor();
        authorization.requireScope(actor, "orders:read");
        // 此方法须检查当前用户状态、租户、订单 ACL 和读取动作权限。
        authorization.requireOrderRead(actor, orderId);
        return orders.getView(actor.tenantId(), orderId);
    }
}

@Configuration
class McpToolsConfiguration {
    @Bean
    ToolCallbackProvider businessTools(OrderTools tools) {
        return MethodToolCallbackProvider.builder().toolObjects(tools).build();
    }
}
```

`OrderView` 是只含允许字段的 DTO。`McpIdentity` 从验证后的请求上下文构造 actor，不从工具参数读取身份。`getView` 查询仍携带可信租户约束。新增编辑工具时注册独立的动作策略和写 scope，而不是复用读取检查。

需要集中控权时，装饰注册出的每个 `ToolCallback`：保留 definition/metadata，覆盖两个 `call` 重载，按工具名查策略后再调用 delegate；未知工具策略拒绝。对象权限仍在能解析业务对象的共享授权层执行。不要另注册一份未经装饰的相同工具。

## Spring Security：Bearer 认证与入口 scope

以下为 JWT 资源服务器配置骨架，使用 Spring Security 对 token 验签并检查 issuer/有效期。配置 audience validator，不能只靠 issuer-uri。

```java
@Bean
JwtDecoder mcpJwtDecoder(
        @Value("${app.mcp.issuer}") String issuer,
        @Value("${app.mcp.resource}") String resource) {
    NimbusJwtDecoder decoder = JwtDecoders.fromIssuerLocation(issuer);
    OAuth2TokenValidator<Jwt> audience = jwt ->
        jwt.getAudience().contains(resource)
            ? OAuth2TokenValidatorResult.success()
            : OAuth2TokenValidatorResult.failure(new OAuth2Error("invalid_token"));
    decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
        JwtValidators.createDefaultWithIssuer(issuer), audience));
    return decoder;
}

@Bean
@Order(1)
SecurityFilterChain mcpSecurity(HttpSecurity http, JwtDecoder mcpJwtDecoder)
        throws Exception {
    http.securityMatcher("/mcp", "/mcp/**")
        .csrf(csrf -> csrf.disable())
        .sessionManagement(sm -> sm.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
        .securityContext(sc -> sc.securityContextRepository(new NullSecurityContextRepository()))
        .requestCache(cache -> cache.disable())
        .formLogin(form -> form.disable())
        .httpBasic(basic -> basic.disable())
        .authorizeHttpRequests(auth -> auth.anyRequest().hasAuthority("SCOPE_mcp:tools"))
        .oauth2ResourceServer(oauth -> oauth.jwt(jwt -> jwt.decoder(mcpJwtDecoder)));
    return http.build();
}
```

导入分别来自 `org.springframework.security.oauth2.jwt`、`org.springframework.security.oauth2.core`、`org.springframework.security.web`、`org.springframework.security.web.context`、`org.springframework.security.config.http` 和框架配置包。与现有多安全链合并时调整 order，确保其他路由仍匹配原链。

此例约定每个 token 有入口 scope `mcp:tools`，工具再要求 `orders:read` 等业务 scope；授权端也必须支持该约定。入口不设统一 scope 的设计可改为 authenticated，但仍需对每个工具强制 scope 检查。默认 scope authority 不等于业务角色，不能把 scope 自动映射成 ADMIN。

补齐以下集成点后才形成完整认证实现：

1. 包装 Bearer entry point，401 的 `WWW-Authenticate` 添加可信配置的 `resource_metadata`；保留标准 Bearer 错误行为。入口 scope 不足必须走 403 `insufficient_scope`，不要吞掉异常继续执行。
2. 开放 `GET /.well-known/oauth-protected-resource/mcp`，返回 `resource`、`authorization_servers`、`scopes_supported`；授权服务器负责发布自己的发现信息。此元数据路由在其他链中明确放行。
3. 从通过校验的 JWT/introspection 结果取 subject/client/scopes，再查本地用户映射和当前租户权限。JWT claim 名称按身份平台契约确定；不自动信任任何自定义 claim。
4. 若使用 opaque token，把 JWT decoder 改为可信 introspector；验证其 active、audience、scope 和身份映射。不要同时启用一个宽松的备用认证入口。
5. JWT 撤销按业务时效要求配置短有效期、撤销状态查询或其他可靠机制；验签成功本身不表示 grant 未撤销。

## 上下文传递的方法

同步请求可从 `SecurityContextHolder` 读取经上述资源服务器建立的 `JwtAuthenticationToken`，并验证认证类型；不要仅判断任意 `Authentication.isAuthenticated()`。

如果 SDK 在线程切换后执行工具，使用所选版本 transport 的 context extractor，在已经通过认证的 HTTP 边界提取不可变 actor，放进 SDK 的请求上下文，并在工具 callback 取出。extractor 只能取已验证身份，不能将裸 Authorization header 当已认证 actor。WebFlux 使用 Reactor Context；自行创建的线程池使用显式上下文传递及 finally 清理，避免全局变量或 InheritableThreadLocal 泄漏。

有状态 transport 在创建会话时保存 subject/client/tenant/resource 绑定，在所有后续请求的 transport 分派前校验；无状态 HTTP 安全链并不意味着 MCP transport 没有会话。

## 连接与协议验证

连接地址使用 `https://service.example/mcp`，客户端选择 Streamable HTTP，通过 OAuth 获得面向该 resource 的 access token。客户端 SDK 负责协议生命周期，不向模型暴露 token。

本地集成测试按顺序执行：认证请求 `initialize` → 接收协商版本和可选 session ID → `notifications/initialized` → `tools/list` → `tools/call`（`get_order`，`arguments: {orderId: ...}`）。后续请求按协商版本带协议头及 SDK 返回的会话标识，每个请求仍需 Bearer。

HTTP POST 接收 JSON-RPC；响应可能是 JSON 或 SSE；GET 的 SSE 支持和 DELETE 会话关闭按 SDK 能力处理。不要把一次 curl POST 的 200 当作完整 MCP 接入成功。浏览器接入时显式配置可信 Origin、预检和需读取的协议响应头；反向代理保留认证/会话头，SSE 关闭缓冲并配置合适超时。

## 官方资料

- [Spring AI 1.1 MCP Server](https://docs.spring.io/spring-ai/reference/1.1/api/mcp/mcp-server-boot-starter-docs.html)：对应本例的框架集成线。
- [Spring AI 工具接口](https://docs.spring.io/spring-ai/reference/api/tools.html)：使用时切换到实际依赖版本。
- [Spring Security JWT 资源服务器](https://docs.spring.io/spring-security/reference/servlet/oauth2/resource-server/jwt.html)：JWT 解码与验证器。
- [MCP SDK 列表](https://modelcontextprotocol.io/docs/sdk)：非 Spring 项目的 SDK 入口。
- [Streamable HTTP 传输](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)：此处生命周期示例的协议基线，按目标客户端协商版本调整。

以上是集成骨架，不是已编译的独立应用。落地时实现业务适配接口、补齐 imports，并用目标项目实际依赖编译和执行端到端权限测试。
