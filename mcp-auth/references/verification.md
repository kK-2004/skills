# 验证清单

用隔离数据库与测试账号执行，不触碰线上数据。`BASE` 为服务本地地址，`MCP=$BASE/mcp`。

## 发现与 challenge

```bash
curl -si -X POST "$MCP" -H 'Content-Type: application/json' -d '{}' | grep -i www-authenticate
curl -s "$BASE/.well-known/oauth-protected-resource/mcp"
curl -s "$BASE/.well-known/oauth-authorization-server"
curl -s -H 'Host: evil.example' "$BASE/.well-known/oauth-protected-resource/mcp"   # resource 仍为配置值
```

期望：401 且 header 含 `resource_metadata` 与 `scope="mcp:tools"`；metadata 的 `resource` 与 `$MCP` 逐字一致。

## DCR

```bash
curl -s -X POST "$BASE/oauth2/register" -H 'Content-Type: application/json' \
  -d '{"client_name":"t","redirect_uris":["http://127.0.0.1:33418/callback"],"token_endpoint_auth_method":"none"}'
```

- 非 localhost 的 http 回调 → 400，且不落库
- 未在白名单的自定义 scheme → 400
- `token_endpoint_auth_method=client_secret_basic` → 400
- 同名同回调重复注册 → 返回同一 client_id，不计限流
- 超过限流 → 429

## 授权与 token

用 `openssl rand` 生成 verifier，`challenge=base64url(sha256(verifier))`。

| 用例 | 期望 |
|------|------|
| 缺 state / 缺 challenge / `plain` 方法 / resource 不一致 / redirect 不匹配 | 400，不发生重定向 |
| 浏览器导航 authorize | 302 到前端 consent 页 |
| JSON 请求 + 未登录 | 401 `loginRequired` |
| 拒绝 | 回调带 `error=access_denied&state=` |
| 批准 | 回调只含 `code` 与原 `state` |
| 错误 verifier 兑换 | `invalid_grant` |
| 同一 code 第二次兑换 | `invalid_grant` |
| 过期 code | `invalid_grant` |
| refresh 正常轮换 | 新 access + 新 refresh，旧 refresh 失效 |
| 旧 refresh 重放 | `invalid_grant`，同 grant 下所有 access/refresh 失效 |

## 资源访问

| 用例 | 期望 |
|------|------|
| 有效 token 调 `tools/list`、`tools/call` | 成功，工具内身份为授权用户 |
| 过期 / 伪造 / 已吊销 token | 401 challenge |
| 其他 resource 签发的 token | 401 |
| 缺少 `mcp:tools` scope | 403 `insufficient_scope` |
| MCP token 访问管理后台 API | 401（不被接受） |
| Web session cookie 访问 `/mcp` | 401 |
| 工具输入夹带身份字段 | 被剥离，不影响身份 |
| 撤销该 grant 后再调用 | 401 |
| 禁用用户后再调用 / refresh | 401 / `invalid_grant` |
| 普通用户撤销他人 grant | 403 |

## 数据与日志

- 数据库中 code / access / refresh 列均为 64 位十六进制哈希，无明文。
- 应用日志与访问日志中搜索 token 片段无命中；`/oauth2/token` 响应带 `Cache-Control: no-store`。

## 真实客户端

至少用一个真实客户端完成全流程：

```bash
claude mcp add --transport http my-mcp https://<host>/mcp
```

在客户端触发授权 → 浏览器登录并批准 → 列出并调用工具 → 管理后台撤销 → 客户端再次调用收到 401 并重新授权。记录客户端名称与版本，作为兼容性结论的依据。
