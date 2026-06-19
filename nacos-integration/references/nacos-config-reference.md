# Nacos Config Property Reference

Complete reference for `spring.cloud.nacos.config.*` properties.
Based on the modern `spring.config.import` approach (Spring Boot 2.4+).

## Core Properties

| Property | Default | Description |
|----------|---------|-------------|
| `spring.cloud.nacos.config.enabled` | `true` | Enable Nacos config |
| `spring.cloud.nacos.config.server-addr` | `localhost:8848` | Nacos server address |
| `spring.cloud.nacos.config.namespace` | `""` | Namespace ID (NOT display name) |
| `spring.cloud.nacos.config.group` | `DEFAULT_GROUP` | Configuration group |
| `spring.cloud.nacos.config.file-extension` | `properties` | Config file extension (`properties`, `yaml`, `yml`) |
| `spring.cloud.nacos.config.refresh-enabled` | `true` | Enable dynamic refresh |
| `spring.cloud.nacos.config.prefix` | | Data ID prefix (overrides `spring.application.name`) |
| `spring.cloud.nacos.config.name` | | Data ID name (overrides prefix + file-extension) |

## Authentication

| Property | Default | Description |
|----------|---------|-------------|
| `spring.cloud.nacos.config.username` | | Nacos username |
| `spring.cloud.nacos.config.password` | | Nacos password (use `${ENV_VAR}` for safety) |
| `spring.cloud.nacos.config.access-key` | | Alibaba Cloud access key |
| `spring.cloud.nacos.config.secret-key` | | Alibaba Cloud secret key |

## Timeout & Retry

| Property | Default | Description |
|----------|---------|-------------|
| `spring.cloud.nacos.config.timeout` | `3000` | Request timeout (ms) |
| `spring.cloud.nacos.config.max-retry` | `3` | Max retry attempts |
| `spring.cloud.nacos.config.retry-time` | `2000` | Retry interval (ms) |

## Advanced

| Property | Default | Description |
|----------|---------|-------------|
| `spring.cloud.nacos.config.cluster-name` | `DEFAULT_CLUSTER` | Cluster name |
| `spring.cloud.nacos.config.endpoint` | | Nacos endpoint URL |
| `spring.cloud.nacos.config.encode` | `UTF-8` | Config encoding |
| `spring.cloud.nacos.config.context-path` | | Nacos context path |

## Data ID Format Rules

The Data ID is resolved in this order:

1. If `spring.cloud.nacos.config.name` is set → use it directly
2. If `spring.cloud.nacos.config.prefix` is set → `${prefix}.${file-extension}`
3. Otherwise → `${spring.application.name}.${file-extension}`

**Examples**:
- `spring.application.name=order-service` + `file-extension=yaml` → Data ID: `order-service.yaml`
- `prefix=my-config` + `file-extension=properties` → Data ID: `my-config.properties`

## Multiple Config Files (Spring Boot 2.4+)

Use `spring.config.import` to load multiple config files from Nacos:

```yaml
spring:
  config:
    import:
      - nacos:shared-config.yaml           # shared config (loaded first)
      - nacos:${spring.application.name}.yaml  # app-specific config
      - nacos:database.yaml               # database config
      - nacos:${spring.application.name}-${spring.profiles.active}.yaml  # profile-specific
```

**Load order**: Top to bottom — later configs override earlier ones.

**Make a config import optional** (app starts even if Nacos is unreachable):

```yaml
spring:
  config:
    import:
      - nacos:${spring.application.name}.yaml?optional=true
```

## Namespace vs Group vs Data ID

```
Namespace (环境隔离: dev/test/prod)
  └── Group (业务隔离: 不同团队/模块)
        └── Data ID (配置文件: 具体配置内容)
```

- **Namespace**: Isolate environments. Use **Namespace ID** (UUID), not display name.
- **Group**: Isolate business domains or teams. Default: `DEFAULT_GROUP`.
- **Data ID**: The actual config file name.

## Nacos Console Operations

### Create Config
1. Start Nacos: `startup.cmd -m standalone` (Windows) / `sh startup.sh -m standalone` (Linux)
2. Login to console: `http://127.0.0.1:8848/nacos` (default: `nacos`/`nacos`)
3. Go to **配置管理 > 配置列表**
4. Click **+ 新建配置**
5. Fill in Data ID, Group, format, and content
6. Click **发布**

### View Config History
**配置管理 > 历史版本** — view/edit history of a config.

### Listen for Config Changes
**配置管理 > 监听查询** — see which clients are listening to which config.
