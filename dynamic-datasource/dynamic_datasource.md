---
name: dynamic-datasource
description: 在 Spring Boot + MyBatis 项目中实现基于注解的动态数据源。覆盖两类场景：(1) 主从读写分离（@Master/@Slave）；(2) 非主从的多业务库按 DAO 包自动绑定多 SqlSessionFactory（零注解，如 training/qlearning/lecturer）。当用户需要实现多数据源路由、读写分离、@Master/@Slave 切换数据源、按 DAO 包静态绑定多 SqlSessionFactory、AbstractRoutingDataSource 集成、或排查"切库未生效/事务连错库"问题时使用。
---

# 动态数据源（读写分离）Skill

> 本 skill 为**通用指南**，不绑定任何具体包名。落地时，请先按下方"项目适配"步骤确定本项目的根包与 Mapper 扫描路径，再生成代码。

## 适用场景
- Spring Boot 2.x + MyBatis / MyBatis-Plus 项目需要把**写操作走主库、读操作走从库**。
- 通过方法/类上的注解（`@Master` / `@Slave`）声明式切换数据源。
- 排查动态数据源相关问题：切库不生效、事务连错库、默认数据源不对、ThreadLocal 未清理。

## 项目适配（动手前必做）
1. **确定根包**：找到本项目 `@SpringBootApplication` 主类所在包，记为 `<BASE_PACKAGE>`（例如 `com.company.project`）。
2. **新建数据源子包**：在本项目内新建 `<BASE_PACKAGE>.datasource`，下文所有类都放该包下。
3. **确认 Mapper 路径**：列出本项目 Mapper 接口实际所在的包（可能多个，例如 `*.dao.mapper`、`*.mapper`、`*.*.mapper`），记为 `<MAPPER_PACKAGES>`，供 `DataSourceConfig` 的 `@MapperScan` 使用。
4. **确认连接池与驱动**：本 skill 默认 HikariCP + MySQL（`com.mysql.cj.jdbc.Driver`）。若项目用 Druid 或其他数据库，替换 `DataSource` 实现与 `driver-class-name` 即可，其余逻辑不变。
5. **确认配置前缀**：主从库连接信息默认放在 `spring.datasource.master` / `spring.datasource.slave`，通过 `@ConfigurationProperties` 绑定。若项目已有约定的前缀，统一替换即可。

## 核心原理
1. `AbstractRoutingDataSource` 持有一组目标数据源（`targetDataSources`），运行时由 `determineCurrentLookupKey()` 返回的 key 决定真正使用哪个。
2. 路由 key 来自 `ThreadLocal`（`DynamicDataSourceHolder`），由 AOP 切面在方法执行前写入、执行后清理。
3. **关键顺序**：事务管理器绑定的就是动态数据源，事务开启那一刻就会从路由数据源取连接并读取 ThreadLocal。因此**切库切面（`@Order(-1)`）必须早于事务（`@EnableTransactionManagement(order=0)`）执行**，否则连接一旦在切库前取走，注解就失效了。
4. 默认数据源是主库，由 `ThreadLocal.withInitial(() -> MASTER)` 兜底，与切面无关。

## 文件清单与职责
所有文件位于 `<BASE_PACKAGE>.datasource`：

| 文件 | 职责 |
|---|---|
| `DataSourceType.java` | 枚举：`MASTER` / `SLAVE` |
| `Master.java` | 切主库注解（`@Target METHOD, TYPE`） |
| `Slave.java` | 切从库注解（`@Target METHOD, TYPE`，含 `value()` 从库名） |
| `DynamicDataSourceHolder.java` | `ThreadLocal` 存储当前数据源类型，提供 set/get/clear/isMaster |
| `DynamicDataSource.java` | 继承 `AbstractRoutingDataSource`，`determineCurrentLookupKey()` 读 ThreadLocal |
| `DataSourceConfig.java` | 创建 `masterDataSource` / `slaveDataSource` 两个连接池 + `@MapperScan` |
| `RoutingDataSourceConfig.java` | 组装 `@Primary dynamicDataSource` + 绑死它的事务管理器 |
| `DataSourceAspect.java` | AOP 切面，拦截 `@Master`/`@Slave` 写 ThreadLocal |

## 实现代码（落地时先按"项目适配"替换包名）

### DataSourceType.java
```java
package <BASE_PACKAGE>.datasource;

public enum DataSourceType {
    MASTER, // 主库
    SLAVE   // 从库
}
```

### Master.java
```java
package <BASE_PACKAGE>.datasource;

import java.lang.annotation.*;

@Target({ElementType.METHOD, ElementType.TYPE})
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface Master {
}
```

### Slave.java
```java
package <BASE_PACKAGE>.datasource;

import java.lang.annotation.*;

@Target({ElementType.METHOD, ElementType.TYPE})
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface Slave {
    String value() default ""; // 用于指定从库名称
}
```

### DynamicDataSourceHolder.java
```java
package <BASE_PACKAGE>.datasource;

public class DynamicDataSourceHolder {
    // 默认 MASTER，由 supplier 兜底（remove 后下次 get 仍返回 MASTER）
    private static final ThreadLocal<DataSourceType> contextHolder =
            ThreadLocal.withInitial(() -> DataSourceType.MASTER);

    public static void setDataSource(DataSourceType type) {
        contextHolder.set(type);
    }

    public static DataSourceType getDataSource() {
        return contextHolder.get();
    }

    public static void clear() {
        contextHolder.remove();
    }

    public static boolean isMaster() {
        return DataSourceType.MASTER.equals(getDataSource());
    }
}
```

### DynamicDataSource.java
```java
package <BASE_PACKAGE>.datasource;

import org.springframework.jdbc.datasource.lookup.AbstractRoutingDataSource;
import lombok.extern.slf4j.Slf4j;
import javax.sql.DataSource;
import java.util.Map;

@Slf4j
public class DynamicDataSource extends AbstractRoutingDataSource {

    public DynamicDataSource(DataSource defaultDataSource, Map<Object, Object> targetDataSources) {
        super.setDefaultTargetDataSource(defaultDataSource);
        super.setTargetDataSources(targetDataSources);
        super.afterPropertiesSet();
    }

    @Override
    protected Object determineCurrentLookupKey() {
        DataSourceType dataSourceType = DynamicDataSourceHolder.getDataSource();
        log.info("本次使用的数据源类型为：{}", dataSourceType);
        return dataSourceType;
    }
}
```

### DataSourceConfig.java
```java
package <BASE_PACKAGE>.datasource;

import javax.sql.DataSource;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import com.zaxxer.hikari.HikariDataSource;
import lombok.extern.slf4j.Slf4j;

@Configuration
// 替换为项目实际的 Mapper 包路径（见"项目适配"第 3 步）
@MapperScan(basePackages = {
        "<MAPPER_PACKAGES>" })
@Slf4j
public class DataSourceConfig {

    @Bean(name = "masterDataSource")
    @ConfigurationProperties(prefix = "spring.datasource.master")
    public DataSource masterDataSource() {
        log.info("初始化主库数据源");
        return new HikariDataSource();
    }

    @Bean(name = "slaveDataSource")
    @ConfigurationProperties(prefix = "spring.datasource.slave")
    public DataSource slaveDataSource() {
        log.info("初始化从库数据源");
        return new HikariDataSource();
    }
}
```

### RoutingDataSourceConfig.java
```java
package <BASE_PACKAGE>.datasource;

import java.util.HashMap;
import java.util.Map;
import javax.sql.DataSource;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.DependsOn;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;

@Configuration
@EnableTransactionManagement(order = 0) // 确保事务最后执行
public class RoutingDataSourceConfig {

    @Bean(name = "dynamicDataSource")
    @Primary
    @DependsOn({"masterDataSource", "slaveDataSource"})
    public DataSource dynamicDataSource(
            @Qualifier("masterDataSource") DataSource masterDataSource,
            @Qualifier("slaveDataSource") DataSource slaveDataSource) {
        Map<Object, Object> targetDataSources = new HashMap<>();
        targetDataSources.put(DataSourceType.MASTER, masterDataSource);
        targetDataSources.put(DataSourceType.SLAVE, slaveDataSource);
        return new DynamicDataSource(masterDataSource, targetDataSources);
    }

    @Bean(name = "transactionManager")
    @DependsOn("dynamicDataSource")
    public PlatformTransactionManager transactionManager(DataSource dynamicDataSource) {
        DataSourceTransactionManager txManager = new DataSourceTransactionManager();
        txManager.setDataSource(dynamicDataSource); // 关键：绑定动态数据源
        return txManager;
    }
}
```

### DataSourceAspect.java
```java
package <BASE_PACKAGE>.datasource;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import lombok.extern.slf4j.Slf4j;

@Aspect
@Component
@Order(-1) // 确保在事务之前执行
@Slf4j
public class DataSourceAspect {

    @Around("@annotation(master) || @within(master)")
    public Object setMasterDataSource(ProceedingJoinPoint pjp, Master master) throws Throwable {
        try {
            DynamicDataSourceHolder.setDataSource(DataSourceType.MASTER);
            return pjp.proceed();
        } finally {
            DynamicDataSourceHolder.clear();
        }
    }

    @Around("@annotation(slave) || @within(slave)")
    public Object setSlaveDataSource(ProceedingJoinPoint pjp, Slave slave) throws Throwable {
        try {
            DynamicDataSourceHolder.setDataSource(DataSourceType.SLAVE);
            return pjp.proceed();
        } finally {
            DynamicDataSourceHolder.clear();
        }
    }
}
```

## 配置文件（application-*.yml）
```yaml
spring:
  datasource:
    master:
      driver-class-name: com.mysql.cj.jdbc.Driver
      jdbc-url: jdbc:mysql://<host>:3306/<db>?useUnicode=true&characterEncoding=utf-8&serverTimezone=GMT%2B8&useSSL=false
      username: <user>
      password: <pwd>
      hikari:
        minimum-idle: 10
        maximum-pool-size: 200
        auto-commit: true
        idle-timeout: 30000
        pool-name: MASTER_POOL
        max-lifetime: 1800000
        connection-timeout: 30000
        connection-test-query: SELECT 1
    slave:
      driver-class-name: com.mysql.cj.jdbc.Driver
      jdbc-url: jdbc:mysql://<slave-host>:3306/<db>?useUnicode=true&characterEncoding=utf-8&serverTimezone=GMT%2B8&useSSL=false
      username: <user>
      password: <pwd>
      hikari:
        minimum-idle: 10
        maximum-pool-size: 200
        auto-commit: true
        idle-timeout: 30000
        pool-name: SLAVE_POOL
        max-lifetime: 1800000
        connection-timeout: 30000
        connection-test-query: SELECT 1
```
`DataSourceConfig` 用 `@ConfigurationProperties(prefix = "spring.datasource.master|slave")` 绑定到 `HikariDataSource`。若项目连接池前缀或类型不同（如 Druid），相应调整 `prefix` 与 `DataSource` 实现类。

## 使用方式（SOP）
1. **标注读方法/读服务走从库**：在只读的 Service 方法或类上加 `@Slave`。
   ```java
   @Slave
   public CourseVO getCourseDetail(Long id) { ... }
   ```
2. **写操作无需标注**：默认走主库（`ThreadLocal` 初始值即 `MASTER`）。需要显式强调时也可在类/方法上加 `@Master`。
3. 类级注解（`@within`）对类内所有公有方法生效；方法级注解（`@annotation`）覆盖单个方法，方法级优先于类级（两个切面各自独立拦截，方法级 set 后类级 finally 的 `clear()` 在方法返回后才执行，不会冲突）。
4. **务必用 `@Transactional` 的方法也要加 `@Slave`**：事务开启即取连接，必须保证切库切面先跑（已通过 `@Order(-1)` + `@EnableTransactionManagement(order=0)` 保证）。

## 关键注意事项（易错点）
- **切面只写 ThreadLocal，不负责路由**：真正路由在 `DynamicDataSource.determineCurrentLookupKey()`。切面缺了 `@within` 会导致类级注解失效。
- **`@Order(-1)` 与 `@EnableTransactionManagement(order=0)` 是配套设计**：值越小优先级越高、越外层先执行。切库必须早于事务，否则连接取错库，注解形同虚设。
- **`@DependsOn` 是防御性显式顺序**：保证主从池先于 dynamicDataSource 初始化、dynamicDataSource 先于事务管理器初始化；`@Qualifier` 注入已部分隐式保证，但显式声明更安全。
- **默认主库由 `withInitial` 兜底，与切面无关**：即使切面异常没跑，未标注的方法也走主库，不会"无库可用"。
- **`clear()` 用 `remove()` 而非 `set(MASTER)`**：`remove()` 删除覆盖值后，下次 `get()` 由 supplier 重新产出 `MASTER`；若用 `set(MASTER)` 会留下强引用值，线程复用时语义等价但不够干净。`remove()` 还能避免线程池复用导致的脏数据残留。
- **未标 `@Slave` 的读操作默认打主库**：若希望读写分离真正生效，需为只读查询显式加 `@Slave`，否则读压力仍在主库。
- **线程池/异步场景**：`ThreadLocal` 不跨线程，异步方法（`@Async`、新线程）内无法继承调用方的数据源设置，需自行在异步方法内重新标注或传递。

## 验证手段
- 观察日志中 `本次使用的数据源类型为：MASTER/SLAVE`（`DynamicDataSource` 打印）。
- 在从库执行 `SHOW PROCESSLIST` 看只读查询是否落到从库连接（pool-name `SLAVE_POOL`）。
- 写操作确认连接来自 `MASTER_POOL`。

---

# 非主从：多业务库按 DAO 包自动绑定（零注解，编译期路由）

> 与上文"主从读写分离"不同，本场景多个业务库之间是平行关系（training / qlearning / lecturer），且**业务代码不需要写任何切换注解**。数据源切换由 Mapper 接口所在的**包路径**自动决定——Spring 的 `@MapperScan` 把每个 DAO 包直接绑定到专属的 `SqlSessionFactory`/`SqlSessionTemplate`，而后者又绑定了专属 `DataSource`。调用方完全无感知，所谓"自动识别 mapper 自动切换"正是这套机制。

## 适用场景
- 系统需同时访问多个平行业务库，且各库的 Mapper 接口天然分属不同包（如 `dao.training` / `dao.qlearning` / `dao.lecturer`）。
- 库边界在编译期就固定，不需要运行时动态指定库名。
- 希望业务代码零侵入（不加注解、不碰 `ThreadLocal`），数据源选择完全由"mapper 放在哪个包"决定。
- 每个库需要独立的 MyBatis-Plus 拦截器（分页/租户等）与独立的事务管理器，实现事务隔离。

## 核心原理（自动识别 mapper → 自动切换）
1. 每个业务库对应一套独立配置类，核心是一行 `@MapperScan`：
   ```java
   @MapperScan(basePackages = "<BASE_PACKAGE>.dao.training",
           sqlSessionFactoryRef = "sqlSessionFactoryTraining",
           sqlSessionTemplateRef = "sqlSessionTemplateTraining")
   ```
2. Spring 扫描 Mapper 接口时，按接口**所在包**把它们注册到对应的 `SqlSessionFactory`；`SqlSessionFactory` 经 `@Qualifier` 绑定专属 `DataSource`、专属 `MybatisPlusInterceptor`、专属 XML 路径。
3. **"自动切换"的本质链路**：调用某 Mapper 方法 → 该 Mapper 属于某包 → 该包已被 `@MapperScan` 绑定到某 `SqlSessionFactory` → 该 Factory 用某 `DataSource`。整条链路在**启动期**就固定，运行时无需任何路由逻辑或 `ThreadLocal`。
4. `@Primary` 给默认库兜底（如 `training`），避免其它未明确绑定的 Bean 注入冲突。
5. 每套配置有独立的 `DataSourceTransactionManager`，因此跨库事务天然隔离——一个 Service 方法内若调用了不同包的 Mapper，它们各自连各自的库、各自的事务管理器（跨库分布式事务需 Seata 等方案）。

## 文件清单与职责
| 文件 | 职责 |
|---|---|
| `DataSourceConfig.java` | 创建 `trainingDataSource`(@Primary) / `qlearningDataSource` / `lecturerDataSource` 三个连接池（`@ConfigurationProperties` 绑定） |
| `TrainingSqlSessionConfig.java` | `@MapperScan("...dao.training")` → 专属 `SqlSessionFactory`/`SqlSessionTemplate` + 独立 `MybatisPlusInterceptor` + 独立 `TransactionManager` |
| `QlearningSqlSessionConfig.java` | 同上，绑定 `dao.qlearning` |
| `LecturerSqlSessionConfig.java` | 同上，绑定 `dao.lecturer` |
| `MybatisPlusConfig.java`（可选） | 为每库定义独立的 `MybatisPlusInterceptor` Bean（分页/租户等） |

## 实现代码（落地时先按"项目适配"替换包名）

### DataSourceConfig.java
```java
package <BASE_PACKAGE>.datasource;

import javax.sql.DataSource;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import com.zaxxer.hikari.HikariDataSource;
import lombok.extern.slf4j.Slf4j;

@Configuration
@Slf4j
public class DataSourceConfig {

    @Bean(name = "trainingDataSource")
    @Primary // 默认库兜底
    @ConfigurationProperties(prefix = "spring.datasource.training")
    public DataSource trainingDataSource() {
        log.info("初始化 training 数据源");
        return new HikariDataSource();
    }

    @Bean(name = "qlearningDataSource")
    @ConfigurationProperties(prefix = "spring.datasource.qlearning")
    public DataSource qlearningDataSource() {
        log.info("初始化 qlearning 数据源");
        return new HikariDataSource();
    }

    @Bean(name = "lecturerDataSource")
    @ConfigurationProperties(prefix = "spring.datasource.lecturer")
    public DataSource lecturerDataSource() {
        log.info("初始化 lecturer 数据源");
        return new HikariDataSource();
    }
}
```

### TrainingSqlSessionConfig.java
```java
package <BASE_PACKAGE>.datasource;

import javax.sql.DataSource;
import org.apache.ibatis.session.SqlSessionFactory;
import org.mybatis.spring.SqlSessionTemplate;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.PlatformTransactionManager;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;

@Configuration
// 关键：basePackages 决定哪些 Mapper 走这套数据源；sqlSessionFactoryRef/TemplateRef 绑定专属工厂
@MapperScan(basePackages = "<BASE_PACKAGE>.dao.training",
        sqlSessionFactoryRef = "sqlSessionFactoryTraining",
        sqlSessionTemplateRef = "sqlSessionTemplateTraining")
public class TrainingSqlSessionConfig {

    @Bean(name = "sqlSessionFactoryTraining")
    public SqlSessionFactory sqlSessionFactoryTraining(
            @Qualifier("trainingDataSource") DataSource dataSource) throws Exception {
        MybatisSqlSessionFactoryBean bean = new MybatisSqlSessionFactoryBean();
        bean.setDataSource(dataSource);
        // 绑定专属 MyBatis-Plus 拦截器（如分页/租户）
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor());
        bean.setPlugins(interceptor);
        // 绑定专属 XML 路径（可选）：
        bean.setMapperLocations(new PathMatchingResourcePatternResolver()
                .getResources("classpath*:mapper/training/*.xml"));
        return bean.getObject();
    }

    @Bean(name = "sqlSessionTemplateTraining")
    public SqlSessionTemplate sqlSessionTemplateTraining(
            @Qualifier("sqlSessionFactoryTraining") SqlSessionFactory sqlSessionFactory) {
        return new SqlSessionTemplate(sqlSessionFactory);
    }

    @Bean(name = "txManagerTraining") // 独立事务管理器，Bean 名必须唯一且语义正确
    public PlatformTransactionManager txManagerTraining(
            @Qualifier("trainingDataSource") DataSource dataSource) {
        return new DataSourceTransactionManager(dataSource);
    }
}
```

### QlearningSqlSessionConfig.java / LecturerSqlSessionConfig.java
> 照搬 `TrainingSqlSessionConfig`，把 `training` 全部替换为 `qlearning` / `lecturer`（包名、Bean 名、`sqlSessionFactoryRef`/`TemplateRef`、`txManager` 名、`@ConfigurationProperties` 前缀）。**注意 Bean 名与 `@Qualifier` 必须一一对应**，复制粘贴后务必改全，避免串库。

## 配置文件（application-*.yml）
```yaml
spring:
  datasource:
    training:
      driver-class-name: com.mysql.cj.jdbc.Driver
      jdbc-url: jdbc:mysql://<host>:3306/training?useUnicode=true&characterEncoding=utf-8&serverTimezone=GMT%2B8&useSSL=false
      username: <user>
      password: <pwd>
      hikari:
        minimum-idle: 10
        maximum-pool-size: 200
        pool-name: TRAINING_POOL
        connection-test-query: SELECT 1
    qlearning:
      driver-class-name: com.mysql.cj.jdbc.Driver
      jdbc-url: jdbc:mysql://<host>:3306/qlearning?useUnicode=true&characterEncoding=utf-8&serverTimezone=GMT%2B8&useSSL=false
      username: <user>
      password: <pwd>
      hikari:
        minimum-idle: 10
        maximum-pool-size: 200
        pool-name: QLEARNING_POOL
        connection-test-query: SELECT 1
    lecturer:
      driver-class-name: com.mysql.cj.jdbc.Driver
      jdbc-url: jdbc:mysql://<host>:3306/lecturer?useUnicode=true&characterEncoding=utf-8&serverTimezone=GMT%2B8&useSSL=false
      username: <user>
      password: <pwd>
      hikari:
        minimum-idle: 10
        maximum-pool-size: 200
        pool-name: LECTURER_POOL
        connection-test-query: SELECT 1
```

## 使用方式（SOP）
1. **把 Mapper 接口放到对应包**：`XxxMapper` 放 `<BASE_PACKAGE>.dao.training` 就自动走 training 库，放 `dao.qlearning` 就走 qlearning 库——**业务代码零注解、零侵入**。
2. **Service 直接注入 Mapper 使用**，无需关心数据源；数据源由包路径在启动期绑定好。
3. **跨库联合查询**：分别注入不同包的 Mapper，在 Service 层组装结果（注意跨库无数据库级事务，需业务层保证一致性或引入最终一致性方案）。
4. **加库**：新增一个 `XxxSqlSessionConfig` + 对应 DAO 包 + yml 前缀；把 Mapper 放进对应包即生效，无需改任何已有代码。

## 关键注意事项（易错点）
- **Bean 名与 `@Qualifier` 必须一一对应**：复制 `TrainingSqlSessionConfig` 生成 qlearning/lecturer 配置时，最容易漏改 `txManagerXxx` 的 Bean 名（如误写成 `txManagerQlearning` 却绑 lecturer 数据源），虽 `@Qualifier("lecturerDataSource")` 保证功能正确，但命名误导排查。
- **`@Primary` 只兜底默认库**：仅当某处注入 DataSource 未指定 Qualifier 时才生效；三套 SqlSessionConfig 都已显式 `@Qualifier`，互不干扰。
- **独立事务管理器 = 事务隔离**：每个库用自己的 `DataSourceTransactionManager`，一个事务方法内调用跨库 Mapper 不会合并成单一事务（跨库分布式事务需 Seata 等方案）。
- **XML 路径按库隔离**：若用 XML，建议 `mapper/training`、`mapper/qlearning` 分目录，并在各自 `sqlSessionFactoryXxx` 中 `setMapperLocations` 指向本库目录，避免 Mapper 错绑。
- **包路径即路由**：新增库 = 新增一个 `XxxSqlSessionConfig` + 对应 DAO 包 + yml 前缀；把 Mapper 放进对应包即生效，无需改任何已有代码。

## 验证手段
- 启动日志确认三个连接池初始化（pool-name `TRAINING_POOL` / `QLEARNING_POOL` / `LECTURER_POOL`）。
- 在目标库执行 `SHOW PROCESSLIST` 确认查询落到对应连接。
- 故意把某 Mapper 移错包，验证其查询打到了错误库（反向验证绑定生效）。
