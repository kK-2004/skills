---
name: mcp-service-wrapper
description: 将现有业务服务包装为 MCP Server，实施远程 HTTP OAuth 鉴权、可信身份传递、工具级与数据级授权及验证 SOP。适用于新增业务 MCP 接口、给现有 MCP 接入鉴权或补齐工具调用控权；不用于仅配置 MCP 客户端连接。
---

# MCP 业务服务封装 SOP

目标：以薄适配层暴露明确的业务能力，复用既有 Service 和权限规则，让 MCP 调用者只能执行其用户身份与客户端授权共同允许的操作。默认沿用目标项目技术栈、身份系统和部署方式，不要求迁移到 Spring 或自建授权服务器。

## 1. 识别现状与边界

读取目标仓库约束，查找协议 SDK/版本、路由、安全过滤器、业务 Service、权限注解、租户上下文、数据库迁移和测试。追踪真实调用路径；Controller 上的拦截器或权限注解通常不会自动保护直接调用 Service 的 MCP 工具。

先形成简短映射表：`业务能力 → Service 方法 → 输入/输出 → 用户/租户来源 → 所需 scope → 角色/动作权限 → 对象权限 → 副作用/确认要求`。只暴露任务需要的能力，避免提供任意 URL 请求、SQL 或反射式通用执行工具。

判断是同进程适配还是独立网关。同进程直接调 Service；独立网关使用有契约的业务 API 和受支持的身份委派，不能用共享超级管理员凭据替代调用者权限。不要把发给 MCP 的令牌直接转发给不同 audience 的下游服务。

确定技术栈后，按 [SDK 与 Streamable HTTP 实施方法](references/sdk-streamable-http.md) 接入 SDK、配置端点、注册工具、建立认证链和传递身份。该文档提供通用业务示例；将示例 Service、DTO 和权限接口替换为目标项目实现。

## 2. 确定接入与认证

远程 HTTP 场景默认使用 MCP SDK + Streamable HTTP，由 SDK 处理协议协商、工具发现、调用分派、会话和流式响应，不手写 MCP JSON-RPC 协议层；本地 stdio 场景按运行环境交付凭据，不强套浏览器 OAuth 流程。实现前核对所选 SDK 与客户端的协议版本，勿盲抄版本号或配置键。

远程受保护资源接入遵循 [auth-and-permissions.md](references/auth-and-permissions.md)：优先复用现有授权服务器，明确 issuer、resource/audience、客户端注册方式和 scope。只有业务确需自建授权端时才加入授权码、consent、token、refresh、revoke 的持久化与生命周期处理。

把 MCP Bearer 入口和 Web session、开放应用 token 的认证边界分开。每个 MCP HTTP 请求验证凭据，不能把 MCP session ID 当成登录凭证。认证信息必须在实际工具执行边界可用；异步/线程池模式需显式传递可信上下文并清理。

## 3. 实现工具薄适配层

按 `依赖/BOM → Streamable HTTP 端点 → 工具 schema 与注册 → Bearer 安全链 → 可信身份上下文 → scope/业务 ACL → 客户端联调` 落地。Spring MVC 可采用 `spring-ai-starter-mcp-server-webmvc`、`protocol: STREAMABLE`、`@Tool` 和 `ToolCallbackProvider`；其他技术栈使用对应官方 SDK 的等价接口，具体代码见实施方法。

- 明确注册工具或使用框架注解生成 schema；只让模型填写业务参数。subject、client、role、scope、tenant 的可信值来自认证上下文，不能从工具参数建立身份。
- 描述说明用途、前置条件、必要参数、数据含义和副作用；身份凭据不得出现在 schema、提示词或业务返回值中。
- 工具入口校验认证来源、所需 scope、当前业务动作权限与对象权限，然后调用现有 Service。对列表在查询层限制可见范围，对详情和写操作重新校验目标对象；知道 ID 不等于获得权限。
- 若权限只存在于原 Controller，提取共享授权逻辑或在 MCP 适配层明确调用。区分可查看、可编辑、可删除、可导出，不能把笼统“管理权限”套给所有动作。
- 输出使用明确 DTO/结构化结果，限制分页和返回体大小；只读查询不顺带生成可公开访问的分享链接。创建下载/分享链接是有副作用的能力。
- 工具目录过滤可改善体验，但 `tools/call` 必须独立鉴权；description、readOnly 等 annotations 和 UI 隐藏都不是访问控制。

## 4. 按业务风险实现确认与重试

业务本身要求预览确认时采用 `prepare → confirm/execute`，确认凭据绑定可信用户、动作、规范化后的最终参数以及必要的租户/client，设置有效期并原子消费。执行时重新校验权限；模板/业务数据变动导致预览不同，应重新预览。

确认凭据只能证明某次预览存在及参数一致，不能单独证明人类已经批准。普通流程由宿主展示并承接用户授权；业务要求强制人工审批时，必须由受信任 UI/审批服务记录批准事件。不要把 `confirmed=true` 或模型填写的 `_selected` 当成审批证据，也不要为所有只读工具强加确认。

写操作按业务需求实现幂等键或结果查询。超时后先查执行状态，不能无限重试可能已成功的副作用。第三方授权被撤销或 scope 不足时停止执行并返回明确错误，不换高权限身份重试。

## 5. 验证和交付

按 [verification.md](references/verification.md) 选择与本次变更相关的用例，至少覆盖真实 HTTP → 工具 → Service 路径的成功、未认证、scope 不足和跨对象越权。使用隔离测试数据验证副作用，不触碰线上业务。

交付工具/权限映射、实现与配置、实际运行的验证结果及未验证项、客户端连接与撤销方式。新增数据模型遵循目标仓库的迁移机制；部署和发布只在任务范围内执行。若仅要求 SOP/设计文档，就交付文档，不顺带修改业务服务。
