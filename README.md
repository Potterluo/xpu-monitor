# NPU/GPU 监控平台

一个基于Web的NPU和GPU监控平台，支持远程监控多台Linux服务器上的NPU/GPU设备状态。

效果图

![效果图](./docs/pic1.png)

## 功能特性

- 🔍 **实时监控**: 实时显示NPU/GPU温度、功耗、显存使用率、计算利用率
- 🌐 **多服务器支持**: 同时监控多台Linux服务器
- 📱 **响应式设计**: 支持桌面和移动设备
- ⚡ **实时更新**: 通过WebSocket实现30秒自动刷新
- 🔧 **手动刷新**: 支持手动立即获取最新状态
- 🎨 **直观界面**: 颜色编码显示温度和利用率状态

## 支持的设备

- **NPU**: 通过 `npu-smi info` 命令获取状态
- **GPU**: 通过 `nvidia-smi` 命令获取状态

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置服务器

编辑 `config/servers.json` 文件，添加你要监控的服务器信息：

```json
{
  "servers": [
    {
      "name": "服务器1",
      "host": "192.168.1.100",
      "port": 22,
      "username": "root",
      "password": "your_password",
      "type": "npu"
    },
    {
      "name": "服务器2",
      "host": "192.168.1.101",
      "port": 22,
      "username": "root",
      "password": "your_password",
      "type": "gpu"
    }
  ]
}
```

### 3. 启动服务

```bash
python app.py
```

### 4. 访问Web界面

打开浏览器访问: http://localhost:5000

## 配置说明

### 服务器配置参数

- `name`: 服务器显示名称
- `host`: 服务器IP地址或域名
- `port`: SSH端口 (默认22)
- `username`: SSH用户名
- `password`: SSH密码
- `type`: 设备类型 (`npu` 或 `gpu`)

### 安全建议

1. 使用专门的监控账户，避免直接使用root
2. 考虑使用SSH密钥认证替代密码
3. 限制监控账户的权限
4. 在防火墙中限制访问端口

## 系统要求

### 服务器端 (被监控的Linux服务器)

- 支持SSH连接
- 已安装NPU驱动 (如华为昇腾NPU) 或 NVIDIA GPU驱动
- `npu-smi` 或 `nvidia-smi` 命令可用

### 监控端

- Python 3.7+
- 网络连接到被监控服务器

## 项目结构

```
npu-gpu-monitor/
├── app.py              # 主应用程序
├── requirements.txt    # Python依赖
├── config/
│   └── servers.json    # 服务器配置文件
├── templates/
│   └── index.html      # Web界面模板
├── static/
│   ├── css/
│   │   └── style.css   # 样式文件
│   └── js/
│       └── app.js      # 前端JavaScript
└── README.md          # 说明文档
```

## API接口

### GET /api/servers
获取所有服务器状态信息

### GET /api/servers/<host>
获取指定服务器状态信息

### POST /api/refresh
手动刷新所有服务器状态

## WebSocket事件

- `connect`: 客户端连接
- `initial_data`: 发送初始数据
- `server_update`: 服务器状态更新
- `disconnect`: 连接断开

## 故障排除

### 常见问题

1. **SSH连接失败**
   - 检查服务器IP、端口、用户名、密码
   - 确认SSH服务正常运行
   - 检查防火墙设置

2. **命令执行失败**
   - 确认npu-smi或nvidia-smi命令存在
   - 检查用户权限
   - 验证驱动程序安装

3. **数据解析错误**
   - 检查命令输出格式是否与预期一致
   - 查看后端日志获取详细错误信息

### 调试模式

修改 `app.py` 最后一行，启用调试模式：

```python
socketio.run(app, host='0.0.0.0', port=5000, debug=True)
```

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！