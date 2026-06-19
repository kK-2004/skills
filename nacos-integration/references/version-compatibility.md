# Nacos + Spring Cloud Alibaba Version Compatibility

**Always check this matrix before choosing versions!**
Only Spring Boot 2.4+ supports `spring.config.import` (no bootstrap.yml needed).

## Version Mapping (Spring Boot 2.4+)

| Spring Boot | Spring Cloud | Spring Cloud Alibaba | Nacos Client |
|-------------|--------------|----------------------|--------------|
| 2.4.x — 2.7.x | 2021.0.x | **2021.0.5.0** (Recommended) | 2.2.x — 2.3.x |
| 3.0.x — 3.2.x | 2023.0.x | **2023.0.1.0** | 2.3.x — 2.4.x |

## Recommended Stable Combinations

### For Spring Boot 2.7.x (nacosDemo uses this)

```xml
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>2.7.18</version>
</parent>

<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>com.alibaba.cloud</groupId>
            <artifactId>spring-cloud-alibaba-dependencies</artifactId>
            <version>2021.0.5.0</version>
            <type>pom</type>
            <scope>import</scope>
        </dependency>
    </dependencies>
</dependencyManagement>
```

### For Spring Boot 3.2.x

```xml
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.0</version>
</parent>

<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>com.alibaba.cloud</groupId>
            <artifactId>spring-cloud-alibaba-dependencies</artifactId>
            <version>2023.0.1.0</version>
            <type>pom</type>
            <scope>import</scope>
        </dependency>
    </dependencies>
</dependencyManagement>
```

## Nacos Server Version

| Nacos Client | Compatible Nacos Server |
|---------------|------------------------|
| 2.x | 2.x (recommended) |
| 1.4.x | 1.4.x, 2.x (backward compatible) |

**Recommendation**: Use **Nacos 2.3.x** server with **Nacos Client 2.3.x**.

## Java Version

| Nacos Version | Minimum Java |
|---------------|---------------|
| 2.x | Java 8+ |
| 1.4.x | Java 8+ |

## Common Version Conflict Symptoms

| Symptom | Cause | Fix |
|----------|-------|-----|
| `java.lang.NoSuchMethodError` | Mismatched SCA / Nacos Client | Use BOM to align all versions |
| `Property 'spring.cloud.nacos.config' threw exception` | Incompatible Nacos Client | Ensure `nacos-client` version matches SCA managed version |
| `spring.config.import` not found | Spring Boot < 2.4 | Upgrade to 2.4+ or use bootstrap.yml (not recommended) |
