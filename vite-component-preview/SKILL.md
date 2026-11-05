---
name: vite-component-preview
description: 在已运行的 Vite 开发服务器页面里单独挂载一个 Vue/React 组件，用模拟 props 渲染并截图验证 UI，绕过登录、路由和后端数据。适用于改完组件样式或交互后需要目视确认，但页面需要登录、缺少测试数据或到达该组件路径太长的情况。
---

# Vite 组件单独预览

在开发服务器页面里，用浏览器执行 JS，动态导入 Vite 编译好的组件模块，挂到临时 DOM 上渲染。全局样式、主题变量、图标 CSS 都由页面本身提供，不需要登录。

## 适用前提

- 项目用 Vite 开发服务器（源文件可以通过 `/src/...` 直接导入）。
- 组件主要靠 props 驱动；依赖 store、router 或 inject 的组件，要在临时 app 上补装对应插件（见下文）。
- 只用于验证和查看，不能代替修改源码；验证完必须刷新页面清掉临时挂载。

## 步骤

1. **启动并打开页面**：用 `preview_start` 启动 dev server。停在登录页也可以，只要全局 CSS 已加载。

2. **找到页面已加载的框架模块地址**（避免出现两份运行时）：
   ```js
   performance.getEntriesByType('resource').map(e => e.name).filter(n => n.includes('/.vite/deps/vue.js'))
   ```
   拿到带 `?v=xxxx` 的完整地址。如果为空，说明页面还没预构建依赖，先正常刷新一次页面。

3. **挂载组件**（Vue）：
   ```js
   const { createApp, h } = await import('<上一步拿到的 vue.js?v=xxxx 地址>');
   const C = (await import('/src/path/to/Component.vue')).default;
   const el = document.createElement('div');
   el.id = '__component-preview';
   document.body.appendChild(el);
   createApp({ render: () => h(C, { /* 模拟 props，覆盖各种状态 */ }) }).mount(el);
   'ok'
   ```
   - 依赖 Pinia 或路由时：同样从 `.vite/deps` 里导入 `pinia`，再导入项目的 `/src/router/index.ts`，在 `createApp(...)` 后 `.use(...)`。
   - React 版本：导入 `react`、`react-dom/client` 的 deps 地址，用 `createRoot(el).render(createElement(C, props))`。

4. **准备模拟数据**：参照组件的 props 类型或现有测试夹具（`tests/*.spec.ts`），一次覆盖主要状态：空、单条、多条、长文本、缺省字段、跨年日期、选中或未选中等。时间字段使用后端的真实格式（例如不带时区的 `2026-10-14T16:14:58.052903`）。

5. **检查**：
   - 用 `computer` 的 `zoom` 截取组件所在区域，确认对齐、间距和文字截断。
   - 需要时用 `javascript_tool` 读取计算样式，或用 `read_page` 确认文本和按钮。
   - 交互用 `computer` 点击后再截图。

6. **清理**：执行 `location.reload()`，清掉临时挂载，不留在用户的预览里。

## 注意

- 组件内部如果会请求需要鉴权的接口，请求会失败。这种情况下只验证不依赖数据的部分，或者通过 props 传入数据。
- fixed 或 absolute 定位的组件（抽屉、弹窗）会盖在页面上方，截图时只取它所在的区域。
- 模块导入报 404 或编译错误时，先用 `preview_logs` 看 Vite 的报错。
- 这种方式只是目视确认，组件逻辑仍然要靠单元测试。
