# XPU Monitor

一个功能强大的Web端XPU（NPU/GPU）监控平台，支持实时监控多台本地和远程服务器上的计算设备状态。

![效果图](./docs/pic1.png)

## 功能特性

### 核心监控功能
- **实时监控**: 实时显示NPU/GPU温度、功耗、显存使用率、计算利用率
- **多设备支持**:
  - NPU监控 (华为昇腾) - 通过 `npu-smi info` 命令
  - GPU监控 (NVIDIA) - 通过 `nvidia-smi` 命令
- **本地与远程**: 支持本地监控和远程SSH监控

### 高级功能
- **多服务器支持**: 同时监控多台服务器，7列卡片布局
- **存储监控**: 实时监控磁盘空间使用情况
- **端点连通性检测**: 支持多IP端点批量检测，显示每个IP的连通状态
- **服务器详情**: 点击卡片查看详细信息，包括设备、存储、端点连通性

### 连接方式
- **SSH密码认证**: 支持传统密码登录
- **SSH密钥认证**: 支持RSA、Ed25519、ECDSA密钥
- **跳板机支持**: 通过跳板机连接内网服务器
- **本地监控**: 支持Windows和Linux本地监控

### 用户体验
- **响应式设计**: 完美适配桌面和移动设备
- **实时更新**: Server-Sent Events (SSE) 实现流畅的实时数据流
- **直观界面**: 颜色编码显示设备状态和警告
- **深色模式**: 支持明暗主题切换
- **配置管理**: Web界面直接管理服务器配置

## 快速开始

### 1. 环境准备

**Python要求**: Python 3.7+

**安装依赖**:
```bash
pip install -r requirements.txt
```

### 2. 配置服务器

编辑 `config/servers.json` 文件配置要监控的服务器：

```json
{
  "servers": [
    {
      "name": "本地GPU",
      "host": "127.0.0.1",
      "type": "gpu",
      "local": true
    },
    {
      "name": "远程NPU服务器",
      "host": "192.168.1.100",
      "port": 22,
      "type": "npu",
      "auth": {
        "type": "password",
        "username": "root",
        "password": "your_password"
      },
      "storage": {
        "mounts": [{"path": "/"}, {"path": "/data"}],
        "endpoints": [
          {"name": "存储网关", "host": ["192.168.1.101", "192.168.1.102", "192.168.1.103~108"]}
        ]
      }
    }
  ]
}
```

### 3. 启动应用

```bash
python run.py
```

### 4. 访问界面

打开浏览器访问: http://localhost:5090

## 配置参数详解

### 服务器配置参数

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 服务器显示名称 |
| `host` | string | 是 | 服务器IP地址或域名 |
| `type` | string | 是 | 设备类型: `"npu"` 或 `"gpu"` |
| `local` | boolean | 否 | 是否为本地服务器 (默认: false) |
| `port` | integer | 否 | SSH端口 (默认: 22) |

### 认证配置 (auth)

**密码认证**:
```json
{
  "type": "password",
  "username": "your_username",
  "password": "your_password"
}
```

**密钥认证**:
```json
{
  "type": "key",
  "username": "your_username",
  "key_file": "/path/to/private_key",
  "key_password": "optional_key_password"
}
```

### 存储配置 (storage)

```json
{
  "storage": {
    "mounts": [
      {"path": "/"},
      {"path": "/data"}
    ],
    "endpoints": [
      {
        "name": "存储网关",
        "host": ["192.168.1.101", "192.168.1.102", "192.168.1.103~108"]
      }
    ]
  }
}
```

**端点主机格式**:
- 单个IP: `"192.168.1.1"`
- IP数组: `["192.168.1.1", "192.168.1.2"]`
- IP范围: `"192.168.1.1~10"` (展开为192.168.1.1到192.168.1.10)

### 跳板机配置 (bastion)

```json
{
  "bastion": {
    "host": "jump.server.com",
    "port": 22,
    "auth": {
      "type": "key",
      "username": "jump_user",
      "key_file": "/path/to/jump_key"
    }
  }
}
```

## API接口

### RESTful API

- `GET /api/servers` - 获取所有服务器状态
- `GET /api/servers/<host>` - 获取指定服务器状态
- `POST /api/refresh` - 手动刷新所有服务器状态
- `GET /api/config` - 获取服务器配置
- `POST /api/config` - 更新服务器配置
- `POST /api/config/server` - 添加新服务器
- `DELETE /api/config/server/<name>` - 删除服务器

### Server-Sent Events (SSE)

- `GET /api/sse` - 实时服务器状态数据流

**事件类型**:
- `initial_data` - 初始数据
- `servers_refreshed` - 服务器状态更新
- `heartbeat` - 心跳保活

## 项目结构

```
xpu-monitor/
├── app.py                    # 主应用程序 (Flask + SSE)
├── run.py                    # 生产环境启动脚本
├── logger.py                 # 统一日志模块
├── requirements.txt          # Python依赖包
├── config/
│   └── servers.json          # 服务器配置文件
├── templates/
│   └── index.html            # Web界面 (单页应用)
├── static/
│   ├── css/style.css         # 样式文件
│   └── js/app.js             # 前端JavaScript
├── tests/
│   └── test_app.py           # 单元测试
└── docs/
    └── pic1.png              # 效果图
```

## 运行测试

```bash
python -m pytest tests/test_app.py -v
```

测试覆盖:
- GPU/NPU解析器测试
- 配置验证测试
- 并发安全性测试
- 错误隔离测试

## 系统要求

### 监控端 (运行此应用)
- **操作系统**: Windows 10+, Linux, macOS
- **Python**: 3.7+
- **内存**: 最少512MB

### 被监控服务器

**NPU服务器**:
- 华为昇腾NPU驱动
- `npu-smi` 命令可用

**GPU服务器**:
- NVIDIA GPU驱动
- `nvidia-smi` 命令可用

## 故障排除

### SSH连接失败
```bash
# 检查SSH连接
ssh username@server_ip -p port
```

### 命令执行失败
```bash
# 在目标服务器上检查命令
nvidia-smi  # 或 npu-smi info
```

### 调试模式
修改 `logger.py` 中的日志级别:
```python
setup_logging(level='DEBUG')
```

## 安全建议

1. 使用SSH密钥认证替代密码
2. 为监控创建专用用户账户
3. 限制监控用户权限
4. 使用HTTPS (生产环境)

## 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情
