---
name: nacos-integration
description: >
  This skill provides step-by-step guidance for integrating Alibaba Nacos as a configuration center
  in Spring Boot projects using the modern spring.config.import approach (Spring Boot 2.4+).
  It should be used when the user wants to add Nacos config management to a Spring Boot application,
  migrate from static configuration to Nacos, or set up dynamic configuration refresh.
  Based on the nacosDemo project practices — no bootstrap.yml needed.
agent_created: true
---

# Nacos Integration Skill

Integrate Alibaba Nacos configuration center into Spring Boot projects using the **modern `spring.config.import` approach** (Spring Boot 2.4+, no `bootstrap.yml` needed).

## Overview

Nacos provides dynamic configuration management. This skill focuses on **configuration center** integration only (not service registration).

The approach used here is based on the **nacosDemo** project: `application.yml` + `spring.config.import` + Spring Cloud Alibaba.

## When to Use This Skill

- User says: "接入 Nacos 配置中心"
- User says: "帮我集成 Nacos"
- User says: "把配置迁移到 Nacos"
- User has a Spring Boot project and wants externalized configuration management

## Integration Steps

### Step 1: Add Dependencies

Add to `pom.xml`. Read `assets/pom-dependencies.xml` for exact dependency blocks.

Required dependencies:
- `spring-cloud-starter-alibaba-nacos-config` — Nacos config client
- `spring-cloud-starter-alibaba-nacos-discovery` — (optional) service discovery
- `nacos-client` — Nacos client

**Important**: Use the BOM (`spring-cloud-alibaba-dependencies`) to avoid version conflicts. See `references/version-compatibility.md`.

### Step 2: Create `application.yml`

This is the **only** config file needed. No `bootstrap.yml`.

Copy `assets/application.yml.template` and edit the TODO fields:

```yaml
spring:
  application:
    name: your-app-name          # becomes Nacos Data ID prefix

  config:
    import:
      - nacos:${spring.application.name}.yaml   # loads from Nacos

  cloud:
    nacos:
      config:
        server-addr: 127.0.0.1:8848
        file-extension: yaml
        group: DEFAULT_GROUP
        namespace: ""              # empty = public; use UUID for custom namespace
        refresh-enabled: true
```

### Step 3: Create Config in Nacos Console

1. Start Nacos server: `startup.cmd -m standalone` (Windows) or `sh startup.sh -m standalone` (Linux)
2. Open console: `http://127.0.0.1:8848/nacos` (default login: `nacos`/`nacos`)
3. Go to **配置管理 > 配置列表**
4. Click **+ 新建配置**:
   - **Data ID**: `${spring.application.name}.yaml` (e.g., `my-app.yaml`)
   - **Group**: `DEFAULT_GROUP`
   - **配置格式**: YAML
   - **配置内容**: paste your config YAML
5. Click **发布**

### Step 4: Verify

Start the Spring Boot app. If config loads successfully, you'll see Nacos-related logs during startup. Test dynamic refresh by:
1. Changing a value in the Nacos console
2. Calling a `@RefreshScope` endpoint — value should update without restart

## Dynamic Refresh

To make config values refreshable at runtime:

```java
import org.springframework.cloud.context.config.annotation.RefreshScope;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

@RefreshScope   // <-- enables @Value refresh
@RestController
public class ConfigController {

    @Value("${myapp.message:default}")
    private String message;

    @GetMapping("/config/message")
    public String getMessage() {
        return message;   // updates when Nacos config changes
    }
}
```

For `@ConfigurationProperties`, add `@RefreshScope` to the class (see `references/java-samples.md`).

## Multi-Environment Configuration

Use **Nacos namespace** to isolate environments:

| Environment | Namespace ID | Nacos Console Action |
|-------------|---------------|----------------------|
| dev | `dev-namespace-id` | Create namespace in **命名空间** tab |
| test | `test-namespace-id` | Same |
| prod | `prod-namespace-id` | Same |

In `application.yml`, set `spring.cloud.nacos.config.namespace` to the **namespace ID** (a UUID), not the display name.

## Common Patterns

### Database Config in Nacos

In Nacos Data ID `your-app.yaml`:

```yaml
spring:
  datasource:
    driver-class-name: com.mysql.cj.jdbc.Driver
    url: jdbc:mysql://localhost:3306/mydb?useUnicode=true&characterEncoding=utf8
    username: root
    password: ${DB_PASSWORD:default_pwd}
```

### Custom Config with @ConfigurationProperties

See `references/java-samples.md` for complete examples.

## Troubleshooting

| Symptom | Cause | Fix |
|----------|-------|-----|
| Config not loading | Data ID mismatch | Ensure `spring.application.name` matches the Nacos Data ID prefix |
| Namespace not working | Using namespace name instead of ID | Use the **namespace ID** (UUID), not the display name |
| Dynamic refresh not working | Missing `@RefreshScope` | Add `@RefreshScope` to the bean class |
| Connection refused | Nacos not running | Run `startup.cmd -m standalone` and verify `http://127.0.0.1:8848/nacos/` |
| `spring.config.import` error | Nacos unreachable at startup | Add `optional:` prefix: `nacos:your-app.yaml?optional=true` |

## File References

- `assets/pom-dependencies.xml` — Maven dependencies (copy-paste ready)
- `assets/application.yml.template` — `application.yml` template (the only config file needed)
- `references/version-compatibility.md` — Spring Boot / Spring Cloud Alibaba / Nacos version matrix
- `references/nacos-config-reference.md` — Complete `spring.cloud.nacos.config.*` property reference
- `references/java-samples.md` — Java samples: `@Value`, `@RefreshScope`, `@ConfigurationProperties`
