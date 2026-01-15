# K8s 日志监控权限配置指南

为了安全地将日志监控连接到您的 Kubernetes 集群，并限制其仅能读取指定 Namespace 的 Pod 日志，请按照以下步骤操作。

## 1. 创建 ServiceAccount、Role 和 RoleBinding

将以下内容保存为 `monitor-rbac.yaml`。请将 `your-namespace` 替换为您实际需要监控的 Namespace（例如 `production`）。

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: log-monitor-sa
  namespace: your-namespace
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: log-reader-role
  namespace: your-namespace
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: log-monitor-binding
  namespace: your-namespace
subjects:
- kind: ServiceAccount
  name: log-monitor-sa
  namespace: your-namespace
roleRef:
  kind: Role
  name: log-reader-role
  apiGroup: rbac.authorization.k8s.io
```

应用配置：
```bash
kubectl apply -f monitor-rbac.yaml
```

## 2. 生成 Kubeconfig (长期 Token)

对于 Kubernetes v1.24+，ServiceAccount 不再自动创建 Token。您需要手动创建一个长期有效的 Secret。

### 创建长期有效的 Secret

创建一个绑定到 ServiceAccount 的 Secret：

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: log-monitor-token
  namespace: your-namespace
  annotations:
    kubernetes.io/service-account.name: log-monitor-sa
type: kubernetes.io/service-account-token
```

保存为 `secret.yaml` 并应用，或直接运行：
```bash
kubectl apply -f secret.yaml
```

获取 Token 和 CA 证书：

```bash
# 获取 Token
TOKEN=$(kubectl get secret log-monitor-token -n your-namespace -o jsonpath='{.data.token}' | base64 --decode)

# 获取 CA 证书
kubectl get secret log-monitor-token -n your-namespace -o jsonpath='{.data.ca\.crt}' > ca.crt

# 获取 API Server 地址
APISERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
```

## 3. 构建 Kubeconfig 文件

创建一个名为 `monitor-kubeconfig.yaml` 的文件，并填入以下内容（替换占位符）：

```yaml
apiVersion: v1
kind: Config
clusters:
- name: monitor-cluster
  cluster:
    certificate-authority-data: <此处粘贴 ca.crt 文件的内容>
    server: <此处粘贴 APISERVER 地址>
contexts:
- name: monitor-context
  context:
    cluster: monitor-cluster
    namespace: your-namespace
    user: monitor-user
current-context: monitor-context
users:
- name: monitor-user
  user:
    token: <此处粘贴 TOKEN 内容>
```

**注意**: `certificate-authority-data` 应该是 base64 编码的字符串（即您直接从 `kubectl get secret ... -o jsonpath='{.data.ca\.crt}'` 获取到的内容）。

## 4. 在 Monitor 中使用

复制 `monitor-kubeconfig.yaml` 的全部内容，粘贴到 Monitor 配置对话框中的 **Kubeconfig** 字段即可。
