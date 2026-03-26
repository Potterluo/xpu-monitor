from flask import Flask, render_template, jsonify, request, Response
import paramiko
import json
import threading
import time
import subprocess
import platform
import os
import re
import socket
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
import queue

app = Flask(__name__)
app.config['SECRET_KEY'] = 'npu-gpu-monitor-secret'

# 全局变量存储服务器状态
server_status = {}

# SSE客户端管理
sse_clients = set()  # 存储所有SSE客户端的队列
sse_clients_lock = threading.Lock()  # 保护sse_clients的锁

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
                    timeout=10,
                    banner_timeout=10,
                    auth_timeout=10
                )
            else:
                ssh.connect(
                    host, port=port,
                    username=auth_config['username'],
                    password=password,
                    timeout=10,
                    banner_timeout=10,
                    auth_timeout=10
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
                timeout=10,
                banner_timeout=10,
                auth_timeout=10
            )
        else:
            bastion_ssh.connect(
                bastion_config['host'],
                port=bastion_config.get('port', 22),
                username=bastion_config['auth']['username'],
                password=bastion_password,
                timeout=10,
                banner_timeout=10,
                auth_timeout=10
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
                timeout=10,
                banner_timeout=10,
                auth_timeout=10
            )
        else:
            ssh.connect(
                '127.0.0.1', port=channel,
                username=auth_config['username'],
                password=password,
                timeout=10,
                banner_timeout=10,
                auth_timeout=10
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

def execute_command(ssh, command, timeout=10):
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

def execute_local_command(command, timeout=15):
    """执行本地命令"""
    try:
        if platform.system() == 'Windows':
            # Windows系统使用shell=True
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        else:
            # Linux/Unix系统
            result = subprocess.run(command.split(), capture_output=True, text=True, timeout=timeout)

        return result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return None, "命令执行超时"
    except Exception as e:
        print(f"执行本地命令失败: {e}")
        return None, str(e)

def parse_npu_smi(output):
    """解析 npu-smi info 输出，支持双行表格结构"""
    if not output or not output.strip():
        return []

    lines = [line.rstrip() for line in output.split('\n') if line.strip()]
    devices = []

    # === 查找主表起始位置 ===
    header_idx = None
    for i, line in enumerate(lines):
        if 'NPU' in line and 'Name' in line and '|' in line:
            header_idx = i
            break
    if header_idx is None:
        print("⚠️ 未找到 NPU 表头")
        return []

    # 找到数据开始行（+= 分隔线之后）
    data_start_idx = None
    for i in range(header_idx + 1, len(lines)):
        if lines[i].strip().startswith('+='):
            data_start_idx = i + 1
            break
    if data_start_idx is None:
        print("⚠️ 未找到数据分隔线")
        return []

    # === 收集设备数据块（到进程表前停止）===
    device_lines = []
    for i in range(data_start_idx, len(lines)):
        line = lines[i]
        # 遇到进程表或其他新表就结束
        if '+-' in line and 'Process' in line:
            break
        if line.strip().startswith('|'):
            device_lines.append(line)

    if len(device_lines) == 0:
        print("⚠️ 未采集到任何设备行")
        return []

    # === 按每2行为一组解析 ===
    i = 0
    while i + 1 < len(device_lines):
        line1 = device_lines[i]
        line2 = device_lines[i + 1]
        i += 2

        # --- 解析第一行：| 0     910B4 | OK | 87.6        38 ... ---
        match1 = re.match(r'\|\s*(\d+)\s+([^\|]+?)\s*\|\s*([^|]+?)\s*\|\s*([\d.]+)\s+([\d.]+)', line1)
        if not match1:
            print(f"⚠️ 跳过第一行（格式不匹配）: {line1}")
            continue

        npu_id = match1.group(1)
        name = match1.group(2).strip()
        health = match1.group(3).strip()
        power = f"{float(match1.group(4)):.2f}W"
        temperature = f"{match1.group(5)}°C"

        # --- 解析第二行：| 0 | BusId | 68   0/0   27252/32768 | ---
        # 提取 AICore(%)
        aicore_match = re.search(r'\|\s*\d+\s*\|\s*[^\|]+\s*\|\s*([\d.]+)', line2)
        utilization = f"{int(float(aicore_match.group(1)))}%" if aicore_match else "0%"

        # 提取 HBM-Usage(MB) —— 最后一个数字对
        hbm_match = re.search(r'(\d+)\s*/\s*(\d+)\s*\|$', line2)
        if hbm_match:
            used = int(hbm_match.group(1))
            total = int(hbm_match.group(2))
            memory_usage = f"{used}MB / {total}MB"
        else:
            memory_usage = "N/A"

        # 构造设备信息
        device = {
            'id': npu_id,
            'name': name,
            'temp': temperature,
            'power': power,
            'memory_usage': memory_usage,
            'utilization': utilization,
            'health': health  # 可选字段
        }
        devices.append(device)

    return devices

def parse_nvidia_smi(output):
    """解析nvidia-smi输出，支持多卡"""
    if not output:
        return []

    devices = []
    import re

    print("=== nvidia-smi 原始输出 ===")
    print(output)
    print("=== 结束 ===\n")

    lines = [line for line in output.split('\n')]

    # 查找所有GPU信息块
    # 每个GPU有固定的4行格式：
    # |   0  NVIDIA H100 80GB HBM3  ...  | 00000000:18:00.0 Off | ... |
    # | N/A   34C    P0            116W /  700W | 79101MiB /  81559MiB | ... |
    # |                                         |                        | ... |
    # +-----------------------------------------+------------------------+...+

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # 查找GPU信息行（包含ID和名称）
        if not line or '|' not in line:
            i += 1
            continue

        # 排除表头和分隔符（更严格的过滤）
        if ('----' in line or 'NVIDIA-SMI' in line or '+=====' in line or
            '+---' in line or 'GPU  Name' in line or 'Fan  Temp' in line or
            'Processes:' in line or 'GPU   GI' in line):
            i += 1
            continue

        # 检查是否是GPU信息行（包含数字ID和NVIDIA）
        if re.search(r'\|\s*\d+\s+NVIDIA', line):
            print(f"找到GPU行: {line}")

            try:
                # 提取 GPU ID 和名称
                gpu_parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(gpu_parts) < 1:
                    i += 1
                    continue

                gpu_main_info = gpu_parts[0]
                print(f"GPU主要信息: {gpu_main_info}")

                # 提取GPU ID和名称 - 修复正则表达式
                # 匹配: "0  NVIDIA H100 80GB HBM3          On"
                id_name_match = re.match(r'(\d+)\s+([A-Za-z0-9\s\-]+?)(?:\s+(On|Off))?$', gpu_main_info)
                if not id_name_match:
                    print(f"无法提取GPU ID和名称: {gpu_main_info}")
                    i += 1
                    continue

                gpu_id = id_name_match.group(1)
                gpu_name = id_name_match.group(2).strip()
                print(f"GPU ID: {gpu_id}, 名称: {gpu_name}")

                # 查找下一行 —— 性能与功耗等数据
                if i + 1 >= len(lines):
                    print(f"GPU {gpu_id}: 没有后续行可供解析")
                    i += 1
                    continue

                usage_line = lines[i + 1].strip()
                print(f"性能行: {usage_line}")

                # 解析性能数据行
                parts = [part.strip() for part in usage_line.split('|')]

                if len(parts) < 4:
                    print(f"GPU {gpu_id}: 性能行分割后只有 {len(parts)} 部分，跳过")
                    i += 1
                    continue

                perf_part = parts[1]  # "N/A   34C    P0            116W /  700W"
                mem_part = parts[2]   # "79101MiB /  81559MiB"
                util_part = parts[3]  # "0%      Default"

                print(f"性能部分: {perf_part}")
                print(f"显存部分: {mem_part}")
                print(f"利用率部分: {util_part}")

                # === 提取温度 ===
                temp_match = re.search(r'(\d+)C', perf_part)
                temperature = f"{temp_match.group(1)}°C" if temp_match else 'N/A'
                print(f"温度: {temperature}")

                # === 提取功耗 Usage / Cap ===
                # 修复：更宽松的正则表达式来匹配功耗
                # 示例: "N/A   34C    P0            116W /  700W"
                # 需要找到类似 "116W /  700W" 或 "N/A /  700W" 的模式
                power_pattern = r'([N/A]+|[\d\.]+W)\s*/\s*([\d\.]+W|[\d\.]+)'
                power_match = re.search(power_pattern, perf_part)
                if power_match:
                    usage_raw = power_match.group(1)
                    cap_raw = power_match.group(2)

                    # 清理数据
                    usage_clean = usage_raw.replace('W', '').strip()
                    cap_clean = cap_raw.replace('W', '').strip()

                    # 统一格式
                    if usage_clean == 'N/A' or usage_clean == 'N/A':
                        power_str = f"N/A / {cap_clean}W"
                    else:
                        power_str = f"{usage_clean}W / {cap_clean}W"
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
                print(f"成功解析GPU信息: {device}\n")

            except Exception as e:
                print(f"解析GPU信息失败: {e}, 行: {line}")
                import traceback
                traceback.print_exc()

        i += 1

    print(f"总共解析到 {len(devices)} 个GPU设备")
    return devices

def get_storage_info(ssh=None, is_local=False):
    """获取存储空间信息"""
    storage_info = {}

    try:
        if is_local:
            # 本地存储检测
            # 检测根目录、home目录空间使用情况
            directories = ['/', '/home']
            if platform.system() == 'Windows':
                directories = ['C:', 'D:'] if os.path.exists('D:') else ['C:']

            for directory in directories:
                try:
                    if platform.system() == 'Windows':
                        command = f'wmic logicaldisk where "DeviceID=\'{directory}\'" get Size,FreeSpace /value'
                        output, error = execute_local_command(command)
                        if not error and output:
                            # 解析Windows输出
                            size_match = re.search(r'Size=(\d+)', output)
                            free_match = re.search(r'FreeSpace=(\d+)', output)
                            if size_match and free_match:
                                total_size = int(size_match.group(1))
                                free_space = int(free_match.group(1))
                                used_space = total_size - free_space
                                usage_percent = (used_space / total_size) * 100 if total_size > 0 else 0

                                storage_info[directory] = {
                                    'total': format_bytes(total_size),
                                    'used': format_bytes(used_space),
                                    'free': format_bytes(free_space),
                                    'usage_percent': round(usage_percent, 1),
                                    'status': 'warning' if usage_percent > 85 else 'normal'
                                }
                    else:
                        # Linux系统
                        output, error = execute_local_command(f'df -h {directory}')
                        if not error and output:
                            lines = output.strip().split('\n')
                            if len(lines) >= 2:
                                # 跳过标题行，解析数据行
                                data = lines[1].split()
                                if len(data) >= 6:
                                    total = data[1]
                                    used = data[2]
                                    available = data[3]
                                    usage = data[4].replace('%', '')

                                    storage_info[directory] = {
                                        'total': total,
                                        'used': used,
                                        'free': available,
                                        'usage_percent': int(usage),
                                        'status': 'warning' if int(usage) > 85 else 'normal'
                                    }
                except Exception as e:
                    print(f"检测目录 {directory} 失败: {e}")
                    continue
        else:
            # 远程存储检测
            directories = ['/', '/home']
            for directory in directories:
                try:
                    command = f'df -h {directory}'
                    output, error = execute_command(ssh, command)
                    if not error and output:
                        lines = output.strip().split('\n')
                        if len(lines) >= 2:
                            data = lines[1].split()
                            if len(data) >= 6:
                                total = data[1]
                                used = data[2]
                                available = data[3]
                                usage = data[4].replace('%', '')

                                storage_info[directory] = {
                                    'total': total,
                                    'used': used,
                                    'free': available,
                                    'usage_percent': int(usage),
                                    'status': 'warning' if int(usage) > 85 else 'normal'
                                }
                except Exception as e:
                    print(f"远程检测目录 {directory} 失败: {e}")
                    continue

    except Exception as e:
        print(f"获取存储信息失败: {e}")

    return storage_info

def get_docker_info(ssh=None, is_local=False):
    """获取Docker镜像和容器信息"""
    docker_info = {
        'images': [],
        'containers': [],
        'total_images_size': '0B',
        'total_containers_size': '0B'
    }

    try:
        if is_local:
            # 本地Docker检测
            # 检查Docker是否可用
            check_cmd = 'docker --version'
            output, error = execute_local_command(check_cmd)
            if error:
                # Docker不可用，返回空信息
                return docker_info

            # 获取镜像信息
            img_output, img_error = execute_local_command('docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"')
            if not img_error and img_output:
                lines = img_output.strip().split('\n')
                if len(lines) > 1:  # 跳过标题行
                    total_size = 0
                    for line in lines[1:]:
                        parts = line.split('\t')
                        if len(parts) >= 2:
                            name = parts[0]
                            size_str = parts[1]
                            size_bytes = parse_size_to_bytes(size_str)
                            total_size += size_bytes

                            docker_info['images'].append({
                                'name': name,
                                'size': size_str,
                                'size_bytes': size_bytes
                            })
                    docker_info['total_images_size'] = format_bytes(total_size)

            # 获取容器信息
            cont_output, cont_error = execute_local_command('docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Size}}"')
            if not cont_error and cont_output:
                lines = cont_output.strip().split('\n')
                if len(lines) > 1:  # 跳过标题行
                    total_size = 0
                    for line in lines[1:]:
                        parts = line.split('\t')
                        if len(parts) >= 2:
                            name = parts[0]
                            status = parts[1]
                            size_str = parts[2] if len(parts) > 2 else '0B'
                            size_bytes = parse_size_to_bytes(size_str)
                            total_size += size_bytes

                            docker_info['containers'].append({
                                'name': name,
                                'status': status,
                                'size': size_str,
                                'size_bytes': size_bytes,
                                'is_running': 'Up' in status
                            })
                    docker_info['total_containers_size'] = format_bytes(total_size)

        else:
            # 远程Docker检测
            # 检查Docker是否可用
            check_cmd = 'docker --version'
            output, error = execute_command(ssh, check_cmd)
            if error:
                return docker_info

            # 获取镜像信息
            img_output, img_error = execute_command(ssh, 'docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"')
            if not img_error and img_output:
                lines = img_output.strip().split('\n')
                if len(lines) > 1:
                    total_size = 0
                    for line in lines[1:]:
                        parts = line.split('\t')
                        if len(parts) >= 2:
                            name = parts[0]
                            size_str = parts[1]
                            size_bytes = parse_size_to_bytes(size_str)
                            total_size += size_bytes

                            docker_info['images'].append({
                                'name': name,
                                'size': size_str,
                                'size_bytes': size_bytes
                            })
                    docker_info['total_images_size'] = format_bytes(total_size)

            # 获取容器信息
            cont_output, cont_error = execute_command(ssh, 'docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Size}}"')
            if not cont_error and cont_output:
                lines = cont_output.strip().split('\n')
                if len(lines) > 1:
                    total_size = 0
                    for line in lines[1:]:
                        parts = line.split('\t')
                        if len(parts) >= 2:
                            name = parts[0]
                            status = parts[1]
                            size_str = parts[2] if len(parts) > 2 else '0B'
                            size_bytes = parse_size_to_bytes(size_str)
                            total_size += size_bytes

                            docker_info['containers'].append({
                                'name': name,
                                'status': status,
                                'size': size_str,
                                'size_bytes': size_bytes,
                                'is_running': 'Up' in status
                            })
                    docker_info['total_containers_size'] = format_bytes(total_size)

    except Exception as e:
        print(f"获取Docker信息失败: {e}")

    return docker_info

def parse_size_to_bytes(size_str):
    """将大小字符串转换为字节数"""
    if not size_str or size_str == '0B':
        return 0

    size_str = size_str.strip().upper()
    if size_str.endswith('KB'):
        return float(size_str[:-2]) * 1024
    elif size_str.endswith('MB'):
        return float(size_str[:-2]) * 1024 * 1024
    elif size_str.endswith('GB'):
        return float(size_str[:-2]) * 1024 * 1024 * 1024
    elif size_str.endswith('TB'):
        return float(size_str[:-2]) * 1024 * 1024 * 1024 * 1024
    elif size_str.endswith('B'):
        return float(size_str[:-1])
    else:
        # 尝试直接解析为数字
        try:
            return float(size_str)
        except:
            return 0

def format_bytes(bytes_value):
    """格式化字节数为可读字符串"""
    if bytes_value == 0:
        return "0B"

    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.1f}{unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f}PB"

def get_storage_optimization_suggestions(storage_info, docker_info, llm_config=None):
    """获取存储优化建议"""
    suggestions = []

    # 基础规则建议
    for mount_point, info in storage_info.items():
        if info['usage_percent'] > 90:
            suggestions.append({
                'type': 'critical',
                'target': mount_point,
                'message': f"{mount_point} 目录使用率达到 {info['usage_percent']}%，急需清理！",
                'actions': [
                    '清理临时文件：rm -rf /tmp/*',
                    '清理日志文件：journalctl --vacuum-time=7d',
                    '查找大文件：find {mount_point} -type f -size +1G -exec ls -lh {{}} \\;'
                ]
            })
        elif info['usage_percent'] > 80:
            suggestions.append({
                'type': 'warning',
                'target': mount_point,
                'message': f"{mount_point} 目录使用率达到 {info['usage_percent']}%，建议清理",
                'actions': [
                    '清理包管理器缓存：apt-get clean (Ubuntu/Debian) 或 yum clean all (CentOS)',
                    '清理旧内核：apt autoremove --purge',
                    '检查用户目录：du -sh {mount_point}/home/*'
                ]
            })

    # Docker相关建议
    if docker_info['images']:
        total_images_size = parse_size_to_bytes(docker_info['total_images_size'])
        if total_images_size > 5 * 1024 * 1024 * 1024:  # 超过5GB
            suggestions.append({
                'type': 'docker',
                'target': 'docker_images',
                'message': f"Docker镜像占用 {docker_info['total_images_size']} 空间",
                'actions': [
                    '清理无用镜像：docker image prune -a',
                    '清理悬空镜像：docker rmi $(docker images -f "dangling=true" -q)',
                    '查看镜像大小：docker images --format "table {{.Repository}}\t{{.Size}}" | sort -k2 -hr'
                ]
            })

    stopped_containers = [c for c in docker_info['containers'] if not c['is_running']]
    if len(stopped_containers) > 5:
        suggestions.append({
            'type': 'docker',
            'target': 'docker_containers',
            'message': f"发现 {len(stopped_containers)} 个停止的容器",
            'actions': [
                '清理停止的容器：docker container prune',
                '批量删除：docker rm $(docker ps -a -q -f status=exited)',
                '查看容器详情：docker ps -a --format "table {{.Names}}\t{{.Status}}"'
            ]
        })

    # 如果配置了LLM，获取智能建议
    if llm_config and llm_config.get('enabled', False):
        print(f"LLM已启用，开始获取智能建议...")
        try:
            llm_suggestions = get_llm_storage_suggestions(storage_info, docker_info, llm_config)
            print(f"LLM返回建议数量: {len(llm_suggestions) if llm_suggestions else 0}")
            if llm_suggestions:
                suggestions.extend(llm_suggestions)
                print(f"已添加LLM建议，总建议数量: {len(suggestions)}")
        except Exception as e:
            print(f"获取LLM建议失败: {e}")
    else:
        print(f"LLM未配置或未启用: {llm_config}")

    return suggestions

def get_llm_storage_suggestions(storage_info, docker_info, llm_config):
    """使用LLM获取智能存储优化建议"""
    try:
        print(f"开始调用LLM API...")

        # 准备存储信息摘要
        storage_summary = []
        for mount_point, info in storage_info.items():
            storage_summary.append(f"{mount_point}: {info['used']}/{info['total']} ({info['usage_percent']}%)")

        docker_summary = []
        if docker_info['images']:
            docker_summary.append(f"Docker镜像: {len(docker_info['images'])}个，总计 {docker_info['total_images_size']}")
        if docker_info['containers']:
            running = len([c for c in docker_info['containers'] if c['is_running']])
            stopped = len(docker_info['containers']) - running
            docker_summary.append(f"Docker容器: {running}个运行中, {stopped}个已停止")

        # 构建提示词 - 使用英文以获得更好的结果
        prompt = f"""Analyze storage usage and provide optimization suggestions:

Storage: {chr(10).join(storage_summary)}
Docker: {chr(10).join(docker_summary)}

Provide 3-5 practical optimization suggestions in JSON array format:
[{{"type": "critical|warning|info", "target": "target", "message": "problem description", "actions": ["command1", "command2"], "effect": "expected effect", "risk": "risk warning"}}]

Suggestions should be specific, actionable, and safe for system administrators."""

        # 调用LLM API
        api_url = llm_config.get('api_url')
        api_key = llm_config.get('api_key')
        model = llm_config.get('model', 'gpt-3.5-turbo')

        print(f"LLM API URL: {api_url}")
        print(f"LLM Model: {model}")

        if not api_url or not api_key:
            print(f"LLM API配置不完整: api_url={bool(api_url)}, api_key={bool(api_key)}")
            return []

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        data = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': 'You are a professional system administrator specializing in storage optimization and system maintenance.'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.7
        }

        print(f"发送请求到LLM API...")
        response = requests.post(api_url, headers=headers, json=data, timeout=90)
        response.raise_for_status()
        print(f"LLM API响应状态: {response.status_code}")

        result = response.json()
        print(f"LLM API响应结构: {list(result.keys())}")

        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0]['message']['content']
            print(f"LLM原始响应内容: {content[:200]}...")
            # 尝试解析JSON响应
            try:
                suggestions = json.loads(content)
                print(f"成功解析LLM建议，数量: {len(suggestions)}")
                return suggestions
            except json.JSONDecodeError as e:
                # 如果解析失败，返回空列表
                print(f"LLM返回的不是有效的JSON: {e}")
                print(f"原始内容: {content}")
                return []
        else:
            print(f"LLM API响应格式异常，缺少choices字段")
            return []

    except requests.exceptions.Timeout:
        print(f"调用LLM API超时")
        return []
    except requests.exceptions.RequestException as e:
        print(f"调用LLM API请求失败: {e}")
        return []
    except Exception as e:
        print(f"调用LLM API失败: {e}")
        return []

def get_server_info(server_config):
    """获取单个服务器信息"""
    server_name = server_config['name']
    host = server_config['host']
    server_type = server_config.get('type', 'gpu')

    # 检查是否为本地机器
    is_local = server_config.get('local', False) or host == 'localhost' or host == '127.0.0.1'

    # 获取存储监控配置
    enable_storage = server_config.get('enable_storage_monitoring', True)
    enable_docker = server_config.get('enable_docker_monitoring', True)

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

            # 获取存储信息
            storage_info = {}
            docker_info = {'images': [], 'containers': [], 'total_images_size': '0B', 'total_containers_size': '0B'}

            if enable_storage:
                storage_info = get_storage_info(is_local=True)

            if enable_docker:
                docker_info = get_docker_info(is_local=True)

            return {
                'name': server_name,
                'host': host,
                'status': 'online',
                'type': server_type,
                'devices': devices,
                'storage': storage_info,
                'docker': docker_info,
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

            # 获取存储信息
            storage_info = {}
            docker_info = {'images': [], 'containers': [], 'total_images_size': '0B', 'total_containers_size': '0B'}

            if enable_storage:
                storage_info = get_storage_info(ssh=ssh, is_local=False)

            if enable_docker:
                docker_info = get_docker_info(ssh=ssh, is_local=False)

            ssh.close()

            if error:
                return {
                    'name': server_name,
                    'host': host,
                    'status': 'error',
                    'error': error,
                    'devices': [],
                    'storage': storage_info,
                    'docker': docker_info,
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
                'storage': storage_info,
                'docker': docker_info,
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
            'storage': {},
            'docker': {'images': [], 'containers': [], 'total_images_size': '0B', 'total_containers_size': '0B'},
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

def update_single_server(server_config):
    """更新单个服务器状态 - 用于并发执行"""
    server_name = server_config.get('name', 'Unknown')
    server_host = server_config.get('host', 'Unknown')
    
    try:
        print(f"开始更新服务器: {server_name} ({server_host})")
        server_info = get_server_info(server_config)
        print(f"服务器更新完成: {server_name} ({server_host}) - 状态: {server_info.get('status', 'unknown')}")
        return server_config['host'], server_info, None
    except Exception as e:
        error_msg = str(e)
        print(f"更新服务器状态失败 {server_name} ({server_host}): {error_msg}")
        # 创建错误状态
        error_info = {
            'name': server_name,
            'host': server_host,
            'status': 'error',
            'error': error_msg,
            'type': server_config.get('type', 'gpu'),
            'devices': [],
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'local': server_config.get('local', False)
        }
        return server_config['host'], error_info, error_msg

def update_all_servers():
    """并发更新所有服务器状态"""
    print("开始更新所有服务器状态...")

    try:
        config = load_server_config()
        servers = config['servers']

        if not servers:
            # 即使没有服务器，也要发送空数据以保持连接活跃
            broadcast_to_sse_clients({
                'type': 'servers_refreshed',
                'data': []
            })
            print("没有配置服务器，发送空数据")
            return

        # 使用线程池并发获取服务器状态
        max_workers = min(len(servers), 6)  # 限制最大并发数为6，避免过多连接

        print(f"开始并发更新 {len(servers)} 个服务器，使用 {max_workers} 个线程")

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ServerUpdate") as executor:
            # 提交所有任务
            future_to_server = {
                executor.submit(update_single_server, server_config): server_config
                for server_config in servers
            }

            # 收集所有结果，设置超时时间
            results = []
            timeout_count = 0

            for future in as_completed(future_to_server, timeout=60):  # 60秒超时
                server_config = future_to_server[future]
                try:
                    host, server_info, error = future.result(timeout=5)  # 5秒超时
                    server_status[host] = server_info
                    results.append(server_info)
                    status = server_info.get('status', 'unknown')
                    print(f"服务器 {server_info.get('name', 'Unknown')} 更新完成: {status}")

                except Exception as e:
                    timeout_count += 1
                    server_name = server_config.get('name', 'Unknown')
                    server_host = server_config.get('host', 'Unknown')
                    print(f"处理服务器 {server_name} ({server_host}) 的结果时出错: {e}")
                    error_info = {
                        'name': server_name,
                        'host': server_host,
                        'status': 'error',
                        'error': f'处理超时或异常: {str(e)}',
                        'type': server_config.get('type', 'gpu'),
                        'devices': [],
                        'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'local': server_config.get('local', False)
                    }
                    server_status[server_config['host']] = error_info
                    results.append(error_info)

            # 处理超时的任务
            if timeout_count > 0:
                print(f"有 {timeout_count} 个服务器更新任务超时")

        # 按照配置文件顺序排序结果
        ordered_results = []
        for server_config in servers:
            host = server_config['host']
            if host in server_status:
                ordered_results.append(server_status[host])

        # 批量发送所有服务器更新
        print(f"所有服务器更新完成，共 {len(ordered_results)} 个服务器")
        broadcast_to_sse_clients({
            'type': 'servers_refreshed',
            'data': ordered_results
        })

    except Exception as e:
        print(f"更新所有服务器状态时发生错误: {e}")
        # 发送错误信息给客户端
        broadcast_to_sse_clients({
            'type': 'servers_refreshed',
            'data': [{
                'name': '系统',
                'host': 'system',
                'status': 'error',
                'error': f'更新服务器列表时发生错误: {str(e)}',
                'type': 'system',
                'devices': [],
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'local': True
            }]
        })

def broadcast_to_sse_clients(data):
    """向所有SSE客户端广播数据"""
    with sse_clients_lock:
        client_count = len(sse_clients)

    print(f"准备广播数据类型: {data.get('type', 'unknown')}, 当前客户端数量: {client_count}")

    if client_count == 0:
        print("没有SSE客户端连接，跳过广播")
        return

    message = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    # 使用锁保护对sse_clients的访问
    with sse_clients_lock:
        clients_copy = sse_clients.copy()

    disconnected_clients = set()
    success_count = 0

    for client_queue in clients_copy:
        try:
            client_queue.put(message, block=False)
            success_count += 1
        except queue.Full:
            print(f"SSE客户端队列已满，跳过消息: {data.get('type', 'unknown')}")
        except Exception as e:
            print(f"向SSE客户端发送数据失败: {e}")
            disconnected_clients.add(client_queue)

    print(f"成功广播到 {success_count}/{client_count} 个SSE客户端")

    # 清理断开连接的客户端
    if disconnected_clients:
        with sse_clients_lock:
            for client in disconnected_clients:
                sse_clients.discard(client)
            print(f"清理了 {len(disconnected_clients)} 个断开的客户端")

def background_update():
    """后台定时更新"""
    print("后台更新线程已启动")

    # 启动时先执行一次更新
    try:
        print("应用启动时执行初始服务器更新")
        update_all_servers()
        print("初始服务器更新完成")
    except Exception as e:
        print(f"初始服务器更新失败: {e}")

    # 然后进入定时更新循环
    while True:
        try:
            print(f"开始后台定时更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            update_all_servers()
            print(f"后台定时更新完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            print(f"后台更新失败: {e}")
        time.sleep(30)  # 每30秒更新一次，与SSE客户端同步

@app.route('/')
def index():
    """主页面"""
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
    print("收到手动刷新请求")
    
    try:
        # 重新加载配置文件并更新所有服务器状态
        update_all_servers()
        print("手动刷新完成")
        return jsonify({'message': '刷新完成'})
    except Exception as e:
        print(f"手动刷新失败: {e}")
        return jsonify({'error': str(e)}), 500

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
            print(f"服务器配置已保存: {server_config['name']}")

            # 立即通知客户端配置已更新
            broadcast_to_sse_clients({
                'type': 'servers_refreshed',
                'data': list(server_status.values())
            })
            print(f"已通知所有客户端服务器配置更新: {server_config['name']}")

            # 在后台线程中获取详细的服务器状态
            def update_server_status():
                try:
                    print(f"开始在后台获取服务器状态: {server_config['name']}")
                    server_info = get_server_info(server_config)
                    server_status[server_config['host']] = server_info
                    # 通知客户端更新状态
                    broadcast_to_sse_clients({
                        'type': 'servers_refreshed',
                        'data': list(server_status.values())
                    })
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
                    broadcast_to_sse_clients({
                        'type': 'servers_refreshed',
                        'data': list(server_status.values())
                    })

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

            # 通过SSE通知所有客户端服务器状态更新
            broadcast_to_sse_clients({
                'type': 'servers_refreshed',
                'data': list(server_status.values())
            })
            print(f"已通知所有客户端刷新服务器列表，当前服务器数量: {len(server_status)}")

            return jsonify({'message': '服务器删除成功'})
        else:
            return jsonify({'error': '保存配置失败'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/storage/suggestions/<host>', methods=['GET'])
def get_storage_suggestions(host):
    """获取指定服务器的存储优化建议"""
    try:
        if host not in server_status:
            return jsonify({'error': '服务器不存在'}), 404

        server_info = server_status[host]
        storage_info = server_info.get('storage', {})
        docker_info = server_info.get('docker', {'images': [], 'containers': [], 'total_images_size': '0B', 'total_containers_size': '0B'})

        # 获取LLM配置
        config = load_server_config()
        llm_config = config.get('llm_config', {})

        # 生成优化建议
        suggestions = get_storage_optimization_suggestions(storage_info, docker_info, llm_config)

        return jsonify({
            'server': server_info['name'],
            'host': host,
            'storage_info': storage_info,
            'docker_info': docker_info,
            'suggestions': suggestions,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/storage/analyze', methods=['POST'])
def analyze_storage():
    """分析多个服务器的存储状况并生成综合建议"""
    try:
        data = request.json
        hosts = data.get('hosts', [])

        if not hosts:
            # 如果没有指定主机，分析所有服务器
            hosts = list(server_status.keys())

        analysis_results = []
        total_suggestions = []

        for host in hosts:
            if host in server_status:
                server_info = server_status[host]
                storage_info = server_info.get('storage', {})
                docker_info = server_info.get('docker', {'images': [], 'containers': [], 'total_images_size': '0B', 'total_containers_size': '0B'})

                # 获取LLM配置
                config = load_server_config()
                llm_config = config.get('llm_config', {})

                # 生成优化建议
                suggestions = get_storage_optimization_suggestions(storage_info, docker_info, llm_config)

                analysis_results.append({
                    'server': server_info['name'],
                    'host': host,
                    'storage_info': storage_info,
                    'docker_info': docker_info,
                    'suggestions_count': len(suggestions),
                    'critical_issues': len([s for s in suggestions if s.get('type') == 'critical']),
                    'warning_issues': len([s for s in suggestions if s.get('type') == 'warning'])
                })

                total_suggestions.extend(suggestions)

        # 生成综合统计
        summary = {
            'total_servers': len(analysis_results),
            'servers_with_issues': len([r for r in analysis_results if r['suggestions_count'] > 0]),
            'total_critical_issues': sum(r['critical_issues'] for r in analysis_results),
            'total_warning_issues': sum(r['warning_issues'] for r in analysis_results),
            'most_common_issues': _get_most_common_issues(total_suggestions)
        }

        return jsonify({
            'summary': summary,
            'server_analysis': analysis_results,
            'all_suggestions': total_suggestions,
            'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def _get_most_common_issues(suggestions):
    """获取最常见的问题类型"""
    if not suggestions:
        return []

    issue_counts = {}
    for suggestion in suggestions:
        target = suggestion.get('target', 'unknown')
        if target not in issue_counts:
            issue_counts[target] = 0
        issue_counts[target] += 1

    # 按出现频次排序，返回前5个最常见的问题
    sorted_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)
    return [{'target': target, 'count': count} for target, count in sorted_issues[:5]]

@app.route('/api/config/llm', methods=['GET'])
def get_llm_config():
    """获取LLM配置"""
    try:
        config = load_server_config()
        llm_config = config.get('llm_config', {})
        return jsonify(llm_config)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/llm', methods=['POST'])
def update_llm_config():
    """更新LLM配置"""
    try:
        llm_config = request.json
        config = load_server_config()

        # 验证LLM配置
        if llm_config.get('enabled', False):
            if not llm_config.get('api_url') or not llm_config.get('api_key'):
                return jsonify({'error': '启用LLM时必须提供API URL和API密钥'}), 400

        # 保存配置
        config['llm_config'] = llm_config
        if save_server_config(config):
            return jsonify({'message': 'LLM配置更新成功'})
        else:
            return jsonify({'error': '保存配置失败'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sse')
def sse_stream():
    """SSE流式接口"""
    def generate():
        # 为每个客户端创建一个队列，设置最大容量以避免内存泄漏
        client_queue = Queue(maxsize=100)

        # 添加客户端到集合
        with sse_clients_lock:
            sse_clients.add(client_queue)

        try:
            # 如果还没有服务器状态数据，先触发一次更新
            if not server_status:
                print("SSE客户端连接时服务器状态为空，触发初始更新")
                # 同步执行一次更新以确保有数据发送
                config = load_server_config()
                servers = config['servers']

                if servers:
                    # 使用线程池同步获取服务器状态
                    max_workers = min(len(servers), 6)

                    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="SSEInit") as executor:
                        future_to_server = {
                            executor.submit(update_single_server, server_config): server_config
                            for server_config in servers
                        }

                        for future in as_completed(future_to_server, timeout=60):
                            server_config = future_to_server[future]
                            try:
                                host, server_info, error = future.result(timeout=5)
                                server_status[host] = server_info
                            except Exception as e:
                                server_name = server_config.get('name', 'Unknown')
                                server_host = server_config.get('host', 'Unknown')
                                print(f"SSE初始化时处理服务器 {server_name} ({server_host}) 失败: {e}")
                                error_info = {
                                    'name': server_name,
                                    'host': server_host,
                                    'status': 'error',
                                    'error': f'初始化失败: {str(e)}',
                                    'type': server_config.get('type', 'gpu'),
                                    'devices': [],
                                    'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    'local': server_config.get('local', False)
                                }
                                server_status[server_config['host']] = error_info

            # 按照配置文件顺序获取服务器状态
            config = load_server_config()
            servers = config['servers']
            ordered_results = []
            for server_config in servers:
                host = server_config['host']
                if host in server_status:
                    ordered_results.append(server_status[host])

            # 发送初始数据
            initial_data = {
                'type': 'initial_data',
                'data': ordered_results
            }
            yield f"data: {json.dumps(initial_data, ensure_ascii=False)}\n\n"
            print(f"SSE客户端连接，发送初始数据: {len(ordered_results)} 个服务器")

            # 持续监听队列中的消息
            heartbeat_count = 0
            while True:
                try:
                    # 设置25秒超时，用于定期心跳（小于30秒以避免超时）
                    message = client_queue.get(timeout=25)
                    yield message
                except queue.Empty:
                    # 每2次心跳（约50秒）触发一次服务器更新
                    heartbeat_count += 1
                    if heartbeat_count % 2 == 0:
                        print("SSE心跳触发服务器状态更新")
                        # 在单独线程中触发更新，避免阻塞SSE流
                        update_thread = threading.Thread(target=update_all_servers, daemon=True)
                        update_thread.start()

                    # 发送心跳消息保持连接
                    heartbeat = {
                        'type': 'heartbeat',
                        'timestamp': datetime.now().isoformat(),
                        'update_triggered': heartbeat_count % 2 == 0
                    }
                    yield f"data: {json.dumps(heartbeat, ensure_ascii=False)}\n\n"

        except GeneratorExit:
            # 客户端断开连接
            print("SSE客户端断开连接")
        except Exception as e:
            print(f"SSE流生成异常: {e}")
        finally:
            # 清理客户端队列
            with sse_clients_lock:
                sse_clients.discard(client_queue)
            # 清空队列中的剩余消息
            while not client_queue.empty():
                try:
                    client_queue.get_nowait()
                except queue.Empty:
                    break

    return Response(generate(), mimetype='text/event-stream',
                   headers={
                       'Cache-Control': 'no-cache',
                       'Connection': 'keep-alive',
                       'Access-Control-Allow-Origin': '*',
                       'Access-Control-Allow-Headers': 'Cache-Control',
                       'X-Accel-Buffering': 'no'  # 禁用nginx缓冲
                   })

@app.route('/api/mock/data', methods=['GET'])
def get_mock_data():
    """获取mock数据用于前端测试"""
    import random

    mock_servers = [
        {
            'name': 'GPU服务器1',
            'host': '192.168.1.10',
            'status': 'online',
            'type': 'gpu',
            'devices': [
                {
                    'id': '0',
                    'name': 'NVIDIA RTX 4090',
                    'temp': '65°C',
                    'power': '350W / 450W',
                    'memory_usage': '12288MB / 24576MB',
                    'utilization': '85%'
                },
                {
                    'id': '1',
                    'name': 'NVIDIA RTX 4090',
                    'temp': '70°C',
                    'power': '380W / 450W',
                    'memory_usage': '16384MB / 24576MB',
                    'utilization': '92%'
                }
            ],
            'storage': {
                '/': {
                    'total': '500G',
                    'used': '425G',
                    'free': '75G',
                    'usage_percent': 85,
                    'status': 'warning'
                },
                '/home': {
                    'total': '1.0T',
                    'used': '600G',
                    'free': '424G',
                    'usage_percent': 60,
                    'status': 'normal'
                }
            },
            'docker': {
                'images': [
                    {'name': 'pytorch/pytorch:latest', 'size': '6.2GB', 'size_bytes': 6652164566},
                    {'name': 'tensorflow/tensorflow:latest', 'size': '4.8GB', 'size_bytes': 5153960755},
                    {'name': 'ubuntu:20.04', 'size': '72.8MB', 'size_bytes': 76336384}
                ],
                'containers': [
                    {'name': 'ml-training-1', 'status': 'Up 2 days', 'size': '12.3GB', 'size_bytes': 13207024435, 'is_running': True},
                    {'name': 'web-server', 'status': 'Up 5 hours', 'size': '256MB', 'size_bytes': 268435456, 'is_running': True},
                    {'name': 'db-container', 'status': 'Exited (0) 1 hour ago', 'size': '8.5GB', 'size_bytes': 9126805504, 'is_running': False}
                ],
                'total_images_size': '11.1GB',
                'total_containers_size': '21.1GB'
            },
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'local': False
        },
        {
            'name': 'NPU服务器1',
            'host': '192.168.1.20',
            'status': 'online',
            'type': 'npu',
            'devices': [
                {
                    'id': '0',
                    'name': 'Ascend 910B',
                    'temp': '72°C',
                    'power': '280W / 300W',
                    'memory_usage': '24576MB / 32768MB',
                    'utilization': '88%'
                },
                {
                    'id': '1',
                    'name': 'Ascend 910B',
                    'temp': '68°C',
                    'power': '260W / 300W',
                    'memory_usage': '20480MB / 32768MB',
                    'utilization': '75%'
                },
                {
                    'id': '2',
                    'name': 'Ascend 910B',
                    'temp': '75°C',
                    'power': '295W / 300W',
                    'memory_usage': '28672MB / 32768MB',
                    'utilization': '95%'
                },
                {
                    'id': '3',
                    'name': 'Ascend 910B',
                    'temp': '70°C',
                    'power': '270W / 300W',
                    'memory_usage': '16384MB / 32768MB',
                    'utilization': '68%'
                }
            ],
            'storage': {
                '/': {
                    'total': '2.0T',
                    'used': '1.8T',
                    'free': '200G',
                    'usage_percent': 90,
                    'status': 'warning'
                },
                '/home': {
                    'total': '4.0T',
                    'used': '1.2T',
                    'free': '2.8T',
                    'usage_percent': 30,
                    'status': 'normal'
                }
            },
            'docker': {
                'images': [
                    {'name': 'mindspore/mindspore:latest', 'size': '8.5GB', 'size_bytes': 9126805504},
                    {'name': 'ubuntu:18.04', 'size': '63.4MB', 'size_bytes': 66485781}
                ],
                'containers': [
                    {'name': 'npu-training-1', 'status': 'Up 3 days', 'size': '18.7GB', 'size_bytes': 20077964800, 'is_running': True},
                    {'name': 'npu-training-2', 'status': 'Up 1 day', 'size': '15.2GB', 'size_bytes': 16320875520, 'is_running': True}
                ],
                'total_images_size': '8.6GB',
                'total_containers_size': '33.9GB'
            },
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'local': False
        },
        {
            'name': '开发服务器',
            'host': '192.168.1.30',
            'status': 'online',
            'type': 'gpu',
            'devices': [
                {
                    'id': '0',
                    'name': 'NVIDIA RTX 3080',
                    'temp': '55°C',
                    'power': '180W / 320W',
                    'memory_usage': '6144MB / 10240MB',
                    'utilization': '45%'
                }
            ],
            'storage': {
                '/': {
                    'total': '1.0T',
                    'used': '450G',
                    'free': '575G',
                    'usage_percent': 45,
                    'status': 'normal'
                },
                '/home': {
                    'total': '2.0T',
                    'used': '800G',
                    'free': '1.2T',
                    'usage_percent': 40,
                    'status': 'normal'
                }
            },
            'docker': {
                'images': [
                    {'name': 'node:16-alpine', 'size': '45.6MB', 'size_bytes': 47815065},
                    {'name': 'nginx:alpine', 'size': '23.7MB', 'size_bytes': 24834134}
                ],
                'containers': [
                    {'name': 'web-app', 'status': 'Up 12 hours', 'size': '128MB', 'size_bytes': 134217728, 'is_running': True}
                ],
                'total_images_size': '69.3MB',
                'total_containers_size': '128MB'
            },
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'local': False
        },
        {
            'name': '单卡测试服务器',
            'host': '192.168.1.40',
            'status': 'online',
            'type': 'npu',
            'devices': [
                {
                    'id': '0',
                    'name': 'Ascend 310',
                    'temp': '42°C',
                    'power': '35W / 60W',
                    'memory_usage': '4096MB / 8192MB',
                    'utilization': '25%'
                }
            ],
            'storage': {
                '/': {
                    'total': '500G',
                    'used': '380G',
                    'free': '120G',
                    'usage_percent': 76,
                    'status': 'normal'
                }
            },
            'docker': {
                'images': [],
                'containers': [],
                'total_images_size': '0B',
                'total_containers_size': '0B'
            },
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'local': False
        },
        {
            'name': '高密度服务器',
            'host': '192.168.1.50',
            'status': 'online',
            'type': 'gpu',
            'devices': [
                {'id': str(i), 'name': 'NVIDIA A100', 'temp': f'{random.randint(60,80)}°C', 'power': f'{random.randint(300,400)}W / 400W', 'memory_usage': f'{random.randint(20480,38912)}MB / 40960MB', 'utilization': f'{random.randint(70,95)}%'}
                for i in range(8)
            ],
            'storage': {
                '/': {
                    'total': '5.0T',
                    'used': '4.2T',
                    'free': '800G',
                    'usage_percent': 84,
                    'status': 'warning'
                }
            },
            'docker': {
                'images': [
                    {'name': 'cuda:12.1', 'size': '15.2GB', 'size_bytes': 16320875520},
                    {'name': 'pytorch:2.0', 'size': '12.8GB', 'size_bytes': 13743895347}
                ],
                'containers': [
                    {'name': f'gpu-job-{i}', 'status': 'Up', 'size': f'{random.randint(5,20)}GB', 'size_bytes': random.randint(5368709120, 21474836480), 'is_running': True}
                    for i in range(5)
                ],
                'total_images_size': '28.0GB',
                'total_containers_size': '75.2GB'
            },
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'local': False
        }
    ]

    return jsonify(mock_servers)

if __name__ == '__main__':
    # 初始化数据
    update_all_servers()

    # 启动后台更新线程
    update_thread = threading.Thread(target=background_update, daemon=True)
    update_thread.start()

    # 启动服务器
    app.run(host='0.0.0.0', port=5000, debug=True)