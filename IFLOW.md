# NPU/GPU 监控平台 - iFlow 配置文件

## 项目概述

这是一个基于Python Flask的Web监控平台，用于实时监控多台Linux服务器上的NPU（华为昇腾）和GPU（NVIDIA）设备状态。系统支持SSH远程连接、WebSocket实时更新、存储监控、Docker监控以及智能存储优化建议。

### 核心功能
- **实时监控**: NPU/GPU温度、功耗、显存使用率、计算利用率
- **多服务器支持**: 同时监控多台Linux服务器，支持密码/密钥/跳板机认证
- **存储监控**: 磁盘空间使用情况监控和智能优化建议
- **Docker监控**: 镜像和容器资源使用监控
- **LLM集成**: 可选的AI智能存储优化建议（支持OpenAI API）
- **Web界面**: 响应式设计，支持桌面和移动设备
- **实时通信**: WebSocket实现30秒自动刷新

## 技术架构

### 后端技术栈
- **框架**: Flask 2.3.0+ + Flask-SocketIO 5.3.0+
- **SSH连接**: Paramiko 3.3.0+（支持密码、密钥、跳板机）
- **异步通信**: Eventlet + Socket.IO
- **数据处理**: 正则表达式解析npu-smi/nvidia-smi输出
- **HTTP客户端**: Requests 2.32.3+

### 前端技术栈
- **UI框架**: Tailwind CSS + Preline UI
- **图标**: Font Awesome 6.4.0
- **图表**: Chart.js
- **实时通信**: Socket.IO客户端
- **现代化**: 支持深色模式、响应式设计

### 支持的设备
- **NPU**: 华为昇腾系列（通过`npu-smi info`命令）
- **GPU**: NVIDIA全系列（通过`nvidia-smi`命令）

## 项目结构

```
xpu-monitor/
├── app.py                    # 主应用程序（Flask + WebSocket服务器）
├── run.py                    # 启动脚本（带环境检查和依赖验证）
├── start.bat                 # Windows启动批处理
├── requirements.txt          # Python依赖包列表
├── config/
│   ├── servers.json         # 服务器配置文件（运行时）
│   └── servers_example.json # 服务器配置示例
├── templates/
│   ├── index_modern.html    # 现代化主界面（Tailwind CSS）
│   └── index.html           # 经典界面（传统样式）
├── static/
│   ├── css/style.css        # 自定义样式
│   └── js/app.js            # 前端JavaScript逻辑
├── docs/
│   ├── login_methods.md     # 登录方式配置指南
│   └── pic1.png             # 系统截图
└── __pycache__/             # Python缓存目录
```

## 核心文件说明

### 后端核心文件

**app.py** - 主应用程序
- Flask Web服务器和WebSocket服务器
- SSH连接管理（支持密码、密钥、跳板机）
- NPU/GPU数据解析（parse_npu_smi, parse_nvidia_smi）
- 存储和Docker信息获取
- LLM智能建议集成
- API接口和WebSocket事件处理
- 后台定时任务（每15秒更新）

**run.py** - 启动脚本
- Python版本检查（要求3.7+）
- 依赖包完整性验证
- 配置文件格式验证
- 错误处理和用户引导

### 前端核心文件

**templates/index_modern.html** - 现代化界面
- Tailwind CSS + Preline UI组件
- 响应式布局（支持移动端）
- 深色模式支持
- Chart.js图表展示
- WebSocket实时通信

**static/js/app.js** - 前端逻辑
- Socket.IO连接管理
- 服务器状态实时更新
- 配置管理界面
- 错误处理和重连机制

### 配置文件

**config/servers.json** - 服务器配置
- 支持本地和远程服务器
- 多种认证方式（密码、密钥、跳板机）
- 存储和Docker监控开关
- LLM配置（可选）

## 主要API接口

### 服务器状态API
- `GET /api/servers` - 获取所有服务器状态
- `GET /api/servers/<host>` - 获取指定服务器状态
- `POST /api/refresh` - 手动刷新所有服务器

### 配置管理API
- `GET /api/config` - 获取服务器配置
- `POST /api/config` - 更新服务器配置
- `POST /api/config/server` - 添加单个服务器
- `DELETE /api/config/server/<name>` - 删除服务器

### 存储分析API
- `GET /api/storage/suggestions/<host>` - 获取存储优化建议
- `POST /api/storage/analyze` - 分析多个服务器存储状况

### LLM配置API
- `GET /api/config/llm` - 获取LLM配置
- `POST /api/config/llm` - 更新LLM配置

### 测试API
- `GET /api/mock/data` - 获取模拟数据（前端测试用）

### WebSocket事件
- `connect` - 客户端连接
- `initial_data` - 发送初始数据
- `server_update` - 服务器状态更新
- `servers_refreshed` - 服务器列表刷新
- `disconnect` - 客户端断开

## 关键功能实现

### SSH连接管理
- 支持密码认证、SSH密钥认证（RSA/Ed25519/ECDSA）
- 跳板机连接（通过SSH隧道）
- 连接池管理和超时控制
- 详细的错误处理和日志记录

### 数据解析
- **NPU解析**: 支持华为昇腾NPU的双行表格结构解析
- **GPU解析**: 支持NVIDIA GPU的标准输出格式解析
- **存储解析**: Linux df命令输出解析
- **Docker解析**: docker images/ps命令输出解析

### 智能建议系统
- 基于规则的存储优化建议
- 可选的LLM集成（OpenAI API）
- 多服务器综合分析
- 风险等级分类（critical/warning/info）

## 运行和部署

### 开发环境启动
```bash
# 安装依赖
pip install -r requirements.txt

# 配置服务器（编辑config/servers.json）
# 启动开发服务器（带调试）
python app.py

# 或使用启动脚本（带环境检查）
python run.py
```

### 生产环境部署
```bash
# 使用生产配置启动
python run.py  # 监听0.0.0.0:5090

# Windows系统
start.bat
```

### 访问地址
- Web界面: http://localhost:5000 (开发) 或 http://localhost:5090 (生产)
- 经典界面: http://localhost:5000/classic

## 配置说明

### 基本服务器配置
```json
{
  "name": "服务器名称",
  "host": "192.168.1.100",
  "type": "gpu",        // gpu 或 npu
  "local": false,       // 是否为本地监控
  "enable_storage_monitoring": true,
  "enable_docker_monitoring": true
}
```

### 远程服务器认证配置
```json
{
  "auth": {
    "type": "password",      // password 或 key
    "username": "root",
    "password": "your_password"  // 或 "key_file": "/path/to/key"
  }
}
```

### 跳板机配置
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

### LLM配置（可选）
```json
{
  "llm_config": {
    "enabled": true,
    "api_url": "https://api.openai.com/v1/chat/completions",
    "api_key": "your_openai_api_key",
    "model": "gpt-3.5-turbo"
  }
}
```

## 开发规范

### 代码风格
- **Python**: 遵循PEP 8规范，使用有意义的变量名
- **JavaScript**: 使用ES6+语法，驼峰命名法
- **HTML/CSS**: 语义化标签，BEM命名规范

### 错误处理
- 详细的异常捕获和日志记录
- 用户友好的错误提示
- WebSocket连接的重连机制
- API请求的错误状态码处理

### 安全性
- SSH密钥文件权限检查（600）
- 密码等敏感信息不在日志中显示
- 输入验证和参数校验
- WebSocket跨域配置

### 性能优化
- 后台线程定时更新，避免阻塞主线程
- WebSocket推送更新，减少HTTP请求
- 数据缓存和状态管理
- 前端虚拟化渲染（大量设备时）

## 扩展功能

### 计划中的功能
- 历史数据存储和趋势分析
- 告警通知（邮件、短信、Webhook）
- 多用户管理和权限控制
- Kubernetes集群监控
- 更多AI芯片支持（寒武纪、地平线等）

### 自定义扩展
- 插件系统支持自定义数据源
- API接口开放第三方集成
- 前端组件化开发
- 主题和样式自定义

## 故障排除

### 常见问题
1. **SSH连接失败**: 检查网络、认证信息、防火墙设置
2. **命令执行超时**: 调整超时参数，检查服务器负载
3. **数据解析错误**: 验证命令输出格式，查看日志
4. **WebSocket连接问题**: 检查网络代理、浏览器兼容性

### 调试模式
```python
# 在app.py中启用调试模式
socketio.run(app, host='0.0.0.0', port=5000, debug=True)
```

### 日志查看
- 控制台输出包含详细的连接和解析日志
- 检查Python异常堆栈信息
- WebSocket事件日志在前端控制台

## 许可证

MIT License - 详见项目根目录LICENSE文件