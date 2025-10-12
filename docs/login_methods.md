# 多种登录方式配置指南

本监控系统支持多种远程登录方式，包括密码认证、SSH密钥认证和跳板机连接。

## 1. 密码认证

最简单的登录方式，直接使用用户名和密码。

### 配置示例

```json
{
  "name": "密码登录服务器",
  "host": "192.168.1.100",
  "port": 22,
  "type": "gpu",
  "auth": {
    "type": "password",
    "username": "root",
    "password": "your_password"
  }
}
```

### 界面配置

1. 选择"密码认证"
2. 填写用户名和密码
3. 填写服务器地址和端口

## 2. SSH密钥认证

更安全的登录方式，使用SSH私钥进行认证。

### 配置示例

```json
{
  "name": "密钥登录服务器",
  "host": "192.168.1.101",
  "port": 22,
  "type": "npu",
  "auth": {
    "type": "key",
    "username": "ubuntu",
    "key_file": "/path/to/private_key",
    "key_password": null
  }
}
```

### 界面配置

1. 选择"密钥认证"
2. 填写用户名
3. 填写密钥文件路径（必须是运行监控程序的服务器上的路径）
4. 如果密钥有密码，填写密钥密码

### 密钥文件准备

1. 生成SSH密钥对：
   ```bash
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/gpu_monitor_key
   ```

2. 将公钥复制到目标服务器：
   ```bash
   ssh-copy-id -i ~/.ssh/gpu_monitor_key.pub user@target_server
   ```

3. 确保私钥文件权限正确：
   ```bash
   chmod 600 ~/.ssh/gpu_monitor_key
   ```

## 3. 跳板机登录

通过跳板机连接到内网目标服务器。

### 配置示例

```json
{
  "name": "内网GPU服务器",
  "host": "10.0.0.50",
  "port": 22,
  "type": "gpu",
  "auth": {
    "type": "key",
    "username": "gpu_user",
    "key_file": "/path/to/target_key"
  },
  "bastion": {
    "host": "jump.example.com",
    "port": 22,
    "auth": {
      "type": "key",
      "username": "jump_user",
      "key_file": "/path/to/jump_key",
      "key_password": "jump_key_password"
    }
  }
}
```

### 界面配置

1. 勾选"使用跳板机"
2. 填写跳板机地址和端口
3. 选择跳板机认证方式并配置相应信息
4. 配置目标服务器认证信息

### 跳板机网络要求

1. 跳板机必须能够SSH连接到目标服务器
2. 监控服务器必须能够SSH连接到跳板机
3. 确保网络防火墙规则允许相应连接

## 4. 兼容性说明

系统向后兼容旧的配置格式：

```json
{
  "name": "旧格式服务器",
  "host": "192.168.1.100",
  "port": 22,
  "username": "root",
  "password": "old_password",
  "type": "gpu"
}
```

旧格式会自动转换为新格式。

## 5. 安全建议

1. **优先使用密钥认证**：比密码认证更安全
2. **限制密钥权限**：私钥文件权限应为600
3. **使用专用账户**：避免使用root账户
4. **定期更换密钥**：定期轮换SSH密钥
5. **网络隔离**：使用跳板机隔离内外网
6. **日志监控**：监控SSH连接日志

## 6. 故障排除

### 连接失败常见原因

1. **密钥文件不存在**：检查密钥文件路径是否正确
2. **权限问题**：检查密钥文件权限是否为600
3. **网络不通**：检查网络连通性和防火墙规则
4. **用户权限不足**：确保用户有执行监控命令的权限
5. **跳板机配置错误**：检查跳板机到目标服务器的连接

### 调试方法

1. 手动测试SSH连接：
   ```bash
   ssh -i /path/to/key user@server
   ```

2. 通过跳板机测试：
   ```bash
   ssh -J jump_user@jump_server target_user@target_server
   ```

3. 检查监控程序日志输出

## 7. 配置模板

参考 `config/servers_example.json` 获取完整的配置示例。