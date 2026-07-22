---
name: utc-time-handling
description: >
  全栈时间处理规范：数据库存 UTC、JPA/Hibernate 时区配置、Jackson 序列化、前端展示转本地时区。
  适用于 Spring Boot 3 + JPA + MySQL 后端 + Vue/JS 前端项目，处理时间字段的存储、传输与显示。
  在新增带时间字段的实体、排查时间显示偏差（慢 8 小时等）、配置时区、或设计 API 时间格式时使用。
  核心原则：存 UTC、传 ISO-8601（带 Z）、显示转本地。
agent_created: true
---

# 全栈时间处理规范（存 UTC、显示本地）

## 核心原则

**统一存 UTC，传输带时区标识，前端按本地时区显示。** 三层各司其职，不在存储层做本地化。

```
[前端] 本地时间 ←→ [传输] ISO-8601 (Z=UTC) ←→ [后端 Instant] ←→ [DB] UTC 字面值
 显示/输入           JSON 序列化              Java 绝对时间点        DATETIME/TIMESTAMP
```

**为什么存 UTC**：服务器可能跨时区部署、用户可能来自不同时区、日志/审计时间需要全局可比。存 UTC 是唯一无歧义的选择；本地化只在「展示给用户看」的最后一步做。

---

## 后端配置（Spring Boot 3 + JPA + MySQL）

### 1. JDBC 连接：serverTimezone=UTC

`application.yml`（dev/prod 都要）：

```yaml
spring:
  datasource:
    url: jdbc:mysql://host:3306/db?useUnicode=true&characterEncoding=utf8&useSSL=false&serverTimezone=UTC&allowPublicKeyRetrieval=true
```

`serverTimezone=UTC` 告诉 MySQL JDBC 驱动：与 DB 通信时按 UTC 解释时间。

### 2. Hibernate 时区：jdbc.time_zone=UTC

```yaml
spring:
  jpa:
    properties:
      hibernate:
        jdbc:
          time_zone: UTC
```

这让 Hibernate 在读写 `Instant`/`LocalDateTime` 时统一用 UTC，避免 JVM 默认时区干扰。

### 3. 实体字段：用 Instant + Hibernate 时间戳注解

```java
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;
import java.time.Instant;

@Getter @Setter
@Entity
@Table(name = "xxx")
public class XxxEntity {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // 创建时间（自动，只写一次）
    @CreationTimestamp
    private Instant createdAt;

    // 更新时间（自动，每次更新刷新）
    @UpdateTimestamp
    private Instant updatedAt;
}
```

**关键点**：
- 用 `java.time.Instant`（绝对时间点，与时区无关，本质是 UTC 时间戳），**不要**用 `LocalDateTime`（无时区语义，易踩坑）。
- `@CreationTimestamp` / `@UpdateTimestamp` 由 Hibernate 自动填充，无需手动 set。
- **不需要** `@EnableJpaAuditing`（那是 Spring Data JPA 的 `@CreatedDate`/`@@LastModifiedDate` 体系，与 Hibernate 注解二选一；本规范用 Hibernate 原生注解，更轻量）。

### 4. DB 列类型

`ddl-auto: update` 会自动把 `Instant` 映射为 MySQL `DATETIME(6)`（带微秒）。列里存的是 **UTC 字面值**（配合上面的 `serverTimezone=UTC` + `jdbc.time_zone=UTC`，三层一致）。

---

## 序列化（Jackson）

Spring Boot 默认用 Jackson 序列化 `Instant`，输出格式为 **ISO-8601 带毫秒 + Z 后缀**：

```json
{ "createdAt": "2026-06-20T13:24:37.123Z", "updatedAt": "2026-06-20T13:30:00.456Z" }
```

`Z` = UTC，前端能正确识别。**默认行为正确，无需额外配置。**

### 如需关闭时间戳数字格式（防 ISO8601 被写成数值）

如果 `application.yml` 里被设过 `spring.jackson.serialization.write-dates-as-timestamps: true`，会把日期写成毫秒数值（`1750428277123`），前端需 `new Date(数值)` 也能解析但不直观。**推荐保持默认 false（ISO-8601 字符串）**：

```yaml
spring:
  jackson:
    serialization:
      write-dates-as-timestamps: false  # 默认即 false，ISO-8601 字符串输出
```

### 接收前端时间（反序列化）

前端传 ISO-8601 字符串（如 `"2026-06-20T13:24:37Z"`），Jackson 自动反序列化为 `Instant`。DTO 字段用 `Instant`：

```java
public record SomeReq(String name, Instant startAt, Instant endAt) {}
```

---

## 前端处理（Vue / 原生 JS）

### 1. 显示：UTC ISO 字符串 → 本地时区

```js
const formatTime = (iso) => {
  if (!iso) return '-'
  try {
    // new Date("...Z") 识别为 UTC，toLocaleString() 转浏览器本地时区
    return new Date(iso).toLocaleString()
  } catch { return String(iso) }
}
```

`new Date("2026-06-20T13:24:37Z")` → 浏览器自动转为本地时间（如中国 UTC+8 → `2026-06-20 21:24:37`）。

**模板里直接用：**
```vue
<template #default="{ row }">{{ formatTime(row.createdAt) }}</template>
```

### 2. 指定显示格式 / 时区

```js
// 指定时区显示
new Date(iso).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })

// 自定义格式
new Date(iso).toLocaleString('zh-CN', {
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
})
```

### 3. 提交：本地时间 → UTC ISO 字符串

用 `<input type="datetime-local">` 或日期选择器拿到的本地时间，提交前转 UTC：

```js
// datetime-local 的值是本地时间无时区，需手动标注后转 UTC
const localValue = '2026-06-20T21:24'  // 来自 input
const utcIso = new Date(localValue).toISOString()  // → "2026-06-20T13:24:00.000Z"
// 提交给后端
api.create({ startAt: utcIso })
```

`Date.toISOString()` 永远返回 UTC（带 Z），后端 Jackson 正确解析。

---

## 排查时间显示问题

### 现象：时间慢 8 小时（中国用户）

**原因 A**：后端返回的时间字符串**没带 `Z`**（如 `"2026-06-20T13:24:37"`），前端 `new Date(...)` 把它当**本地时间**解析 → 比真实 UTC 时间少算了 +8 → 显示比实际早 8 小时。
**修复**：确保 Jackson 输出带 `Z`（默认行为，检查是否被全局/字段级 `@JsonFormat` 改写）。或前端 `new Date(iso + 'Z')` 补时区。

**原因 B**：DB 存的不是 UTC（`serverTimezone` 配错），导致读出的值本身就是本地时间，又被当 UTC → 双重偏移。
**修复**：核对 `serverTimezone=UTC` + `jdbc.time_zone: UTC` 一致。

### 现象：时间快 8 小时

通常是把本地时间当 UTC 存了（JVM 时区是 +8，但没配 `jdbc.time_zone: UTC`，Hibernate 用 JVM 时区写库）。
**修复**：补上 `spring.jpa.properties.hibernate.jdbc.time_zone: UTC`。

### 自检命令

```bash
# 看 DB 实际存的值（应为 UTC）
mysql -e "SELECT NOW(), UTC_TIMESTAMP(), created_at FROM xxx LIMIT 1;"

# 对比：NOW()（DB 会话时区）vs UTC_TIMESTAMP()（真 UTC）vs 你的列值
```

---

## 决策清单（新增时间字段时）

- [ ] 实体字段用 `Instant`（不是 `LocalDateTime`/`Date`）
- [ ] 用 `@CreationTimestamp`/`@UpdateTimestamp` 自动填充
- [ ] `application.yml` 配 `serverTimezone=UTC` + `hibernate.jdbc.time_zone: UTC`
- [ ] Jackson 保持默认（ISO-8601 带 Z 输出），不要乱加 `@JsonFormat(timezone=...)`
- [ ] 前端 `new Date(iso).toLocaleString()` 显示
- [ ] 前端提交用 `new Date(localValue).toISOString()` 转 UTC

---

## 反模式（不要做）

- ❌ DB 存本地时间（跨时区部署即灾难）
- ❌ 实体用 `LocalDateTime`（无时区语义，序列化/跨时区易错）
- ❌ 在 `application.yml` 设 `spring.jackson.time-zone: Asia/Shanghai`（强制全局本地化序列化，破坏 UTC 一致性）
- ❌ 后端手动 `+8 小时` 再返回（时区转换是前端的职责）
- ❌ 前端 `new Date(iso).getHours()` 直接用（应为 `toLocaleString` 走时区转换）
- ❌ 混用 `@CreatedDate`（Spring Data）与 `@CreationTimestamp`（Hibernate），一个项目只用一套
