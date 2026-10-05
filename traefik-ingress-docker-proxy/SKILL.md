---
name: "traefik-ingress-docker-proxy"
description: "为运行在 Docker 主机上的服务生成 K8s Service + EndpointSlice + Traefik Ingress 清单，用域名经 Traefik 反向代理到 Docker 容器端口。"
---

# 用 Traefik Ingress 代理 Docker 服务

适用场景：服务跑在集群外的 Docker 主机上（docker compose / docker run），希望通过 K8s 集群里的 Traefik 用域名 + HTTPS 访问它。

## 1. 收集信息（缺什么问什么）

对每个要代理的服务，需要：

| 项 | 示例 | 说明 |
|---|---|---|
| 服务名 | `minio-api` | 用作 Service / EndpointSlice 名，小写字母、数字、`-` |
| 域名 | `minio-api.ksite.xin` | |
| 宿主机端口 | `9000` | Docker 映射到宿主机的端口（`ports` 左边的值） |
| Docker 主机 IP | `10.0.0.7` | **内网 IP**，且 K8s 节点能访问到 |

全局信息，没说明时用默认值，并在回复里写明用了默认值：

- 命名空间：`default`
- TLS Secret：`ksite-wildcard`（Cloudflare Origin 通配符证书，在 `default` 命名空间）
- IngressClass：`traefik`
- 入口：`websecure`

用户只给了 docker-compose 时，从 `ports`、`container_name` 中提取端口和服务名，但域名必须让用户确认。

## 2. 生成清单

每个服务一组 Service + EndpointSlice，所有服务合并成**一个** Ingress。写到文件（如 `traefik-docker-proxy.yaml`）并发给用户，不要只贴在回复里。

```yaml
---
apiVersion: v1
kind: Service
metadata:
  name: <服务名>
  namespace: default
spec:
  # 不写 selector，端点由 EndpointSlice 手动提供
  ports:
    - name: http
      port: <端口>
      targetPort: <端口>
      protocol: TCP
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: <服务名>-1
  namespace: default
  labels:
    kubernetes.io/service-name: <服务名>   # 必须与 Service 名一致
addressType: IPv4
ports:
  - name: http                            # 必须与 Service 端口名一致
    port: <端口>
    protocol: TCP
endpoints:
  - addresses:
      - <Docker主机内网IP>
    conditions:
      ready: true
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: <名称，如 docker-services>
  namespace: default
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.tls: "true"
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - <域名1>
        - <域名2>
      secretName: ksite-wildcard
  rules:
    - host: <域名1>
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: <服务名1>
                port:
                  number: <端口1>
```

### 规则

- 用标准 `Ingress`，**不用** Traefik 的 `IngressRoute` CRD，除非用户需要 TCP 路由、加权分流等 Ingress 做不到的功能。
- Service **不能**写 `selector`，否则 K8s 会覆盖手写的端点。
- EndpointSlice 的 `kubernetes.io/service-name` 标签和端口 `name` 必须与 Service 完全一致，这是最常见的错误。
- Ingress 与 TLS Secret 必须在**同一命名空间**。Secret 在别的命名空间时，要么把资源放过去，要么让用户把 Secret 复制过来。
- IP 引号可有可无，YAML 会把 IP 解析为字符串。
- 不使用 `certResolver`（Let's Encrypt），证书由 Cloudflare Origin 证书提供。

## 3. Cloudflare 相关

证书前提：Cloudflare SSL/TLS 模式为 **Full (strict)**，源站使用 Cloudflare Origin 证书。

- 模式是 **Full**：配置不变，也能工作。
- 模式是 **Flexible**：CF 到源站是明文 HTTP，提醒用户这不安全；如坚持使用，入口改为 `web`，去掉 `router.tls` 注解和 `tls` 段。
- 对象存储（MinIO 等）等需要上传大文件的服务，提醒 Cloudflare 免费版单请求上限 100MB：使用分片上传，或该域名关闭代理（小黄云）。

## 4. 按服务类型的附加提醒（只提相关的）

- **MinIO API**：给 minio 容器加 `MINIO_SERVER_URL=https://<api域名>`，否则预签名链接会带内网地址。
- **minio-console**：没有独立账号，用 MinIO 的账号登录。
- **Elasticsearch / 数据库类**：公网暴露只靠密码保护有风险，建议加 Traefik `ipAllowList` 中间件，或者不暴露域名。
- **含 JMX、管理端口的服务**：这些端口不要加进 Ingress，也不要映射到宿主机。

## 5. 部署与验证命令

```bash
kubectl get ingressclass                      # 确认名称是否为 traefik
kubectl -n default get secret ksite-wildcard  # 确认证书存在
kubectl apply -f traefik-docker-proxy.yaml
kubectl -n default get svc,endpointslice,ingress
kubectl run -it --rm nettest --image=busybox --restart=Never -- \
  wget -qO- -T 3 http://<Docker主机IP>:<端口>   # 验证集群能访问 Docker 主机
curl -I https://<域名>
```

## 6. 排错

| 现象 | 原因 |
|---|---|
| 502 / 504 | K8s 节点访问不到 Docker 主机端口：检查安全组 / 防火墙，IP 是否为内网 IP |
| 404 | Ingress 未被 Traefik 识别：`ingressClassName` 不对，或 Host 不匹配 |
| Service 没有端点 | EndpointSlice 的 `service-name` 标签或端口名与 Service 不一致 |
| Cloudflare 526 | Full (strict) 模式下证书无效：Secret 不对或不在同一命名空间 |
| Cloudflare 525 | SSL 握手失败：入口用错，没走 `websecure` |

## 7. 收尾安全建议

走 Traefik 之后，Docker 主机上这些服务的端口只需对 K8s 节点开放。提醒用户在安全组里只放行 K8s 节点 IP，或者在 compose 里把端口绑定到内网 IP（`"<内网IP>:9000:9000"`）。