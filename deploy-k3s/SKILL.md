---
name: deploy-k3s
description: Use when the user wants to deploy a project to a k3s / Kubernetes cluster via GitHub Actions — generating Deployment/Service/Ingress manifests, a kubectl-based deploy workflow (deploy-k3s.yml), ServiceAccount RBAC, or migrating an existing Docker/SSH deployment to k3s. Triggers on "部署到 k3s", "deploy to k8s", "k3s CI/CD", "kubectl apply in GitHub Actions", "nodeSelector / 调度到某类节点", "cloudflared tunnel 到集群".
---

# Deploy-k3s — GitHub Actions 部署到 k3s 集群

## Overview

为项目生成「GitHub Actions 构建镜像 → 推送镜像仓库 → kubectl apply 到 k3s」的部署链路：

- 镜像推到私有仓库（ACR/GHCR 等），集群用 `imagePullSecret` 拉取
- 清单是一份 `deploy/k8s/app.yaml` 模板，workflow 用 `envsubst` 按分支渲染（测试/正式两套）
- 运行配置全部来自 GitHub Secrets，workflow 每次同步成集群 `Secret`（`envFrom` 注入）
- 部署账号是**命名空间级** ServiceAccount 的 kubeconfig（`KUBECONFIG_B64`）
- 对外访问：Traefik Ingress（可配合 cloudflared tunnel），不使用 NodePort

与 `deploy` skill（docker save + SCP + compose）互补：已有 Docker 部署的项目，**保留原 workflow，新增 `deploy-k3s.yml`**，两者都可手动选择运行。

## When to Use

- 已有 k3s/k8s 集群，要把项目用 CI 部署上去
- 从「SSH + docker run」迁移到 k3s，并且要保留旧方式作为备选
- 需要按节点标签调度（如 `size=small`）、节点宕机自动迁移
- 用 cloudflared tunnel / Traefik 做域名入口

**不适用于：** 需要 Helm Chart / ArgoCD GitOps 的场景；多集群；有状态数据库本身上集群（本 skill 假设 DB/Redis 在集群外或已有）。

## Workflow

```
  → Step 0: 检测既有部署文件与集群现状（决定增/改策略）
  → Step 1: 检测项目类型、端口、健康检查、前端形态
  → Step 2: 收集部署配置（AskUserQuestion）
  → Step 3: 生成 Dockerfile（必要时）/ app.yaml / deploy-k3s.yml / RBAC
  → Step 4: 【最后一步·强制】输出集群前置条件 + Secrets 清单 + 发布/回滚步骤
```

## Step 0: 检测既有部署文件与集群现状

| 文件 / 信息 | 策略 |
|---|---|
| `Dockerfile`（含 `backend/Dockerfile`） | **保留不动**。前后端一体等新需求另建根目录 `Dockerfile`，避免影响旧 workflow 的构建上下文 |
| `.github/workflows/deploy*.yml` | **保留**旧的 docker 部署 workflow，只按用户要求调整触发方式；k3s 新建 `deploy-k3s.yml` |
| `application-*.yml` / `.env` 中的 DB、Redis 地址 | 决定在集群里怎么连（直接 IP、Secret 覆盖、还是 Service+EndpointSlice） |
| 应用的真实 IP 获取逻辑（如 `IpUtil`、限流过滤器） | 经 Ingress 后 `X-Forwarded-For` 可能被改写，见 Common Mistakes |
| 前端是否独立部署（nginx 静态目录） | 决定是否打进同一镜像 |

**让用户在集群上跑（或请用户提供输出），不要猜：**
```bash
kubectl get nodes --show-labels          # 节点标签（nodeSelector 用）
kubectl get ingressclass                 # 通常是 traefik
kubectl get svc -A                       # 端口占用、已有服务命名风格
kubectl -n kube-system get pods -o wide | grep svclb   # ServiceLB 在哪些节点
```

## Step 1: 项目检测

- **端口**：看 `server.port` / 程序监听端口
- **健康检查**：Spring Boot 用 `/actuator/health`（确认 Security 放行）；没有就提示用户加
- **JVM 项目**：读 Dockerfile 里的 `JAVA_OPTS`，Pod 的内存 limit 必须覆盖 JVM 总占用（见 3.2）
- **前端**：Vite/Vue 等 SPA 若用 hash 路由，可直接放进 Spring Boot `classpath:/static`，无需路由回退；history 路由需额外 fallback
- **Redis/MySQL 默认值**：看 yml 的 `${VAR:default}`，决定哪些 env 只在 secret 非空时注入（空字符串会覆盖默认值）

## Step 2: 收集部署配置（AskUserQuestion，不要假设）

1. **集群访问方式**：kubeconfig secret（推荐，`KUBECONFIG_B64`）/ SSH 到主节点 / 自托管 runner。
   - kubeconfig 的 `server:` 必须是 **GitHub runner 可达**的地址（不能是 127.0.0.1 或 Tailscale 100.x），证书需含该地址（k3s `--tls-san`）
2. **调度**：节点标签 key=value（如 `size=small`），副本数
3. **对外入口**：Traefik Ingress + 域名（测试/正式各一个）/ cloudflared tunnel → Traefik / 仅集群内
4. **前端**：打进后端镜像 / 单独镜像 / 保持原服务器
5. **触发方式**：手动 `workflow_dispatch`（按分支区分环境）/ push 自动
6. **镜像仓库**：ACR / GHCR / Docker Hub（凭据 secrets 名）
7. **DB/Redis 位置**：集群外主机 IP / 集群内 Service

## Step 3: 生成文件

### 3.1 根目录一体镜像 Dockerfile（仅当前端要打进后端镜像时）

构建上下文为仓库根目录，旧 workflow 继续用 `backend/Dockerfile`：

```dockerfile
## ===== 前端构建 =====
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

## ===== Maven 构建：把 dist 放进 classpath:/static =====
FROM {maven_image} AS builder
WORKDIR /build
COPY backend/pom.xml ./
RUN mvn dependency:go-offline -B || true
COPY backend/src ./src
COPY --from=frontend /frontend/dist ./src/main/resources/static
RUN mvn -B -q clean package -DskipTests && \
    find target -name "*-original.jar" -delete && cp $(ls -1 target/*.jar | head -n 1) /app.jar

## ===== 运行时 =====
FROM {jre_image}
# ... 非 root 用户、时区、EXPOSE {port}
COPY --from=builder /app.jar /app/app.jar
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /app/app.jar"]
```

配套：
- 根目录 `.dockerignore`：排除 `.git .github docs deploy **/node_modules **/dist **/target **/logs`
- 后端加静态资源缓存：`/assets/**` 带内容哈希 → `max-age=365d, immutable`；`index.html` 交给 Spring Security 默认 `no-store`
- `server.compression.enabled=true`（text/html、css、js、json、svg），减少回源流量
- 本地开发不受影响：Vite `server.proxy` 把 `/api` 代理到后端

### 3.2 清单模板 `deploy/k8s/app.yaml`

占位符由 workflow `envsubst` 渲染：`${APP_NAME} ${IMAGE} ${BUILD_NUMBER} ${HOST} ${RUN_ID}`。

```yaml
# 对外：cloudflared tunnel → Traefik → Ingress（按 Host）→ Service → Pod
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${APP_NAME}
  namespace: default
  labels:
    app: ${APP_NAME}
spec:
  replicas: 1
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      app: ${APP_NAME}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: ${APP_NAME}
        build: "${BUILD_NUMBER}"
      annotations:
        # 每次运行都变 → Secret 更新后也会滚动重建 Pod
        kblog/run-id: "${RUN_ID}"
    spec:
      nodeSelector:
        {node_label_key}: {node_label_value}
      # 节点宕机 30 秒后迁移（默认 5 分钟）
      tolerations:
        - key: node.kubernetes.io/unreachable
          operator: Exists
          effect: NoExecute
          tolerationSeconds: 30
        - key: node.kubernetes.io/not-ready
          operator: Exists
          effect: NoExecute
          tolerationSeconds: 30
      imagePullSecrets:
        - name: {registry_secret}
      containers:
        - name: app
          image: ${IMAGE}
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: {port}
          envFrom:
            - secretRef:
                name: ${APP_NAME}-env
          env:
            - name: SPRING_PROFILES_ACTIVE
              value: prod
            # JVM：覆盖镜像默认 -Xmx，堆 + 元空间 + 代码缓存 + 线程栈 必须 < limits
            - name: JAVA_OPTS
              value: "-Xms256m -Xmx384m -XX:MaxMetaspaceSize=192m -XX:ReservedCodeCacheSize=64m -Xss512k -XX:+UseG1GC -XX:+ExitOnOutOfMemoryError"
          # request = limit：调度器按真实占用判断，装不下就 Pending，不压垮节点
          resources:
            requests:
              cpu: 100m
              memory: 768Mi
            limits:
              memory: 768Mi
          startupProbe:
            httpGet: { path: {health_path}, port: http }
            periodSeconds: 5
            failureThreshold: 36
          readinessProbe:
            httpGet: { path: {health_path}, port: http }
            periodSeconds: 10
          # 存活只看端口，DB/Redis 抖动时不反复重启
          livenessProbe:
            tcpSocket: { port: http }
            periodSeconds: 20
---
apiVersion: v1
kind: Service
metadata:
  name: ${APP_NAME}
  namespace: default
  labels:
    app: ${APP_NAME}
spec:
  selector:
    app: ${APP_NAME}
  ports:
    - name: http
      port: 80
      targetPort: http
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ${APP_NAME}
  namespace: default
  labels:
    app: ${APP_NAME}
spec:
  ingressClassName: traefik
  rules:
    - host: ${HOST}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ${APP_NAME}
                port:
                  number: 80
```

- Service 用 **ClusterIP**，不用 NodePort（30000–32767 端口难管理、无 HTTPS、与集群其他服务风格不一致）
- 需要 HTTPS 入口（不经 tunnel）时 Ingress 加 `traefik.ingress.kubernetes.io/router.entrypoints: websecure`、`router.tls: "true"` 和 `tls.secretName`
- 所有资源都带 `app` 标签，便于 `kubectl get deploy,pods,svc,ingress -l app=...`

### 3.3 Workflow `.github/workflows/deploy-k3s.yml`

```yaml
name: Deploy to k3s

# 仅手动触发：Actions 页面选本 workflow + 分支（dev → 测试，main → 正式）
on:
  workflow_dispatch:
    inputs:
      rollback_tag:
        description: "可选：回滚的镜像标签，如 k3s-{app}-test-42；留空则正常构建部署"
        required: false
        default: ""
        type: string

concurrency:
  group: deploy-k3s-{app}-${{ github.ref_name }}
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    env:
      BUILD_NUMBER: ${{ github.run_number }}
    steps:
      - uses: actions/checkout@v4

      - name: Set deployment context
        id: ctx
        run: |
          if [[ "${GITHUB_REF_NAME}" == "dev" ]]; then
            echo "app_name={app}-test" >> "$GITHUB_OUTPUT"
            echo "host={test_domain}" >> "$GITHUB_OUTPUT"
          else
            echo "app_name={app}" >> "$GITHUB_OUTPUT"
            echo "host={prod_domain}" >> "$GITHUB_OUTPUT"
          fi

      - name: Login to registry
        if: ${{ inputs.rollback_tag == '' }}
        env:
          REGISTRY: ${{ secrets.REGISTRY }}
          REGISTRY_USERNAME: ${{ secrets.REGISTRY_USERNAME }}
          REGISTRY_PASSWORD: ${{ secrets.REGISTRY_PASSWORD }}
        run: echo "$REGISTRY_PASSWORD" | docker login "$REGISTRY" -u "$REGISTRY_USERNAME" --password-stdin

      # 标签带 k3s- 前缀：与其他 workflow 的 run_number 隔离（各 workflow 构建号独立计数）
      - name: Build and push image
        if: ${{ inputs.rollback_tag == '' }}
        env:
          APP_NAME: ${{ steps.ctx.outputs.app_name }}
          REGISTRY: ${{ secrets.REGISTRY }}
        run: |
          set -euo pipefail
          IMAGE="${REGISTRY}/{namespace}/{repo}"
          docker build --progress=plain \
            -t "${IMAGE}:k3s-${APP_NAME}-${BUILD_NUMBER}" \
            -t "${IMAGE}:k3s-${APP_NAME}-latest" \
            --build-arg BUILD_NUMBER="${BUILD_NUMBER}" \
            -f Dockerfile .
          docker push "${IMAGE}:k3s-${APP_NAME}-${BUILD_NUMBER}"
          docker push "${IMAGE}:k3s-${APP_NAME}-latest"

      - name: Set kubeconfig
        run: |
          mkdir -p ~/.kube
          echo "${{ secrets.KUBECONFIG_B64 }}" | base64 -d > ~/.kube/config

      - name: Deploy to k3s
        env:
          APP_NAME: ${{ steps.ctx.outputs.app_name }}
          HOST: ${{ steps.ctx.outputs.host }}
          RUN_ID: ${{ github.run_id }}
          ROLLBACK_TAG: ${{ inputs.rollback_tag || '' }}
          REGISTRY: ${{ secrets.REGISTRY }}
          REGISTRY_USERNAME: ${{ secrets.REGISTRY_USERNAME }}
          REGISTRY_PASSWORD: ${{ secrets.REGISTRY_PASSWORD }}
          # 应用配置：按项目增删
          DB_PASSWORD: ${{ secrets.DB_PASSWORD }}
          DB_HOST: ${{ secrets.DB_HOST }}
          REDIS_HOST: ${{ secrets.REDIS_HOST }}
        run: |
          set -euo pipefail
          IMAGE_REPO="${REGISTRY}/{namespace}/{repo}"
          if [[ -n "$ROLLBACK_TAG" ]]; then
            [[ "$ROLLBACK_TAG" =~ ^k3s-${APP_NAME}-[0-9]+$ ]] || { echo "Invalid rollback_tag"; exit 1; }
            TAG="$ROLLBACK_TAG"; DEPLOY_BUILD_NUMBER="${ROLLBACK_TAG##*-}"
          else
            TAG="k3s-${APP_NAME}-${BUILD_NUMBER}"; DEPLOY_BUILD_NUMBER="$BUILD_NUMBER"
          fi

          # 部署账号只有命名空间权限：不要查询 nodes 等集群级资源
          echo "=== [1/4] Check cluster ==="
          kubectl version

          echo "=== [2/4] Sync secrets ==="
          kubectl -n default create secret docker-registry {registry_secret} \
            --docker-server="$REGISTRY" --docker-username="$REGISTRY_USERNAME" \
            --docker-password="$REGISTRY_PASSWORD" \
            --dry-run=client -o yaml | kubectl apply -f -

          ENV_FILE="$(mktemp)"; trap 'rm -f "$ENV_FILE"' EXIT
          {
            echo "DB_PASSWORD=$DB_PASSWORD"
            # 有默认值的配置：secret 非空才注入，否则空字符串会覆盖 yml 默认值
            if [[ -n "$DB_HOST" ]]; then echo "DB_HOST=$DB_HOST"; fi
            if [[ -n "$REDIS_HOST" ]]; then echo "REDIS_HOST=$REDIS_HOST"; fi
          } > "$ENV_FILE"
          kubectl -n default create secret generic "${APP_NAME}-env" \
            --from-env-file="$ENV_FILE" --dry-run=client -o yaml | kubectl apply -f -

          echo "=== [3/4] Apply Deployment/Service/Ingress ==="
          export APP_NAME HOST RUN_ID
          export IMAGE="${IMAGE_REPO}:${TAG}"
          export BUILD_NUMBER="$DEPLOY_BUILD_NUMBER"
          # 显式列出变量，避免误替换清单里其他 $ 内容
          envsubst '${APP_NAME} ${IMAGE} ${BUILD_NUMBER} ${HOST} ${RUN_ID}' \
            < deploy/k8s/app.yaml | kubectl apply -f -

          echo "=== [4/4] Wait for rollout ==="
          if ! kubectl -n default rollout status "deployment/${APP_NAME}" --timeout=300s; then
            kubectl -n default describe pods -l "app=${APP_NAME}" | tail -n 60 || true
            kubectl -n default logs -l "app=${APP_NAME}" --tail=100 --all-containers --prefix || true
            exit 1
          fi
          kubectl -n default get deploy,pods,svc,ingress -l "app=${APP_NAME}" -o wide

      - name: Logout from registry
        if: always()
        run: docker logout "${{ secrets.REGISTRY }}" || true
```

国内基础镜像：按 `deploy` skill 的方式加 `DOCKER_MIRROR_URL`（判断变量放 **job 级** env）。

### 3.4 部署账号 RBAC（已有则复用，缺失才创建）

集群里通常已为其他项目建过部署账号（如 `github-deployer`），**先检验，权限齐全就直接复用，不要重复创建或覆盖**。

**① 检验（在 master 上以管理员身份执行，用 `--as` 模拟该账号，不需要那份 kubeconfig 文件）：**

```bash
SA=system:serviceaccount:default:github-deployer   # 按实际账号/命名空间修改

# 账号与绑定是否存在
kubectl -n default get serviceaccount github-deployer
kubectl -n default get role,rolebinding -o wide | grep github-deployer

# 写权限：kubectl apply 需要
for r in deployments.apps services ingresses.networking.k8s.io secrets; do
  echo -n "patch $r: "; kubectl auth can-i patch $r -n default --as=$SA
done
# 读/监听权限：rollout status 与失败诊断需要
for r in pods pods/log events replicasets.apps deployments.apps; do
  echo -n "watch $r: "; kubectl auth can-i watch $r -n default --as=$SA
done
```

| 检验结果 | 处理 |
|---|---|
| 全部 `yes` | 直接复用，跳过 ② |
| 账号存在但部分 `no` | 把缺的规则**合并**进已有 Role（`kubectl -n default edit role <name>`），不要整份 apply 覆盖 |
| 账号不存在 | 执行 ② 创建，并为它导出 kubeconfig → `KUBECONFIG_B64` |

> `kubectl version` 成功不代表账号有效（`/version` 无需认证），以 `auth can-i` 结果为准。
> 该账号只有命名空间权限，workflow 中不要查询 `nodes` 等集群级资源。

**② 创建（仅账号不存在时，集群管理员执行一次）：**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: github-deployer
  namespace: default
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: github-deployer
  namespace: default
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: [""]
    resources: ["services", "secrets"]
    verbs: ["get", "list", "create", "update", "patch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "create", "update", "patch"]
  - apiGroups: [""]
    resources: ["pods", "pods/log", "events"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: github-deployer
  namespace: default
subjects:
  - kind: ServiceAccount
    name: github-deployer
    namespace: default
roleRef:
  kind: Role
  name: github-deployer
  apiGroup: rbac.authorization.k8s.io
```

创建后重新执行 ① 检验，全部 `yes` 再运行 workflow。

## Step 4: 【最后一步·强制】收尾输出

最后一条消息必须包含：

1. **集群前置条件**
   - 目标节点已打标签：`kubectl label node <name> {key}={value}`
   - 部署账号 RBAC 按 3.4 ① 检验全部 `yes`（已有账号直接复用，缺失才创建）
   - Ingress 域名在 cloudflared tunnel / DNS 中指向 `http://traefik.kube-system.svc.cluster.local:80`（tunnel）或 Traefik 入口
   - 目标节点能访问集群外 DB/Redis；DB 用户允许该节点来源 IP
2. **Secrets 清单**

| Secret | 必填 | 说明 |
|---|:---:|---|
| `KUBECONFIG_B64` | ✅ | `base64 -i kubeconfig.yaml \| tr -d '\n'`；`server:` 必须公网可达 |
| `REGISTRY` / `REGISTRY_USERNAME` / `REGISTRY_PASSWORD` | ✅ | 镜像仓库（ACR 用 `ACR_*` 命名亦可） |
| 应用密码类（`DB_PASSWORD`、`ADMIN_PASSWORD`…） | ✅ | 写入集群 Secret |
| `DB_HOST` / `REDIS_HOST` 等地址 | ⬜ | 非空才注入，覆盖 yml 默认值 |
| `DOCKER_MIRROR_URL` | ⬜ | runner 拉基础镜像慢时 |

3. **发布步骤**：workflow 文件需在**默认分支**存在才会出现在 Actions 页面 → Run workflow → 选分支 → `rollback_tag` 留空
4. **验证**：`kubectl get deploy,pods,svc,ingress -l app={app} -o wide`（`NODE` 列即所在节点）
5. **回滚**：同一 workflow，`rollback_tag` 填 `k3s-{app}-<run_number>`，跳过构建直接部署旧镜像

## 关键设计决策

| 决策 | 原因 |
|---|---|
| 保留旧 docker workflow，新增 deploy-k3s.yml | 迁移期可随时切回；两者都手动触发，按分支选环境 |
| 镜像标签 `k3s-` 前缀 | 不同 workflow 的 `run_number` 各自从 1 计数，同名标签会互相覆盖 |
| `envsubst` + 单模板 | 测试/正式共用一份清单，按分支注入名称/域名 |
| Secrets → `kubectl create secret --dry-run \| apply` | 幂等；GitHub Secrets 是唯一真源 |
| Pod 注解 `run-id` | 只改 Secret 时 Pod 模板不变不会重建；注解保证每次部署都滚动 |
| `maxSurge 1 / maxUnavailable 0` | 单副本也能零停机滚动 |
| 存活探针用 tcpSocket，就绪探针用 health | 依赖抖动时不被反复重启，但会摘流 |
| request = limit（内存） | 防止调度器超卖导致节点 swap 卡死 |
| ClusterIP + Ingress，不用 NodePort | 统一入口、HTTPS、无端口冲突管理 |
| 发布失败自动打印 describe + logs | CI 里直接看到 ImagePullBackOff / 启动异常原因 |

## Common Mistakes（实战踩坑）

| 现象 | 原因 | 修复 |
|---|---|---|
| Actions 页面找不到 Run workflow 按钮 | `workflow_dispatch` 的 workflow 文件不在默认分支 | 先合入 main；运行时可选其他分支 |
| `nodes is forbidden ... at the cluster scope` | 部署账号是命名空间级 SA，workflow 里查了 `kubectl get nodes` | 删掉集群级查询；Pod 所在节点用 `get pods -o wide` 看 |
| `kubectl version` 成功但后续 Unauthorized | `/version` 无需认证，不代表凭据有效 | 重新导出 kubeconfig；本地 `kubectl auth can-i` 验证 |
| kubectl 连不上 API | kubeconfig `server: https://127.0.0.1:6443` 或内网/Tailscale 地址 | 改成公网地址，k3s 加 `--tls-san <公网IP>` |
| NodePort `8087` apply 报错 | NodePort 只能 30000–32767 | 改用 ClusterIP + Ingress |
| 全站用户一起被限流/拉黑 | Traefik 不信任上游，`X-Forwarded-For` 被改写成代理 IP | 优先读 `CF-Connecting-IP`；或给 Traefik 配 `forwardedHeaders.trustedIPs` |
| 改了 yml 默认地址却不生效 | workflow 把空 secret 当作 `KEY=` 注入，覆盖了 `${KEY:default}` | 有默认值的项：secret 非空才写入 env 文件 |
| 节点先后卡死、NotReady、Pod Pending | JVM `-Xmx1024m` 远超 request，节点内存超卖 → swap 卡死 | 覆盖 `JAVA_OPTS`，request = limit；节点关 swap，kubelet 加 `system-reserved`、`eviction-hard` |
| Pod 一直 Pending：`had untolerated taint(s)` | 目标节点 NotReady 带 NoSchedule 污点；30s tolerations 只管驱逐不管调度 | 先恢复节点（网络/内存），或临时给其他节点打标签 |
| 所有请求 2–20 秒、偶发 502 | 节点间走 Tailscale DERP 海外中转（`tailscale status` 显示 `relay "xxx"`）；应用每次查询跨节点访问 DB | 放行 UDP 41641 打通直连 / 自建国内 DERP；让应用调度到离 DB 近的节点 |
| 新部署后首屏白屏很久 | 新哈希静态资源未被 CDN 缓存，大 JS 经 tunnel 回源慢 | 开启 `server.compression`；静态资源长缓存；拆分大 chunk |
| 只改 Secret 后 Pod 没更新 | Pod 模板未变化不触发滚动 | 模板注解写入 `run-id` |
| 回滚标签格式不符被拒 | 标签前缀与环境不匹配 | 按 `k3s-<APP_NAME>-<run_number>` 填写 |

## 排查命令速查

```bash
kubectl get pods -A -o wide | grep -E '<app>|cloudflared|traefik'   # 各组件所在节点
kubectl describe pod <pod> | tail -20                                # 调度/拉镜像失败原因
kubectl get nodes; tailscale status                                  # 节点状态、是否走中转
kubectl top node; kubectl top pod -l app=<app>                       # 内存占用
kubectl run -it --rm t --image=curlimages/curl --restart=Never -- \
  curl -s -o /dev/null -w '%{time_total}s\n' http://<app>.default.svc.cluster.local/   # 绕过 CDN 测集群内耗时
```
