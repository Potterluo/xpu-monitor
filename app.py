from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import paramiko
import json
import threading
import time
import subprocess
import platform
import os
import socket
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'npu-gpu-monitor-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# 全局变量存储服务器状态
server_status = {}

def load_server_config():
    """加载服务器配置"""
    try:
        # 确保config目录存在
        os.makedirs('config', exist_ok=True)

        # 如果配置文件不存在，创建默认配置
        if not os.path.exists('config/servers.json'):
            default_config = {
                "servers": [
                    {
                        "name": "本机GPU",
                        "host": "localhost",
                        "local": True,
                        "type": "gpu"
                    }
                ]
            }
            save_server_config(default_config)
            return default_config

        with open('config/servers.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"加载配置文件失败: {e}")
        return {"servers": []}

def save_server_config(config):
    """保存服务器配置"""
    try:
        os.makedirs('config', exist_ok=True)
        with open('config/servers.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存配置文件失败: {e}")
        return False

def validate_server_config(server):
    """验证服务器配置"""
    if not all(key in server for key in ['name', 'host', 'type']):
        return False, "服务器配置缺少必要字段"

    if server['type'] not in ['gpu', 'npu']:
        return False, f"不支持的设备类型: {server['type']}"

    # 验证远程服务器配置
    if not server.get('local', False) and server['host'] not in ['localhost', '127.0.0.1']:
        # 检查新格式认证配置
        if 'auth' in server:
            auth_config = server['auth']
            if not isinstance(auth_config, dict):
                return False, "认证配置格式错误"

            auth_type = auth_config.get('type')
            if auth_type not in ['password', 'key']:
                return False, f"不支持的认证类型: {auth_type}"

            username = auth_config.get('username')
            if not username:
                return False, "认证配置缺少用户名"

            if auth_type == 'password':
                if not auth_config.get('password'):
                    return False, "密码认证需要提供密码"
            elif auth_type == 'key':
                key_file = auth_config.get('key_file')
                if not key_file:
                    return False, "密钥认证需要提供密钥文件路径"

        # 兼容旧配置格式
        elif 'username' in server and 'password' in server:
            pass  # 旧格式，有效
        else:
            return False, "远程服务器需要认证配置"

        # 验证跳板机配置
        if 'bastion' in server:
            bastion_config = server['bastion']
            if not isinstance(bastion_config, dict):
                return False, "跳板机配置格式错误"

            if not all(key in bastion_config for key in ['host', 'auth']):
                return False, "跳板机配置缺少必要字段"

            bastion_auth = bastion_config['auth']
            if not isinstance(bastion_auth, dict):
                return False, "跳板机认证配置格式错误"

            bastion_auth_type = bastion_auth.get('type')
            if bastion_auth_type not in ['password', 'key']:
                return False, f"不支持的跳板机认证类型: {bastion_auth_type}"

            bastion_username = bastion_auth.get('username')
            if not bastion_username:
                return False, "跳板机认证配置缺少用户名"

            if bastion_auth_type == 'password':
                if not bastion_auth.get('password'):
                    return False, "跳板机密码认证需要提供密码"
            elif bastion_auth_type == 'key':
                bastion_key_file = bastion_auth.get('key_file')
                if not bastion_key_file:
                    return False, "跳板机密钥认证需要提供密钥文件路径"

    return True, "配置有效"

def create_ssh_client():
    """创建SSH客户端"""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return ssh

def authenticate_ssh(ssh, auth_config):
    """SSH认证"""
    auth_type = auth_config.get('type', 'password')
    username = auth_config.get('username')

    try:
        if auth_type == 'password':
            # 密码认证
            password = auth_config.get('password')
            if not password:
                raise ValueError("密码认证需要提供密码")
            return password, None

        elif auth_type == 'key':
            # 密钥认证
            key_file = auth_config.get('key_file')
            key_password = auth_config.get('key_password')

            if not key_file:
                raise ValueError("密钥认证需要提供密钥文件路径")

            if not os.path.exists(key_file):
                raise ValueError(f"密钥文件不存在: {key_file}")

            # 加载私钥
            try:
                private_key = paramiko.RSAKey.from_private_key_file(
                    key_file, password=key_password
                )
            except paramiko.PasswordRequiredException:
                raise ValueError("密钥文件需要密码")
            except paramiko.SSHException as e:
                # 尝试其他密钥格式
                try:
                    private_key = paramiko.Ed25519Key.from_private_key_file(
                        key_file, password=key_password
                    )
                except paramiko.SSHException:
                    try:
                        private_key = paramiko.ECDSAKey.from_private_key_file(
                            key_file, password=key_password
                        )
                    except paramiko.SSHException:
                        raise ValueError(f"无法加载密钥文件: {e}")

            return None, private_key

        else:
            raise ValueError(f"不支持的认证类型: {auth_type}")

    except Exception as e:
        print(f"SSH认证配置错误: {e}")
        raise

def ssh_connect(host, port, auth_config, bastion_config=None):
    """建立SSH连接，支持密码、密钥和跳板机"""
    ssh = create_ssh_client()

    try:
        if bastion_config:
            # 通过跳板机连接
            return ssh_connect_via_bastion(ssh, host, port, auth_config, bastion_config)
        else:
            # 直接连接
            password, private_key = authenticate_ssh(ssh, auth_config)

            if private_key:
                ssh.connect(
                    host, port=port,
                    username=auth_config['username'],
                    pkey=private_key,
                    timeout=5
                )
            else:
                ssh.connect(
                    host, port=port,
                    username=auth_config['username'],
                    password=password,
                    timeout=5
                )

            print(f"SSH连接成功: {host}:{port}")
            return ssh

    except paramiko.AuthenticationException:
        print(f"SSH认证失败 {host}:{port}: 用户名或密码/密钥错误")
        if ssh:
            ssh.close()
        return None
    except paramiko.SSHException as e:
        error_msg = str(e).lower()
        if 'timed out' in error_msg:
            print(f"SSH连接超时 {host}:{port}")
        elif 'connection refused' in error_msg:
            print(f"SSH连接被拒绝 {host}:{port}: 服务可能未运行或端口被防火墙阻止")
        elif 'name or service not known' in error_msg or 'nodename nor servname provided' in error_msg:
            print(f"SSH主机名解析失败 {host}:{port}: 主机名不存在或DNS问题")
        else:
            print(f"SSH连接失败 {host}:{port}: {e}")
        if ssh:
            ssh.close()
        return None
    except socket.timeout:
        print(f"SSH连接超时 {host}:{port}")
        if ssh:
            ssh.close()
        return None
    except Exception as e:
        print(f"SSH连接失败 {host}:{port}: {e}")
        if ssh:
            ssh.close()
        return None

def ssh_connect_via_bastion(ssh, target_host, target_port, auth_config, bastion_config):
    """通过跳板机建立SSH连接"""
    try:
        # 第一步：连接到跳板机
        bastion_ssh = create_ssh_client()
        bastion_password, bastion_private_key = authenticate_ssh(bastion_ssh, bastion_config['auth'])

        if bastion_private_key:
            bastion_ssh.connect(
                bastion_config['host'],
                port=bastion_config.get('port', 22),
                username=bastion_config['auth']['username'],
                pkey=bastion_private_key,
                timeout=5
            )
        else:
            bastion_ssh.connect(
                bastion_config['host'],
                port=bastion_config.get('port', 22),
                username=bastion_config['auth']['username'],
                password=bastion_password,
                timeout=5
            )

        print(f"跳板机连接成功: {bastion_config['host']}")

        # 第二步：通过跳板机连接到目标主机
        transport = bastion_ssh.get_transport()

        # 创建到目标主机的通道
        dest_addr = (target_host, target_port)
        local_addr = ('127.0.0.1', 22)

        channel = transport.open_channel("direct-tcpip", dest_addr, local_addr)

        # 通过通道连接到目标主机
        password, private_key = authenticate_ssh(ssh, auth_config)

        if private_key:
            ssh.connect(
                '127.0.0.1', port=channel,
                username=auth_config['username'],
                pkey=private_key,
                timeout=5
            )
        else:
            ssh.connect(
                '127.0.0.1', port=channel,
                username=auth_config['username'],
                password=password,
                timeout=5
            )

        # 关闭跳板机连接，但保持通道开启
        bastion_ssh.close()

        print(f"通过跳板机连接成功: {target_host}:{target_port}")
        return ssh

    except Exception as e:
        print(f"跳板机连接失败 {target_host}:{target_port}: {e}")
        if ssh:
            ssh.close()
        return None

def execute_command(ssh, command, timeout=8):
    """执行远程命令"""
    try:
        stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        return output, error
    except socket.timeout:
        print(f"命令执行超时: {command}")
        return None, "Command execution timeout"
    except Exception as e:
        error_msg = str(e)
        if 'timed out' in error_msg.lower():
            print(f"命令执行超时: {command}")
            return None, "Command execution timeout"
        print(f"执行命令失败: {e}")
        return None, error_msg

def execute_local_command(command):
    """执行本地命令"""
    try:
        if platform.system() == 'Windows':
            # Windows系统使用shell=True
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        else:
            # Linux/Unix系统
            result = subprocess.run(command.split(), capture_output=True, text=True, timeout=30)

        return result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return None, "命令执行超时"
    except Exception as e:
        print(f"执行本地命令失败: {e}")
        return None, str(e)

def parse_npu_smi(output):
    """解析NPU-SMI输出"""
    if not output:
        return []

    devices = []
    lines = output.strip().split('\n')

    for line in lines:
        if '|' not in line:
            continue

        parts = [p.strip() for p in line.split('|') if p.strip()]
        if len(parts) >= 6:
            try:
                device = {
                    'id': parts[0].strip(),
                    'name': parts[1].strip(),
                    'temp': parts[2].strip(),
                    'power': parts[3].strip(),
                    'memory_usage': parts[4].strip(),
                    'utilization': parts[5].strip()
                }
                devices.append(device)
            except Exception as e:
                print(f"解析NPU信息失败: {e}")
                continue

    return devices

def parse_nvidia_smi(output):
    """解析nvidia-smi输出"""
    if not output:
        return []

    devices = []
    import re

    print("=== nvidia-smi 原始输出 ===")
    print(output)
    print("=== 结束 ===\n")

    lines = [line.strip() for line in output.split('\n') if line.strip()]

    # 查找包含 GPU 信息的那一行（通常是包含显卡名称的那一行）
    gpu_info_line = None
    for line in lines:
        # 排除表头和分隔符
        if '----' in line or 'NVIDIA-SMI' in line:
            continue
        # 匹配以数字开头、包含 "NVIDIA" 的行（如：|   0  NVIDIA GeForce RTX ...）
        if re.match(r'.*\d+\s+NVIDIA', line) and '|' in line:
            gpu_info_line = line
            print(f"找到 GPU 行: {gpu_info_line}")
            break

    if not gpu_info_line:
        print("未找到GPU信息行")
        return devices

    try:
        # 提取 GPU ID 和名称
        # 示例: "|   0  NVIDIA GeForce RTX 4060      WDDM  |   00000000:2B:00.0  On |"
        gpu_parts = [p.strip() for p in gpu_info_line.split('|') if p.strip()]
        if len(gpu_parts) < 1:
            print("GPU信息分割失败")
            return devices

        gpu_main_info = gpu_parts[0]
        print(f"GPU主要信息: {gpu_main_info}")

        # 提取GPU ID和名称
        id_name_match = re.match(r'(\d+)\s+([A-Za-z0-9\s\-]+?)(?:\s+(WDDM|TCC))?$', gpu_main_info)
        if not id_name_match:
            print("无法提取GPU ID和名称")
            return devices

        gpu_id = id_name_match.group(1)
        gpu_name = id_name_match.group(2).strip()
        print(f"GPU ID: {gpu_id}, 名称: {gpu_name}")

        # 查找下一行 —— 性能与功耗等数据
        try:
            gpu_line_idx = lines.index(gpu_info_line)
            if gpu_line_idx + 1 >= len(lines):
                print("没有后续行可供解析")
                return devices

            usage_line = lines[gpu_line_idx + 1]
            print(f"性能行: {usage_line}")
        except (IndexError, ValueError):
            print("无法获取性能数据行")
            return devices

        # 解析第二行：|  0%   37C    P8            N/A  /  115W |    1609MiB /   8188MiB |      0%      Default |
        parts = [part.strip() for part in usage_line.split('|')]
        # 我们关心的是中间三块：
        # parts[1]: Fan, Temp, Perf, Power
        # parts[2]: Memory Usage
        # parts[3]: GPU-Util, Compute M.

        if len(parts) < 4:
            print(f"性能行分割后只有 {len(parts)} 部分，不足4部分")
            return devices

        perf_part = parts[1]  # "0%   37C    P8            N/A  /  115W"
        mem_part = parts[2]   # "1609MiB /   8188MiB"
        util_part = parts[3]  # "0%      Default"

        print(f"性能部分: {perf_part}")
        print(f"显存部分: {mem_part}")
        print(f"利用率部分: {util_part}")

        # === 提取温度 ===
        temp_match = re.search(r'(\d+)C', perf_part)
        temperature = f"{temp_match.group(1)}°C" if temp_match else 'N/A'
        print(f"温度: {temperature}")

        # === 提取功耗 Usage / Cap ===
        power_match = re.search(r'(N/A|[\d\.]+)\s*/\s*([\d\.]+)W', perf_part)
        if power_match:
            usage = power_match.group(1)
            cap = power_match.group(2)
            # 统一格式：N/A / 115W 或 25W / 115W
            power_str = f"{usage} / {cap}W"
        else:
            power_str = "N/A / N/A"
        print(f"功耗: {power_str}")

        # === 提取显存使用 ===
        mem_match = re.search(r'(\d+)MiB\s*/\s*(\d+)MiB', mem_part)
        if mem_match:
            used_mem = mem_match.group(1)
            total_mem = mem_match.group(2)
            memory_str = f"{used_mem}MB / {total_mem}MB"
        else:
            memory_str = "N/A"
        print(f"显存: {memory_str}")

        # === 提取 GPU 利用率 ===
        util_match = re.search(r'(\d+)%(?:\s+|$)', util_part)
        utilization = f"{util_match.group(1)}%" if util_match else 'N/A'
        print(f"利用率: {utilization}")

        device = {
            'id': gpu_id,
            'name': gpu_name,
            'temp': temperature,
            'power': power_str,
            'memory_usage': memory_str,
            'utilization': utilization
        }

        devices.append(device)
        print(f"成功解析GPU信息: {device}")

    except Exception as e:
        print(f"解析GPU信息失败: {e}")
        print(f"原始数据: GPU行={gpu_info_line}")

    return devices

def get_server_info(server_config):
    """获取单个服务器信息"""
    server_name = server_config['name']
    host = server_config['host']
    server_type = server_config.get('type', 'gpu')

    # 检查是否为本地机器
    is_local = server_config.get('local', False) or host == 'localhost' or host == '127.0.0.1'

    try:
        if is_local:
            # 本地监控
            if server_type == 'npu':
                command = 'npu-smi info'
            else:
                command = 'nvidia-smi'

            output, error = execute_local_command(command)

            if error:
                return {
                    'name': server_name,
                    'host': host,
                    'status': 'error',
                    'error': error,
                    'devices': [],
                    'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }

            if server_type == 'npu':
                devices = parse_npu_smi(output)
            else:
                devices = parse_nvidia_smi(output)

            return {
                'name': server_name,
                'host': host,
                'status': 'online',
                'type': server_type,
                'devices': devices,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'local': True
            }

        else:
            # 远程监控 - 支持多种认证方式
            auth_config = server_config.get('auth')
            if not auth_config:
                # 兼容旧配置格式
                auth_config = {
                    'type': 'password',
                    'username': server_config.get('username'),
                    'password': server_config.get('password')
                }

            bastion_config = server_config.get('bastion')
            ssh = ssh_connect(
                host,
                server_config.get('port', 22),
                auth_config,
                bastion_config
            )

            if not ssh:
                return {
                    'name': server_name,
                    'host': host,
                    'status': 'offline',
                    'error': 'SSH连接失败',
                    'devices': [],
                    'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }

            if server_type == 'npu':
                command = 'npu-smi info'
            else:
                command = 'nvidia-smi'

            output, error = execute_command(ssh, command)
            ssh.close()

            if error:
                return {
                    'name': server_name,
                    'host': host,
                    'status': 'error',
                    'error': error,
                    'devices': [],
                    'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }

            if server_type == 'npu':
                devices = parse_npu_smi(output)
            else:
                devices = parse_nvidia_smi(output)

            return {
                'name': server_name,
                'host': host,
                'status': 'online',
                'type': server_type,
                'devices': devices,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'local': False
            }

    except Exception as e:
        return {
            'name': server_name,
            'host': host,
            'status': 'error',
            'error': str(e),
            'devices': [],
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

def update_all_servers():
    """更新所有服务器状态"""
    config = load_server_config()

    for server_config in config['servers']:
        try:
            server_info = get_server_info(server_config)
            server_status[server_config['host']] = server_info

            # 通过WebSocket推送更新
            socketio.emit('server_update', server_info)
        except Exception as e:
            print(f"更新服务器状态失败 {server_config['name']}: {e}")
            # 创建错误状态
            error_info = {
                'name': server_config['name'],
                'host': server_config['host'],
                'status': 'error',
                'error': str(e),
                'type': server_config.get('type', 'gpu'),
                'devices': [],
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'local': server_config.get('local', False)
            }
            server_status[server_config['host']] = error_info
            socketio.emit('server_update', error_info)

def background_update():
    """后台定时更新"""
    while True:
        try:
            update_all_servers()
        except Exception as e:
            print(f"后台更新失败: {e}")
        time.sleep(15)  # 每15秒更新一次，提高响应速度

@app.route('/')
def index():
    """主页面"""
    return render_template('index_modern.html')

@app.route('/classic')
def classic_index():
    """经典界面"""
    return render_template('index.html')

@app.route('/api/servers')
def get_servers():
    """获取所有服务器状态API"""
    return jsonify(list(server_status.values()))

@app.route('/api/servers/<host>')
def get_server(host):
    """获取单个服务器状态API"""
    if host in server_status:
        return jsonify(server_status[host])
    return jsonify({'error': 'Server not found'}), 404

@app.route('/api/refresh', methods=['POST'])
def refresh_servers():
    """手动刷新服务器状态"""
    # 重新加载配置文件并更新所有服务器状态
    update_all_servers()

    # 通过WebSocket通知所有客户端服务器状态更新
    socketio.emit('servers_refreshed', list(server_status.values()))
    print("手动刷新完成，已通知所有客户端更新服务器状态")

    return jsonify({'message': '刷新完成'})

@app.route('/api/config', methods=['GET'])
def get_config():
    """获取服务器配置"""
    config = load_server_config()
    return jsonify(config)

@app.route('/api/config', methods=['POST'])
def update_config():
    """更新服务器配置"""
    try:
        config = request.json
        if not isinstance(config, dict) or 'servers' not in config:
            return jsonify({'error': '配置格式错误'}), 400

        # 验证服务器配置
        for server in config['servers']:
            is_valid, error_msg = validate_server_config(server)
            if not is_valid:
                return jsonify({'error': error_msg}), 400

        # 保存配置
        if save_server_config(config):
            # 重新加载服务器状态
            update_all_servers()
            return jsonify({'message': '配置更新成功'})
        else:
            return jsonify({'error': '保存配置失败'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/server', methods=['POST'])
def add_server():
    """添加单个服务器"""
    try:
        server_config = request.json
        config = load_server_config()

        # 验证服务器配置
        is_valid, error_msg = validate_server_config(server_config)
        if not is_valid:
            return jsonify({'error': error_msg}), 400

        # 检查是否已存在相同名称或主机的服务器
        for existing_server in config['servers']:
            if existing_server['name'] == server_config['name']:
                return jsonify({'error': '服务器名称已存在'}), 400
            if existing_server['host'] == server_config['host']:
                return jsonify({'error': '服务器主机已存在'}), 400

        # 添加服务器
        config['servers'].append(server_config)

        if save_server_config(config):
            # 先保存配置，然后异步获取服务器状态
            print(f"服务器配置已保存: {server_config['name']}")

            # 立即通过WebSocket通知客户端配置已更新
            # 创建一个临时的服务器状态，显示为"连接中"
            temp_server_info = {
                'name': server_config['name'],
                'host': server_config['host'],
                'status': 'connecting',
                'type': server_config.get('type', 'gpu'),
                'devices': [],
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'local': server_config.get('local', False)
            }

            # 立即添加到服务器状态中
            server_status[server_config['host']] = temp_server_info

            # 立即通知客户端
            socketio.emit('servers_refreshed', list(server_status.values()))
            print(f"已立即通知所有客户端新增服务器: {server_config['name']}")

            # 在后台线程中获取详细的服务器状态
            def update_server_status():
                try:
                    print(f"开始在后台获取服务器状态: {server_config['name']}")
                    server_info = get_server_info(server_config)
                    server_status[server_config['host']] = server_info
                    # 再次通知客户端更新状态
                    socketio.emit('servers_refreshed', list(server_status.values()))
                    print(f"服务器状态更新完成: {server_config['name']} - {server_info['status']}")
                except Exception as e:
                    print(f"获取服务器状态失败: {server_config['name']} - {e}")
                    # 更新为错误状态
                    error_info = {
                        'name': server_config['name'],
                        'host': server_config['host'],
                        'status': 'error',
                        'error': str(e),
                        'type': server_config.get('type', 'gpu'),
                        'devices': [],
                        'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'local': server_config.get('local', False)
                    }
                    server_status[server_config['host']] = error_info
                    socketio.emit('servers_refreshed', list(server_status.values()))

            # 启动后台线程
            update_thread = threading.Thread(target=update_server_status, daemon=True)
            update_thread.start()

            return jsonify({'message': '服务器添加成功'})
        else:
            return jsonify({'error': '保存配置失败'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/server/<name>', methods=['DELETE'])
def delete_server(name):
    """删除服务器"""
    try:
        config = load_server_config()
        original_count = len(config['servers'])

        # 在删除前找到要删除的服务器
        server_to_delete = None
        for s in config['servers']:
            if s['name'] == name:
                server_to_delete = s
                break

        if not server_to_delete:
            return jsonify({'error': '服务器不存在'}), 404

        # 删除指定名称的服务器
        config['servers'] = [s for s in config['servers'] if s['name'] != name]

        if save_server_config(config):
            # 从状态中删除服务器
            if server_to_delete['host'] in server_status:
                del server_status[server_to_delete['host']]
                print(f"从内存中删除服务器: {server_to_delete['name']} ({server_to_delete['host']})")

            # 重新加载所有服务器状态（强制刷新）
            update_all_servers()

            # 通过WebSocket通知所有客户端服务器状态更新
            socketio.emit('servers_refreshed', list(server_status.values()))
            print(f"已通知所有客户端刷新服务器列表，当前服务器数量: {len(server_status)}")

            return jsonify({'message': '服务器删除成功'})
        else:
            return jsonify({'error': '保存配置失败'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    """客户端连接时发送当前状态"""
    emit('initial_data', list(server_status.values()))

@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开连接"""
    print("客户端断开连接")

@socketio.on('request_servers')
def handle_request_servers():
    """客户端请求刷新服务器列表"""
    print(f"收到客户端请求刷新服务器列表，当前服务器数量: {len(server_status)}")
    server_list = list(server_status.values())
    print(f"发送服务器列表给客户端，包含服务器: {[s['name'] for s in server_list]}")
    emit('servers_refreshed', server_list)

if __name__ == '__main__':
    # 初始化数据
    update_all_servers()

    # 启动后台更新线程
    update_thread = threading.Thread(target=background_update, daemon=True)
    update_thread.start()

    # 启动服务器
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)