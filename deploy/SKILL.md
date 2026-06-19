---
name: deploy
description: Use when the user wants to deploy a project, generate Docker/CI/CD files, set up GitHub Actions workflows, or create Dockerfile/compose.yaml for any project type. Triggers on requests like "deploy this", "generate Dockerfile", "set up CI/CD", "create deployment files", "add GitHub Actions", or when a project is feature-complete and ready for deployment configuration.
---

# Deploy — CI/CD & Docker 部署文件生成

## Overview

为任意项目生成生产级 Docker + GitHub Actions CI/CD 部署文件。自动检测项目类型与**既有部署文件**，只补齐缺失部分（绝不覆盖用户已有的 Dockerfile/compose），生成的 workflow 走「本地构建 → docker save → SCP → docker load → docker compose up」链路，所有密钥通过 GitHub Secrets 注入。

## When to Use

- 项目业务代码编写完成，需要快速部署
- 需要为现有项目添加 Docker 支持
- 需要配置 GitHub Actions 自动部署到远程服务器
- 从旧部署方式（如手动拉镜像 / ACR 拉取）迁移到「自建镜像 + CI 自动部署」
- 用户说 "deploy"、"部署"、"CI/CD"、"Docker 化"、"容器化"

**不适用于：**
- Kubernetes 集群部署（需要 Helm Chart）
- 多云服务商部署（如 AWS ECS、GCP Cloud Run）
- 已有完整 CI/CD 系统（如 Jenkins）且不需要迁移

## Workflow

```
用户说 /deploy
  → Step 0: 检测既有部署文件（最重要，决定增/改策略）
  → Step 1: 检测项目类型
  → Step 2: 收集部署配置（询问用户）
  → Step 3: 生成缺失/补齐的文件
  → Step 4: 【最后一步·强制】告诉用户要在 GitHub Action Secrets 配置哪些
```

## Step 0: 检测既有部署文件（关键，必做）

**在生成任何文件前，先用 MCP/Glob 工具检查仓库现状：**

| 文件 | 存在时策略 |
|------|----------|
| `Dockerfile` / `Dockerfile.dev` | ✅ **保留不动**，除非用户明确要求改写。多阶段构建通常已经很好。 |
| `docker-compose.yml` / `compose.yaml` | ✅ **保留**（这是开发/试用编排，常引用官方预构建镜像）。生产编排另起一个文件。 |
| `.dockerignore` | ✅ **保留** |
| `.github/workflows/*.yml` | ⚠️ 检查是否已有 deploy workflow，避免覆盖用户的定制逻辑 |
| `makefile` / `Makefile` | 仅参考构建命令，不修改 |
| `.gitignore` | 确认是否已忽略 `.env`（生产密钥文件），没有则建议补一行 `.env` |

**核心原则：增补 > 覆盖。** 用户的项目里已有的部署文件大概率是经过调试的，直接覆盖会丢失他们的定制（如外部网络名、卷绝对路径、加密密钥等）。

**检测既有环境的线索（决定 compose.prod.yml 怎么写）：**
- 既有 compose 是否用了 `external: true` 的网络？（如 `common-net`）→ 生产编排复用同一外部网络，**不重新创建 DB/Redis**
- 既有 compose 的 `SQL_DSN` 连的是 `mysql:` 还是 `postgres:`？→ 决定数据库类型
- 既有 compose 的 volumes 是相对路径还是绝对路径？（如 `/root/docker/xxx/data`）→ 生产编排沿用同一绝对路径，避免数据迁移
- 是否有 `SESSION_SECRET` / `CRYPTO_SECRET` / `ENCRYPTION_KEY` 之类的**应用层加密密钥**？→ **迁移时必须保留原值**（见 Step 3.3 密钥保护）

## Step 1: 项目类型检测

| 项目类型 | 检测特征 | 构建工具 | 运行时基础镜像 |
|---------|---------|---------|-------------|
| Go | `go.mod` 存在 | `go build` | `alpine:3.20` |
| Node.js | `package.json` 存在 | `npm`/`yarn`/`pnpm`/`bun` | `node:22-alpine` |
| Python | `requirements.txt`/`pyproject.toml` | `pip`/`poetry` | `python:3.12-alpine` |
| Java/Maven | `pom.xml` 存在 | `mvn` | `eclipse-temurin:21-jre-alpine` |
| Java/Gradle | `build.gradle`/`build.gradle.kts` | `gradle` | `eclipse-temurin:21-jre-alpine` |
| Rust | `Cargo.toml` 存在 | `cargo` | `alpine:3.20` |
| 静态前端 | `index.html` + 无构建工具 | 无（直接复制） | `nginx:alpine` |
| Go + 嵌入前端 | `go.mod` + `embed.FS` + `web/` | bun build + go build | `debian:bookworm-slim`（CGO/字体等依赖时） |

**额外检测：**
- 端口号：从代码或既有 compose 推断默认端口
- 数据库：检查是否使用 MySQL、PostgreSQL、Redis 等
- Web 框架：Express/FastAPI/Gin/Spring Boot 等（影响启动命令）
- **健康检查端点：** 检测项目是否有健康检查路由（如 `/api/status`、Spring Boot 的 actuator `/health`）。没有则提示用户，否则 compose healthcheck 会失败。

## Step 2: 收集部署配置

**必须向用户询问（用 AskUserQuestion 工具，不要假设默认值）：**

1. **SSH/部署目标：** SSH Host、User、Port（默认 22）、服务器部署路径。可「稍后用 Secrets 配置」。
2. **镜像分发策略：**
   - 「本地构建并上传」（`docker save` + SCP，无需 Registry，适合单服务器）—— **默认推荐**
   - 「推到镜像仓库」（GHCR/Docker Hub/ACR，服务器 pull，需 registry 凭据）
3. **触发条件：**
   - 触发分支（默认 `main`）
   - 是否路径过滤（如仅 `backend/**` 变更才触发，避免只改前端也重建）
   - 是否保留手动触发 `workflow_dispatch`（默认开启）
4. **镜像加速：** 服务器是否在国内？需要配置 Docker registry mirror 吗？
5. **版本保留：** 服务器上保留最近几个历史构建镜像？（默认 5，用于回滚）

**不要问、应从代码/既有文件推断的：**
- 应用容器端口（看既有 compose 的 `ports:` 右侧 / 程序监听端口）
- 数据库类型与连接串格式（看既有 `SQL_DSN`）
- 加密密钥名称（看既有 compose 的 environment）

## Step 3: 生成文件

### 3.1 Dockerfile — 仅在缺失时生成

**如果 `Dockerfile` 已存在，跳过本节，保留用户文件。**

多阶段构建模板见下方各语言。通用安全要求：
- 非 root 用户运行（`USER` 指令必须）
- 固定版本基础镜像（**不要用 `latest`**，用 `alpine:3.20` 这类带 tag 的）
- 多阶段构建最小化镜像体积
- 分层复制以利用缓存：先 `COPY` 依赖清单（go.mod/package.json/pom.xml），再 `COPY` 源码

**Go 项目：**
```dockerfile
# syntax=docker/dockerfile:1
FROM golang:{go_version}-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o /out/{app_name} .

FROM alpine:3.20
RUN addgroup -S app && adduser -S -G app app
WORKDIR /app
COPY --from=builder /out/{app_name} /usr/local/bin/{app_name}
RUN mkdir -p /data && chown -R app:app /data
USER app
EXPOSE {port}
VOLUME ["/data"]
ENTRYPOINT ["{app_name}"]
```

**Node.js 项目：**
```dockerfile
# syntax=docker/dockerfile:1
FROM node:{node_version}-alpine AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@latest --activate
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM node:{node_version}-alpine
RUN addgroup -S app && adduser -S -G app app
WORKDIR /app
COPY --from=builder --chown=app:app /app/{build_output} ./{build_output}
COPY --from=builder --chown=app:app /app/node_modules ./node_modules
COPY --from=builder --chown=app:app /app/package.json ./
USER app
EXPOSE {port}
CMD ["node", "{build_output}/index.js"]
```

**Python 项目：**
```dockerfile
FROM python:3.12-alpine
RUN addgroup -S app && adduser -S -G app app
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chown -R app:app /app
USER app
EXPOSE {port}
CMD ["python", "-m", "uvicorn", "{app_module}:app", "--host", "0.0.0.0", "--port", "{port}"]
```

**Java/Spring Boot 项目：**
```dockerfile
# syntax=docker/dockerfile:1
FROM maven:3.9-eclipse-temurin-21-alpine AS builder
WORKDIR /build
COPY pom.xml ./
RUN mvn dependency:go-offline -B || true
COPY src ./src
RUN mvn -B -q clean package -DskipTests
RUN find target -name "*-original.jar" -type f -delete && \
    cp $(ls -1 target/*.jar | head -n 1) /app.jar

FROM eclipse-temurin:21-jre-alpine
RUN addgroup -S app && adduser -S -G app app
WORKDIR /app
COPY --from=builder --chown=app:app /app.jar /app/app.jar
RUN mkdir -p /data/logs && chown -R app:app /data
USER app
EXPOSE {port}
VOLUME ["/data"]
ENV JAVA_OPTS="-Xms256m -Xmx512m -XX:+UseG1GC"
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /app/app.jar"]
```

### 3.2 .dockerignore — 仅在缺失时生成

通用模板（已存在则保留用户文件）：
```
.git
.gitignore
.gitattributes
README.md
docs/
.idea/
.vscode/
*.swp
node_modules/
dist/
build/
target/
*.exe
*.dll
Dockerfile
.dockerignore
docker-compose*.yml
compose*.yaml
.github/
tmp/
*.log
```

### 3.3 生产编排 `docker-compose.prod.yml` — 关键文件

**与开发用 `docker-compose.yml` 分离**：开发 compose 通常 `build: context: .` 或引用官方预构建镜像；生产 compose 引用 CI 构建并 `docker load` 进来的本地镜像 `{app_name}:latest`。

**核心设计原则（从实战经验提炼）：**

1. **所有敏感值通过环境变量 + `.env` 注入**，用 `${VAR:?错误提示}` 做必填校验（缺失立即报错退出，比静默用空值安全）：
   ```yaml
   SQL_DSN: ${SQL_DSN:?请在 GitHub Action secret 中设置 SQL_DSN}
   ```
2. **可选项用默认值语法** `${VAR:-default}`：
   ```yaml
   ports:
     - "${NEW_API_PORT:-8085}:3000"   # 不配 secret 就用 8085
   ```
3. **复用既有外部网络**（DB/Redis 已在其他 compose 跑着时），**不要在本 compose 重建它们**：
   ```yaml
   networks:
     common-net:
       external: true
   ```
4. **沿用既有 volume 绝对路径**，避免数据迁移：
   ```yaml
   volumes:
     - ${DATA_DIR:-/root/docker/{app}}/data:/data
   ```
5. **加密密钥必须显式声明且校验**（见下方「密钥保护」）。

**完整模板（适配外部 DB/Redis 场景）：**
```yaml
# {app_name} 自建镜像部署编排
# 镜像由 CI 构建并通过 docker load 加载，密钥全部来自 GitHub Secrets 生成的 .env
name: {app_name}

services:
  {app_name}:
    image: {app_name}:latest          # CI 构建并通过 docker load 加载
    container_name: {app_name}
    restart: always
    command: --log-dir /app/logs
    ports:
      - "${APP_PORT:-8085}:3000"      # 宿主机端口:容器端口，端口看程序监听
    volumes:
      - ${DATA_DIR:-/root/docker/{app_name}}/data:/data
      - ${DATA_DIR:-/root/docker/{app_name}}/logs:/app/logs
    environment:
      TZ: Asia/Shanghai
      # 必填：缺失会报错（:? 校验）
      SQL_DSN: ${SQL_DSN:?请在 GitHub Action secret 中设置 SQL_DSN}
      # 可选：有默认值
      REDIS_CONN_STRING: ${REDIS_CONN_STRING:-redis://redis:6379}
      # ⚠️ 加密密钥：首次设置后不可更改（见密钥保护）
      SESSION_SECRET: ${SESSION_SECRET:?请在 GitHub Action secret 中设置 SESSION_SECRET}
      CRYPTO_SECRET: ${CRYPTO_SECRET:?请在 GitHub Action secret 中设置 CRYPTO_SECRET}
    healthcheck:
      test: ["CMD-SHELL", "wget -q -O - http://localhost:3000/api/status | grep -o '\"success\":\\s*true' || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - common-net

networks:
  common-net:
    external: true
```

**模板：本 compose 自带数据库（无外部 DB 时）：**
```yaml
services:
  {app_name}:
    image: {app_name}:latest
    # ... 同上
    environment:
      - SQL_DSN=postgresql://${DB_USER:-app}:${DB_PASSWORD:?请设置 DB_PASSWORD}@postgres:5432/${DB_NAME:-app}
    depends_on: [postgres, redis]
    networks: [app-net]

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${DB_USER:-app}
      POSTGRES_PASSWORD: ${DB_PASSWORD:?请设置 DB_PASSWORD}
      POSTGRES_DB: ${DB_NAME:-app}
    volumes:
      - pg-data:/var/lib/postgresql/data
    networks: [app-net]

  redis:
    image: redis:alpine
    networks: [app-net]

volumes:
  pg-data:
networks:
  app-net:
    driver: bridge
```

> **日志目录设计：** 运行时数据（日志/缓存/上传）统一写到 `/data` 下，不写程序目录。compose 用 `./logs:/data/logs` bind mount，服务器侧 `mkdir -p logs && chmod 777 logs`。

#### 🔑 密钥保护（极重要，从血泪经验提炼）

很多应用有一类「**应用层加密密钥**」，用于加密数据库里存储的敏感数据（API Key、渠道凭据、OAuth token 等）。常见名字：

- `CRYPTO_SECRET` / `ENCRYPTION_KEY` / `AES_KEY`
- `SESSION_SECRET` / `JWT_SECRET`（签名用，改了顶多让会话失效）

**迁移/重新部署这类应用时：**
1. **必须从既有部署照抄原值**，绝对不能生成新随机值。
2. **更换 `CRYPTO_SECRET` 等加密密钥 = 数据库中所有已加密数据永久不可解密**（不可逆，只能重置所有受影响记录）。
3. 在 compose 中给这类密钥加显式注释警告：
   ```yaml
   # ⚠️ 以下密钥首次设置后切勿更改！更换会导致已加密的渠道凭据无法解密！
   CRYPTO_SECRET: ${CRYPTO_SECRET:?请设置 CRYPTO_SECRET}
   ```
4. 在生成的 GitHub Secrets 清单里，对这类密钥标注「**保留原值**」并附上既有值供用户核对。

### 3.4 `.env` 由 CI 生成（不在仓库维护）

**不要**生成 `.env.example` / `.env.template` 让用户在服务器手动编辑。改为：**在 workflow runner 上用 `printf` 从 GitHub Secrets 逐行生成 `.env`，每次部署 scp 覆盖到服务器**。

好处：
- 密钥唯一真源是 GitHub Secrets，服务器不需要手动维护 `.env`
- 不会出现「首次部署用了模板里的占位符密码起库」的事故
- 避免密钥散落在服务器文件系统

实现见 Step 3.5 的 deploy step。

> ⚠️ 确认 `.gitignore` 已忽略 `.env`（runner 上生成的临时 .env 不应被 commit）。

### 3.5 GitHub Actions Workflow — `.github/workflows/deploy.yml`

**已存在 deploy workflow 时，先读现有逻辑，避免覆盖用户定制。**

**完整模板（本地构建上传 + 双标签版本保留 + 国内镜像加速 + 密钥走 secrets）：**

```yaml
name: Deploy to Server

on:
  push:
    branches:
      - {deploy_branch}      # 默认 main
    # paths:                  # 可选路径过滤
    #   - backend/**
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 60

    env:
      IMAGE_NAME: {app_name}
      IMAGE_TAG: latest                  # 可滚动标签，compose 永远引用
      IMAGE_VER_TAG: ${{ github.run_number }}   # 构建号标签（递增），历史版本保留用
      IMAGE_TAR: {app_name}.tar.gz
      KEEP_VERSIONS: "5"                 # 保留最近 N 个构建号镜像

    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          ref: {deploy_branch}

      # 国内服务器：配置 Docker 镜像加速
      - name: Configure Docker registry mirror
        if: ${{ secrets.DOCKER_MIRROR_URL != '' }}
        run: |
          set -euo pipefail
          sudo mkdir -p /etc/docker
          sudo tee /etc/docker/daemon.json > /dev/null <<EOF
          {
            "registry-mirrors": ["${{ secrets.DOCKER_MIRROR_URL }}"],
            "max-concurrent-downloads": 10,
            "max-concurrent-uploads": 5
          }
          EOF
          sudo systemctl restart docker
          sleep 5
          docker info | grep -A 5 "Registry Mirrors" || true

      - name: Build Docker image
        run: |
          set -euo pipefail
          echo "Building ${IMAGE_NAME}:${IMAGE_TAG} (= build #${IMAGE_VER_TAG})"
          # 双标签：latest 滚动 + 构建号唯一（用于回滚与历史保留）
          docker build --progress=plain \
            -t "${IMAGE_NAME}:${IMAGE_TAG}" \
            -t "${IMAGE_NAME}:${IMAGE_VER_TAG}" .
          docker images "${IMAGE_NAME}"
          echo "Saving image to ${IMAGE_TAR}"
          docker save "${IMAGE_NAME}:${IMAGE_TAG}" "${IMAGE_NAME}:${IMAGE_VER_TAG}" | gzip > "${IMAGE_TAR}"
          ls -lh "${IMAGE_TAR}"

      - name: Deploy to server
        env:
          SSH_HOST: ${{ secrets.SSH_HOST }}
          SSH_USER: ${{ secrets.SSH_USER }}
          SSH_KEY: ${{ secrets.SSH_KEY }}
          SSH_PORT: ${{ secrets.SSH_PORT }}
          DEPLOY_PATH: ${{ secrets.DEPLOY_PATH }}
          # 应用配置（全部来自 secrets，不在服务器维护 .env）
          APP_PORT: ${{ secrets.APP_PORT }}
          DATA_DIR: ${{ secrets.DATA_DIR }}
          SQL_DSN: ${{ secrets.SQL_DSN }}
          REDIS_CONN_STRING: ${{ secrets.REDIS_CONN_STRING }}
          SESSION_SECRET: ${{ secrets.SESSION_SECRET }}
          CRYPTO_SECRET: ${{ secrets.CRYPTO_SECRET }}
        run: |
          set -euo pipefail
          # 必填校验
          : "${SSH_HOST:?missing SSH_HOST secret}"
          : "${SSH_USER:?missing SSH_USER secret}"
          : "${SSH_KEY:?missing SSH_KEY secret}"
          : "${DEPLOY_PATH:?missing DEPLOY_PATH secret}"
          : "${SQL_DSN:?missing SQL_DSN secret}"
          : "${SESSION_SECRET:?missing SESSION_SECRET secret}"
          : "${CRYPTO_SECRET:?missing CRYPTO_SECRET secret}"

          SSH_PORT="${SSH_PORT:-22}"

          # 配置 SSH
          mkdir -p ~/.ssh && chmod 700 ~/.ssh
          printf '%s\n' "$SSH_KEY" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          ssh-keyscan -p "$SSH_PORT" -t rsa,ecdsa,ed25519 "$SSH_HOST" >> ~/.ssh/known_hosts 2>/dev/null || true

          # 在 runner 上从 secrets 生成 .env（值原样写入，不经 shell 二次解释，避免日志泄露）
          echo "Generating .env from secrets..."
          {
            printf 'APP_PORT=%s\n' "${APP_PORT:-8085}"
            printf 'DATA_DIR=%s\n' "${DATA_DIR:-/root/docker/{app_name}}"
            printf 'SQL_DSN=%s\n' "$SQL_DSN"
            printf 'REDIS_CONN_STRING=%s\n' "${REDIS_CONN_STRING:-redis://redis:6379}"
            printf 'SESSION_SECRET=%s\n' "$SESSION_SECRET"
            printf 'CRYPTO_SECRET=%s\n' "$CRYPTO_SECRET"
          } > .env
          chmod 600 .env

          # 确保部署目录 + 同步 compose 与 .env
          ssh -i ~/.ssh/deploy_key -p "$SSH_PORT" -o StrictHostKeyChecking=accept-new \
            "${SSH_USER}@${SSH_HOST}" "mkdir -p '$DEPLOY_PATH'"
          scp -i ~/.ssh/deploy_key -P "$SSH_PORT" docker-compose.prod.yml .env \
            "${SSH_USER}@${SSH_HOST}:$DEPLOY_PATH/"

          # 上传镜像
          scp -i ~/.ssh/deploy_key -P "$SSH_PORT" "${IMAGE_TAR}" \
            "${SSH_USER}@${SSH_HOST}:$DEPLOY_PATH/${IMAGE_TAR}"

          # 远程部署
          ssh -i ~/.ssh/deploy_key -p "$SSH_PORT" \
            "${SSH_USER}@${SSH_HOST}" \
            "DEPLOY_PATH='$DEPLOY_PATH' IMAGE_TAR='$IMAGE_TAR' IMAGE_NAME='$IMAGE_NAME' KEEP_VERSIONS='$KEEP_VERSIONS' bash -s" <<'REMOTE'
          set -euo pipefail
          echo "=== Starting deployment ==="
          cd "$DEPLOY_PATH"

          # 日志/数据目录权限
          mkdir -p logs data && chmod -R 777 logs

          # 复用既有外部网络（DB/Redis 在其上）
          docker network inspect common-net >/dev/null 2>&1 || docker network create common-net

          echo "Stopping old containers..."
          docker compose -f docker-compose.prod.yml down --remove-orphans 2>/dev/null || true

          echo "Loading Docker image..."
          docker load < "$IMAGE_TAR"

          echo "Starting services..."
          docker compose -f docker-compose.prod.yml --env-file .env up -d --no-build

          # 清理：保留最近 N 个构建号镜像，删多余；latest 永不删
          echo "Cleaning up..."
          rm -f "$IMAGE_TAR"
          KEEP="${KEEP_VERSIONS:-5}"
          docker image prune -f 2>/dev/null || true
          docker images "$IMAGE_NAME" --format '{{.Tag}} {{.ID}}' \
            | grep -v '<none>' \
            | grep -v '^latest ' \
            | sort -t' ' -k1 -n -r \
            | tail -n +"$((KEEP + 1))" \
            | awk '{print $2}' \
            | while read -r id; do
                echo "Removing old image: $id"
                docker rmi "$id" 2>/dev/null || true
              done

          echo "=== Remaining $IMAGE_NAME images ==="
          docker images "$IMAGE_NAME"
          echo "=== Running containers ==="
          docker compose -f docker-compose.prod.yml ps
          echo "=== Deployment completed ==="
          REMOTE

      - name: Cleanup runner artifacts
        if: always()
        run: |
          rm -f "$IMAGE_TAR" .env
          echo "Cleaned up local tarball and generated .env"
```

#### 双标签版本保留机制（关键设计）

单用 `:latest` 无法保留历史（每次覆盖只留 1 个）。必须双标签：

| 标签 | 来源 | 行为 | 作用 |
|------|------|------|------|
| `:latest` | 固定 | 每次滚动更新指向最新构建 | compose 引用，`up -d` 自动最新 |
| `:<run_number>` | `github.run_number`（递增 1/2/3…） | 打上后不动 | 历史快照，回滚用 |

**清理逻辑**：保留最近 N 个构建号标签（按数字倒序），删多余；`latest` 始终豁免（正在运行）。磁盘最终 = `latest` + 最近 N 个。

**回滚示例**：
```bash
docker tag {app_name}:42 {app_name}:latest
docker compose -f docker-compose.prod.yml --env-file .env up -d --no-build
```

## Step 4: 【最后一步·强制】告诉用户要在 GitHub Action Secrets 配置哪些

**这是 /deploy 的收尾必做步骤，不可省略。** 生成完所有文件后，**最后一条消息必须**是面向用户的「Secrets 配置清单」，明确列出：

1. **必须配置**的 secrets（少一个 workflow 直接报错退出）
2. **可选配置**的 secrets（有默认值）
3. **加密密钥**类的特别警告（保留既有原值）

### Secrets 分类清单（基础表，按项目实际情况增删）

| Secret | 必填 | 说明 / 示例 |
|--------|:---:|------|
| `SSH_HOST` | ✅ | 服务器 IP/域名，如 `1.2.3.4` |
| `SSH_USER` | ✅ | SSH 用户，如 `root` |
| `SSH_KEY` | ✅ | SSH **私钥完整内容**（含 `-----BEGIN…-----END…-----`，不是路径） |
| `DEPLOY_PATH` | ✅ | 服务器部署目录，如 `/root/docker/{app}` |
| `SQL_DSN` | ✅ | 数据库连接串（按项目 DB 类型，MySQL: `user:pwd@tcp(host:3306)/db`） |
| `SESSION_SECRET` | ✅* | 会话签名密钥（**保留既有原值**） |
| `CRYPTO_SECRET` | ✅* | 应用层加密密钥（**保留既有原值！换了已加密数据永久不可解密**） |
| `SSH_PORT` | ⬜ | 默认 `22` |
| `APP_PORT` | ⬜ | 默认 `8085`（即 `8085:3000` 的宿主机端口） |
| `DATA_DIR` | ⬜ | 默认 `/root/docker/{app}` |
| `REDIS_CONN_STRING` | ⬜ | 默认 `redis://redis:6379` |
| `DOCKER_MIRROR_URL` | ⬜ | 国内服务器强烈建议配（阿里云等加速地址） |

\* 加密类密钥：**仅当应用本身有这类密钥时才必填**；若有，必须保留既有部署的原值，绝不可生成新随机值。

### 生成后的收尾输出（固定模板，必须按此结构输出）

每次完成 /deploy，**最后一条消息**按下面结构收尾（把 `{占位符}` 替换成实际值，不要留 `[列出]` 这种空占位）：

```markdown
## ✅ 部署文件已生成

已创建/更新：
- `docker-compose.prod.yml` - 生产编排（密钥走 .env，由 CI 从 secrets 生成）
- `.github/workflows/deploy.yml` - GitHub Actions（本地构建 + 双标签 + 保留最近 5 个版本）
- [Dockerfile / .dockerignore：仅在缺失时生成，否则标注「保留既有」]

---

## ⚙️ 配置 GitHub Action Secrets（部署前必做）

仓库 → Settings → Secrets and variables → Actions → New repository secret

### 🔴 必须配置（缺一不可）
| Secret | 值 |
|--------|---|
| `SSH_HOST` | <服务器 IP> |
| `SSH_USER` | root |
| `SSH_KEY` | <粘贴 SSH 私钥完整内容> |
| `DEPLOY_PATH` | <如 /root/docker/{app}> |
| `SQL_DSN` | <如 newapi:pwd@tcp(mysql:3306)/new-api> |
| `SESSION_SECRET` | <既有原值，保留不变> |
| `CRYPTO_SECRET` | <既有原值，⚠️ 保留不变！换了已加密凭据不可解密> |

### 🟢 可选配置（不配用默认值）
| Secret | 默认值 | 何时配 |
|--------|--------|--------|
| `SSH_PORT` | 22 | SSH 非 22 端口时 |
| `APP_PORT` | 8085 | 改宿主机端口时 |
| `DATA_DIR` | /root/docker/{app} | 换数据目录时 |
| `REDIS_CONN_STRING` | redis://redis:6379 | Redis 有密码/换地址时 |
| `DOCKER_MIRROR_URL` | (无) | 国内服务器强烈建议配 |

---

## 🚀 接下来

1. 服务器装 Docker（如未装）：`curl -fsSL https://get.docker.com | sh`
2. 推送触发部署：`git push origin {branch}`
3. 查看状态：GitHub → Actions
4. 回滚到第 N 次构建：
   `docker tag {app}:N {app}:latest && docker compose -f docker-compose.prod.yml --env-file .env up -d --no-build`
```

> ⚠️ **注意**：清单里的 secret 必须填**实际推断出的值或既有原值**，不能是 `changeme` 之类占位符。加密密钥必须在表格里明确写「保留原值」并附上既有值供用户核对。

## 关键设计决策

| 决策 | 原因 |
|------|------|
| Step 0 先检测既有文件，增量补齐 | 避免覆盖用户调试好的 Dockerfile/compose 定制 |
| 生产编排与开发编排分离（`.prod.yml`） | 开发用 build context / 官方镜像；生产用 CI load 的本地镜像 |
| 镜像用 `docker save` + SCP | 无需自建 Registry，单服务器最简 |
| `.env` 由 CI 在 runner 上从 secrets 生成 | 密钥唯一真源在 GitHub，服务器零配置 |
| `${VAR:?error}` 必填校验 | 缺失密钥立即报错，杜绝空值/占位符起库 |
| 双标签 latest + run_number | latest 滚动更新 + 构建号保留历史，支持回滚 |
| 保留最近 N 个构建号 | 平衡磁盘占用与回滚能力，默认 5 |
| 复用既有外部网络 | 不重建 DB/Redis，沿用既有数据卷 |
| 加密密钥标注「保留原值」 | 更换会导致数据库已加密数据永久不可解密 |
| 非 root 运行 + 固定 tag 镜像 | 安全最佳实践 |
| `printf '%s\n'` 写 .env 而非 heredoc | 值不经 shell 二次解释，避免 secret 在日志泄露 |
| `if: always()` 清理 runner 上 .env | 避免 secret 残留 CI |

## Common Mistakes

| 问题 | 原因 | 修复 |
|------|------|------|
| 覆盖了用户的 Dockerfile | 没做 Step 0 检测 | 先检查既有文件，已有则保留 |
| 用占位符密码起库（如 `changeme`） | compose 给了默认密码值 | 敏感值用 `${VAR:?}` 校验，缺失就报错；.env 由 secrets 生成 |
| 重新部署后所有渠道 API Key 失效 | 换了 `CRYPTO_SECRET` 等加密密钥 | 必须保留既有部署的原值 |
| `:latest` 单标签，无法回滚 | latest 每次覆盖 | 双标签 latest + run_number |
| 旧镜像排序用字典序删错版本 | tag 是字符串非数字 | 用 `sort -n -r` 按数字倒序 |
| 服务器磁盘被旧镜像撑爆 | 没清理或清理过度删了运行中镜像 | 保留最近 N 个 + `latest` 始终豁免 |
| SSH 连接失败 | Secret 里是路径不是私钥内容 | SSH_KEY 存完整私钥（含 BEGIN/END） |
| 镜像构建超时 | timeout 太短 | 设 `timeout-minutes: 60`，国内配镜像加速 |
| 容器启动立即退出 | 端口占用或启动命令错 | `docker logs {container}` 看错 |
| 国内 CI 拉基础镜像超时 | 没配 registry mirror | 加 `DOCKER_MIRROR_URL` secret + 配置 daemon.json |
| 日志写入 403 | 容器内日志目录无权限 | bind mount `./logs` + 服务器 `mkdir logs && chmod 777` |
| healthcheck 失败 | 没有 health 端点 | 确认有 `/health` 或 `/api/status` 路由 |
| 外部网络 DB 连不上 | compose 重建了 DB 服务 | 复用既有 `external: true` 网络，不重建 DB |

## 扩展：添加反向代理（Caddy）

如用户有域名，在 `docker-compose.prod.yml` 加 Caddy：
```yaml
  caddy:
    image: caddy:2-alpine
    container_name: {app_name}-caddy
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-data:/data
      - caddy-config:/config
    networks: [common-net]

volumes:
  caddy-data:
  caddy-config:
```
Caddyfile：
```
example.com {
    reverse_proxy {app_name}:3000
}
```
