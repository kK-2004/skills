# Sample: Using Nacos Config in Spring Boot

## Controller with @Value (Dynamic Refresh)

```java
package com.example.demo.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.context.config.annotation.RefreshScope;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RefreshScope   // <-- Enables dynamic refresh of @Value fields
@RestController
public class ConfigController {

    @Value("${myapp.welcome-message:Hello Default}")
    private String welcomeMessage;

    @Value("${myapp.feature-enabled:false}")
    private boolean featureEnabled;

    @GetMapping("/config/message")
    public String getMessage() {
        return welcomeMessage;
    }

    @GetMapping("/config/feature")
    public boolean isFeatureEnabled() {
        return featureEnabled;
    }
}
```

## Using @ConfigurationProperties (Recommended)

```java
package com.example.demo.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.cloud.context.config.annotation.RefreshScope;
import org.springframework.stereotype.Component;

@Data
@RefreshScope
@ConfigurationProperties(prefix = "myapp")
@Component
public class MyAppProperties {

    private String welcomeMessage;

    private boolean featureEnabled;

    private DataSourceConfig datasource = new DataSourceConfig();

    @Data
    public static class DataSourceConfig {
        private String url;
        private String username;
        private String password;
    }
}
```

Usage in Nacos config (Data ID: `your-app.yaml`):

```yaml
myapp:
  welcome-message: "Hello from Nacos!"
  feature-enabled: true
  datasource:
    url: jdbc:mysql://localhost:3306/mydb
    username: root
    password: secret
```

## Manually Trigger Refresh

```java
package com.example.demo.controller;

import org.springframework.cloud.context.refresh.ContextRefresher;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
import java.util.Set;

@RestController
public class RefreshController {

    private final ContextRefresher contextRefresher;

    public RefreshController(ContextRefresher contextRefresher) {
        this.contextRefresher = contextRefresher;
    }

    @PostMapping("/actuator/refresh")
    public Set<String> refresh() {
        return contextRefresher.refresh();
    }
}
```

## Verify Nacos Connection on Startup

```java
package com.example.demo;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.core.env.Environment;
import javax.annotation.PostConstruct;

@SpringBootApplication
public class DemoApplication {

    private final Environment environment;

    public DemoApplication(Environment environment) {
        this.environment = environment;
    }

    public static void main(String[] args) {
        SpringApplication.run(DemoApplication.class, args);
    }

    @PostConstruct
    public void logNacosConfig() {
        String serverAddr = environment.getProperty("spring.cloud.nacos.config.server-addr");
        String namespace = environment.getProperty("spring.cloud.nacos.config.namespace");
        System.out.println("Nacos Config:");
        System.out.println("  Server: " + serverAddr);
        System.out.println("  Namespace: " + (namespace == null || namespace.isEmpty() ? "public" : namespace));
    }
}
```

## Nacos Config Data ID Naming Convention

| Spring Profile | Data ID Loaded |
|----------------|-----------------|
| default (no profile) | `${spring.application.name}.yaml` |
| `dev` | `${spring.application.name}-dev.yaml` |
| `prod` | `${spring.application.name}-prod.yaml` |

To enable profile-specific config, set:
```yaml
spring:
  profiles:
    active: dev
```

Nacos will auto-load: `your-app.yaml` (shared) + `your-app-dev.yaml` (profile-specific).
