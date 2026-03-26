# XPU Monitor Kubernetes 部署指南

## 概述

本文档描述如何将 XPU Monitor 部署到 Kubernetes 集群中。

## 前置要求

- Kubernetes 集群 (v1.19+)
- kubectl 命令行工具
- Docker 守护进程
- NGINX Ingress Controller
- cert-manager (用于HTTPS)

## 配置文件说明

### 配置目录结构

配置文件将被挂载到容器的 `/app/config` 目录：

```
/mnt/private/app/xpu-monitor/
├── servers.json          # 服务器配置文件
└── .gitkeep             # 保持目录结构
```

### servers.json 配置示例

```json
{
  "servers": [
    {
      "name": "GPU服务器1",
      "host": "192.168.1.100",
      "port": 22,
      "type": "gpu",
      "local": false,
      "auth": {
        "type": "password",
        "username": "monitor",
        "password": "your_password"
      },
      "enable_storage_monitoring": true,
      "enable_docker_monitoring": true
    },
    {
      "name": "NPU服务器1",
      "host": "192.168.1.101",
      "port": 22,
      "type": "npu",
      "local": false,
      "auth": {
        "type": "key",
        "username": "monitor",
        "key_file": "/path/to/private_key",
        "key_password": "key_password_if_any"
      },
      "enable_storage_monitoring": true,
      "enable_docker_monitoring": true
    }
  ],
  "llm_config": {
    "enabled": false,
    "api_url": "https://api.openai.com/v1/chat/completions",
    "api_key": "your_api_key_here",
    "model": "gpt-3.5-turbo"
  }
}
```

## 部署步骤

### 1. 准备配置文件

在部署节点上创建配置目录和配置文件：

```bash
# 创建配置目录
sudo mkdir -p /mnt/private/app/xpu-monitor

# 设置权限
sudo chown -R $(whoami):$(whoami) /mnt/private/app/xpu-monitor

# 创建配置文件
cat > /mnt/private/app/xpu-monitor/servers.json << 'EOF'
{
  "servers": [],
  "llm_config": {
    "enabled": false
  }
}
EOF
```

### 2. 编辑配置文件

编辑服务器配置文件，添加要监控的服务器：

```bash
vi /mnt/private/app/xpu-monitor/servers.json
```

### 3. 构建和部署

使用提供的部署脚本：

```bash
# 赋予执行权限
chmod +x deploy.sh

# 完整部署（构建镜像、推送、部署）
./deploy.sh deploy

# 或者分步执行
./deploy.sh build    # 仅构建镜像
./deploy.sh push     # 推送镜像
./deploy.sh deploy   # 部署到K8s
```

### 4. 查看部署状态

```bash
# 查看所有资源
kubectl get all -n xpu-monitor

# 查看Pod日志
kubectl logs -n xpu-monitor -l app=xpu-monitor -f

# 查看Ingress状态
kubectl get ingress -n xpu-monitor
```

### 5. 访问应用

部署完成后，通过以下地址访问：

- **HTTP**: http://xpu.dev.huawei.com
- **HTTPS**: https://xpu.dev.huawei.com (需要配置TLS证书)

## 镜像仓库配置

如果使用私有镜像仓库，需要修改 `deploy.sh` 中的配置：

```bash
# 编辑 deploy.sh
REGISTRY="your-private-registry.com"
```

并创建 Kubernetes Secret：

```bash
kubectl create secret docker-registry regcred \
  --docker-server=your-private-registry.com \
  --docker-username=your-username \
  --docker-password=your-password \
  -n xpu-monitor
```

然后在 `k8s-deployment.yaml` 中添加：

```yaml
spec:
  template:
    spec:
      imagePullSecrets:
      - name: regcred
```

## TLS/HTTPS 配置

### 使用 cert-manager 自动获取证书

如果集群中安装了 cert-manager，Ingress 配置会自动申请 Let's Encrypt 证书。

### 使用自定义证书

如果使用自定义 TLS 证书：

```bash
# 创建 TLS Secret
kubectl create secret tls xpu-monitor-tls \
  --cert=path/to/cert.crt \
  --key=path/to/cert.key \
  -n xpu-monitor
```

## 资源配置

默认资源配置：

```yaml
requests:
  memory: "256Mi"
  cpu: "250m"
limits:
  memory: "512Mi"
  cpu: "500m"
```

可以根据实际监控规模调整：

```bash
# 编辑部署
kubectl edit deployment xpu-monitor -n xpu-monitor
```

## 故障排查

### Pod 无法启动

```bash
# 查看 Pod 状态
kubectl get pods -n xpu-monitor

# 查看 Pod 详情
kubectl describe pod <pod-name> -n xpu-monitor

# 查看日志
kubectl logs <pod-name> -n xpu-monitor
```

### 配置文件未生效

```bash
# 检查配置文件挂载
kubectl exec -it <pod-name> -n xpu-monitor -- ls -la /app/config

# 查看配置文件内容
kubectl exec -it <pod-name> -n xpu-monitor -- cat /app/config/servers.json
```

### Ingress 无法访问

```bash
# 检查 Ingress
kubectl get ingress -n xpu-monitor

# 检查 Ingress Controller
kubectl get pods -n ingress-nginx

# 查看 Ingress 日志
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx
```

## 升级部署

### 更新配置文件

```bash
# 编辑配置
vi /mnt/private/app/xpu-monitor/servers.json

# 重启Pod以加载新配置
kubectl rollout restart deployment/xpu-monitor -n xpu-monitor
```

### 更新应用版本

```bash
# 构建新镜像
./deploy.sh build

# 推送镜像
./deploy.sh push

# 更新部署
kubectl set image deployment/xpu-monitor xpu-monitor=<new-image-tag> -n xpu-monitor
```

## 监控和维护

### 查看资源使用

```bash
# 查看Pod资源使用
kubectl top pod -n xpu-monitor

# 查看Node资源使用
kubectl top node
```

### 备份配置

```bash
# 备份配置文件
cp /mnt/private/app/xpu-monitor/servers.json \
   /mnt/private/app/xpu-monitor/servers.json.backup.$(date +%Y%m%d)
```

### 卸载

```bash
# 使用脚本卸载
./deploy.sh undeploy

# 或手动删除
kubectl delete -f k8s-deployment.yaml
```

## 安全建议

1. **配置文件权限**：确保 `/mnt/private/app/xpu-monitor` 目录权限正确
2. **密钥管理**：使用 Kubernetes Secret 存储敏感信息
3. **网络策略**：配置 NetworkPolicy 限制 Pod 间通信
4. **RBAC**：配置适当的 Role-Based Access Control

## 常见问题

### Q: 如何修改Ingress域名？

A: 编辑 `k8s-deployment.yaml` 中的 Ingress 部分，修改 `spec.rules[0].host` 和 `spec.tls[0].hosts`。

### Q: 如何配置持久化存储？

A: 当前配置使用 hostPath 挂载配置文件。如需持久化应用数据，可以添加 PVC：

```yaml
volumeMounts:
- name: data
  mountPath: /app/data
volumes:
- name: data
  persistentVolumeClaim:
    claimName: xpu-monitor-data
```

### Q: 支持高可用部署吗？

A: 是的，修改 Deployment 的 `replicas` 参数即可：

```yaml
spec:
  replicas: 3  # 运行3个副本
```

注意：多个副本会同时访问配置文件，建议使用共享存储（如 NFS）。

## 联系支持

如有问题，请提交 Issue 或联系维护团队。
