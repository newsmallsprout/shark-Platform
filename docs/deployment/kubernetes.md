# K8s 生产部署傻瓜式操作文档（shark-platform）

> 上级索引：[deployment/README.md](./README.md) · Traffic 中间件：[traffic-middleware.md](./traffic-middleware.md)

这份文档收敛仓库里所有“需要人工操作”的步骤：从构建镜像、部署到 K8s、RBAC、生产 kubeconfig、到上线后配置与维护（电话告警、日志监控、排班去重）。照着做就能上线。

---

## 0. 一次性要准备的值（先把这些写下来）

- **namespace**：`habit`
- **域名**：`domain name`（如仍使用 test 域名，把本文所有域名替换）
- **目标节点 hostname**：`随意`
- **镜像**：`habit`（按实际 tag 替换）
- **DJANGO_SECRET_KEY（生产）**：随机字符串，base64 后写入 Secret（不要用示例）
- **Slack Webhook**：电话告警、日志监控各自要用的 webhook（不同模块配置位置不同）

---

## 1. 生产部署（只做一次，后续升级只改 image tag）

### 1.1 生成生产 Secret（必须）

生成 `DJANGO_SECRET_KEY` 的 base64：

```bash
echo -n "replace-me-with-prod-secret" | base64
```

把输出复制到下面 YAML 的 `data.DJANGO_SECRET_KEY`。

### 1.2 一次性 YAML（保存为 shark-platform-prod.yaml）

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: shark-platform-sa
  namespace: middleware-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: shark-log-reader
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["create", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: shark-log-reader-binding
subjects:
- kind: ServiceAccount
  name: shark-platform-sa
  namespace: middleware-system
roleRef:
  kind: ClusterRole
  name: shark-log-reader
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: shark-platform-config
  namespace: middleware-system
data:
  DEBUG: "False"
  ALLOWED_HOSTS: "*"
  CSRF_TRUSTED_ORIGINS: "domian name"
  DEFAULT_MONITOR_NAMESPACE: "日志采集的namescape"
  PUBLIC_URL: "domian name"
  # Turbo Pod 可选参数（不填则走代码默认值）
  SYNC_RUNNER_IMAGE: "imagename"
  SYNC_RUNNER_NAMESPACE: "middleware-system"
  SYNC_RUNNER_SERVICE_ACCOUNT: "shark-platform-sa"
  SYNC_RUNNER_IMAGE_PULL_POLICY: "IfNotPresent"
  SYNC_RUNNER_STATE_PVC: "shark-platform-state-pvc"
---
apiVersion: v1
kind: Secret
metadata:
  name: shark-platform-secrets
  namespace: middleware-system
type: Opaque
data:
  DJANGO_SECRET_KEY: REPLACE_ME_BASE64
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: shark-platform-state-pvc
  namespace: middleware-system
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: gp3
  resources:
    requests:
      storage: 5Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: shark-platform-logs-pvc
  namespace: middleware-system
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: gp3
  resources:
    requests:
      storage: 50Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: shark-platform
  namespace: middleware-system
  labels:
    app: shark-platform
spec:
  replicas: 1
  selector:
    matchLabels:
      app: shark-platform
  template:
    metadata:
      labels:
        app: shark-platform
    spec:
      serviceAccountName: shark-platform-sa
      nodeSelector:
        kubernetes.io/hostname: 绑定节点做不做都行
      tolerations:
      - key: "node-role.kubernetes.io/cluster-tools"
        operator: "Exists"
        effect: "NoSchedule"
      containers:
      - name: shark-platform
        image:  imagename 
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: shark-platform-config
        - secretRef:
            name: shark-platform-secrets
        volumeMounts:
        - name: app-state
          mountPath: /app/state
        - name: app-logs
          mountPath: /app/logs
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /api/system/health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 15
        readinessProbe:
          httpGet:
            path: /
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
      volumes:
      - name: app-state
        persistentVolumeClaim:
          claimName: shark-platform-state-pvc
      - name: app-logs
        persistentVolumeClaim:
          claimName: shark-platform-logs-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: shark-platform-service
  namespace: middleware-system
spec:
  selector:
    app: shark-platform
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: ClusterIP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shark-platform-ingress
  namespace: middleware-system
spec:
  ingressClassName: traefik
  rules:
  - host: domian name
    http:
      paths:
      - backend:
          service:
            name: shark-platform-service
            port:
              number: 80
        path: /
        pathType: ImplementationSpecific
```

### 1.3 一步一步执行部署命令

```bash
kubectl get ns middleware-system || kubectl create ns middleware-system
kubectl apply -f shark-platform-prod.yaml
kubectl get pvc -n middleware-system
kubectl get pod -n middleware-system -l app=shark-platform -o wide
kubectl logs -f -n middleware-system deploy/shark-platform
```

### 1.4 验证 RBAC（日志监控必须）

```bash
kubectl auth can-i list pods --as=system:serviceaccount:middleware-system:shark-platform-sa -A
kubectl auth can-i get pods/log --as=system:serviceaccount:middleware-system:shark-platform-sa -n biz-system
kubectl auth can-i get pods/log --as=system:serviceaccount:middleware-system:shark-platform-sa -n flink-system
```

---

## 2. 生产 kubeconfig 配置（需要跨集群时才做）

同集群部署时，Log Monitor 默认使用 in-cluster config，任务 kubeconfig 留空即可。

如果你要跨集群监控，按下面生成 kubeconfig（长期 token）并粘贴到 Log Monitor 任务里：

### 2.1 创建 SA + Token Secret

```bash
kubectl -n middleware-system create sa shark-platform-kubeconfig-sa

cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: shark-platform-kubeconfig-token
  namespace: middleware-system
  annotations:
    kubernetes.io/service-account.name: shark-platform-kubeconfig-sa
type: kubernetes.io/service-account-token
YAML
```

### 2.2 绑定读取日志权限

```bash
kubectl create clusterrolebinding shark-platform-kubeconfig-binding \
  --clusterrole=shark-log-reader \
  --serviceaccount=middleware-system:shark-platform-kubeconfig-sa
```

### 2.3 导出 token/CA/apiserver 并生成 kubeconfig

```bash
TOKEN=$(kubectl get secret shark-platform-kubeconfig-token -n middleware-system -o jsonpath='{.data.token}')
CA=$(kubectl get secret shark-platform-kubeconfig-token -n middleware-system -o jsonpath='{.data.ca\.crt}')
APISERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')

cat > shark-platform-kubeconfig.yaml <<EOF
apiVersion: v1
kind: Config
clusters:
- name: prod-cluster
  cluster:
    certificate-authority-data: ${CA}
    server: ${APISERVER}
contexts:
- name: shark-platform
  context:
    cluster: prod-cluster
    namespace: biz-system
    user: shark-platform
current-context: shark-platform
users:
- name: shark-platform
  user:
    token: ${TOKEN}
EOF
```

把 `shark-platform-kubeconfig.yaml` 的全文粘贴到 Log Monitor 任务的 `Kubeconfig` 输入框即可。

---

## 3. 上线后必须做的初始化（别跳过）

### 3.1 修改默认管理员密码

容器启动时会自动迁移数据库并创建默认管理员（首次）：

- 用户名：`admin`
- 密码：`admin`

上线后请立刻改密。

### 3.2 Schedules（排班）重复数据清理（只需一次）

历史重复数据用命令清理（先 dry-run，再 apply）：

```bash
kubectl exec -n middleware-system deploy/shark-platform -- python3 manage.py dedup_schedules
kubectl exec -n middleware-system deploy/shark-platform -- python3 manage.py dedup_schedules --apply
```

可选按日期范围：

```bash
kubectl exec -n middleware-system deploy/shark-platform -- \
  python3 manage.py dedup_schedules --from-date 2026-02-01 --to-date 2026-02-10 --apply
```

### 3.3 Phone Alert（电话告警）配置清单

页面：**Schedules → Phone Alert Config**

- Public URL：与 `PUBLIC_URL` 一致
- Slack Webhook URL：电话告警通知
- External API URL：回调接口（只发两种状态：`PROCESSING/COMPLETED`）
- External API Username/Password：Basic Auth
- Oncall Slack Mapping：配置“姓名 → Slack User ID（Uxxxx）”，系统会转成 `<@Uxxxx>` 真实@人

同一个时间段多个值班人员会同时 @（多个 `<@U...>` 会拼在一起发送）。

### 3.4 Log Monitor（日志监控）配置清单

- 同集群：任务 kubeconfig 留空（走 in-cluster config）
- 多 namespace：任务 `k8s_namespace` 支持逗号分隔
- Slack 告警 deep link：依赖 `PUBLIC_URL`

### 3.5 System Inspection（集群巡检）

- 页面 **System Inspection** 配 Prometheus URL（需能查到 `monitor` 里的 Prometheus）
- PVC 用量读 `pvc_stats_*`（prd 已部署 `pvc-stats-exporter`，清单见 `infra/kubernetes/monitor/pvc-stats-exporter/`）
- 与 ops-host 脚本同一张清单：`scripts/inspect-prd.sh`
- 说明：[INSPECTION.md](../INSPECTION.md)

---

## 4. 常用排障命令（不会就照抄）

```bash
kubectl get deploy,pod,svc,ingress -n middleware-system
kubectl describe pod -n middleware-system -l app=shark-platform | head -n 120
kubectl logs -f -n middleware-system deploy/shark-platform
kubectl get ingress -A | grep ubest-ops
kubectl get svc -A | grep shark-platform
```

---

## 5. 额外说明（仓库里容易踩坑的地方）

- `CSRF_TRUSTED_ORIGINS` 不要带反引号/多余空格；务必用逗号分隔的 URL 列表。
- 生产建议使用 PVC（EBS CSI / gp3）做数据盘（本文已默认使用 `storageClassName: gp3` 的 PVC）。`gp3` 通常是 `WaitForFirstConsumer`，PVC 可能会在 Pod 调度后才 Bound。
- README 的 K8s 步骤里若提到独立 `secrets.yaml`，仓库示例是把 Secret 合并在 `infra/kubernetes/configmap.yaml`（生产建议用本文档的一体 YAML）。
- 本地 Docker Compose 见 `infra/docker/docker-compose.yml`：默认只起应用；需 MySQL/Mongo 等时加 `--profile sync` 或 `COMPOSE_PROFILES=sync`。MySQL 配置在 `infra/docker/mysql/`。
