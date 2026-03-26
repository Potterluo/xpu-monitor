# XPU Monitor - Kubernetes 部署快速指南

## 快速开始

### 1. 准备配置文件

```bash
# Linux/Mac
sudo mkdir -p /mnt/private/app/xpu-monitor
sudo chown -R $(whoami):$(whoami) /mnt/private/app/xpu-monitor

# Windows PowerShell
New-Item -ItemType Directory -Path "D:\mnt\private\app\xpu-monitor" -Force
```

### 2. 创建服务器配置

编辑 `/mnt/private/app/xpu-monitor/servers.json`:

```json
{
  "servers": [
    {
      "name": "GPU服务器1",
      "host": "192.168.1.100",
      "type": "gpu",
      "local": false,
      "auth": {
        "type": "password",
        "username": "monitor",
        "password": "your_password"
      }
    }
  ]
}
```

### 3. 部署到K8s

```bash
# Linux/Mac
chmod +x deploy.sh
./deploy.sh deploy

# Windows PowerShell
.\deploy.ps1 deploy
```

### 4. 访问应用

- URL: http://xpu.dev.huawei.com
- HTTPS: https://xpu.dev.huawei.com (需要配置证书)

## 配置说明

### 配置文件挂载

- **宿主机路径**: `/mnt/private/app/xpu-monitor/`
- **容器路径**: `/app/config/`
- **配置文件**: `servers.json`

### 服务器配置格式

| 字段 | 类型 | 说明 | 必填 |
|------|------|------|------|
| name | string | 服务器名称 | ✅ |
| host | string | 主机地址 | ✅ |
| type | string | gpu/npu | ✅ |
| local | boolean | 是否本地 | ✅ |
| auth | object | 认证配置 | ❌ |
| enable_storage_monitoring | boolean | 存储监控 | ❌ |
| enable_docker_monitoring | boolean | Docker监控 | ❌ |

### 认证配置

**密码认证**:
```json
{
  "auth": {
    "type": "password",
    "username": "user",
    "password": "password"
  }
}
```

**密钥认证**:
```json
{
  "auth": {
    "type": "key",
    "username": "user",
    "key_file": "/path/to/key",
    "key_password": "optional_password"
  }
}
```

## 常用命令

```bash
# 查看状态
kubectl get all -n xpu-monitor

# 查看日志
kubectl logs -n xpu-monitor -l app=xpu-monitor -f

# 重启Pod
kubectl rollout restart deployment/xpu-monitor -n xpu-monitor

# 更新配置后重启
vi /mnt/private/app/xpu-monitor/servers.json
kubectl rollout restart deployment/xpu-monitor -n xpu-monitor

# 扩容
kubectl scale deployment xpu-monitor --replicas=3 -n xpu-monitor

# 卸载
kubectl delete -f k8s-deployment.yaml
```

## 域名配置

当前配置的域名: `xpu.dev.huawei.com`

如需修改，编辑 `k8s-deployment.yaml` 中的 Ingress 部分：

```yaml
spec:
  tls:
  - hosts:
    - your-domain.com  # 修改这里
  rules:
  - host: your-domain.com  # 修改这里
```

## 资源限制

默认资源配置：
- CPU: 250m (请求) / 500m (限制)
- 内存: 256Mi (请求) / 512Mi (限制)

修改资源配置：

```bash
kubectl edit deployment xpu-monitor -n xpu-monitor
```

## 故障排查

### Pod 启动失败

```bash
# 查看 Pod 状态
kubectl get pods -n xpu-monitor

# 查看详情
kubectl describe pod <pod-name> -n xpu-monitor

# 查看日志
kubectl logs <pod-name> -n xpu-monitor
```

### 配置文件问题

```bash
# 检查配置文件挂载
kubectl exec -it <pod-name> -n xpu-monitor -- cat /app/config/servers.json

# 检查文件权限
ls -la /mnt/private/app/xpu-monitor/
```

### Ingress 问题

```bash
# 检查 Ingress
kubectl get ingress -n xpu-monitor

# 检查 DNS 解析
nslookup xpu.dev.huawei.com

# 检查 Ingress Controller
kubectl get pods -n ingress-nginx
```

## 更多信息

详细部署文档请参考: [K8S_DEPLOYMENT.md](K8S_DEPLOYMENT.md)

## 文件说明

| 文件 | 说明 |
|------|------|
| `Dockerfile` | Docker镜像构建文件 |
| `k8s-deployment.yaml` | Kubernetes完整部署配置 |
| `deploy.sh` | Linux/Mac 部署脚本 |
| `deploy.ps1` | Windows 部署脚本 |
| `.dockerignore` | Docker构建排除文件 |
| `K8S_DEPLOYMENT.md` | 详细部署文档 |
| `README_K8S.md` | 本文件 |
