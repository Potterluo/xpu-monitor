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

from logger import get_logger, LogTimer, setup_logging

setup_logging(level='INFO')

app = Flask(__name__)
app.config['SECRET_KEY'] = 'npu-gpu-monitor-secret'

log = get_logger('xpu-monitor')

server_status = {}
sse_clients = set()
sse_clients_lock = threading.Lock()



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
        log.error(f"保存配置文件失败: {e}")
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

            log.info(f"SSH连接成功: {host}:{port}")
            return ssh

    except paramiko.AuthenticationException:
        log.warning(f"SSH认证失败 {host}:{port}: 用户名或密码/密钥错误")
        if ssh:
            ssh.close()
        return None
    except paramiko.SSHException as e:
        error_msg = str(e).lower()
        if 'timed out' in error_msg:
            log.warning(f"SSH连接超时 {host}:{port}")
        elif 'connection refused' in error_msg:
            log.warning(f"SSH连接被拒绝 {host}:{port}: 服务可能未运行或端口被防火墙阻止")
        elif 'name or service not known' in error_msg or 'nodename nor servname provided' in error_msg:
            log.warning(f"SSH主机名解析失败 {host}:{port}: 主机名不存在或DNS问题")
        else:
            log.warning(f"SSH连接失败 {host}:{port}: {e}")
        if ssh:
            ssh.close()
        return None
    except socket.timeout:
        log.warning(f"SSH连接超时 {host}:{port}")
        if ssh:
            ssh.close()
        return None
    except Exception as e:
        log.error(f"SSH连接失败 {host}:{port}: {e}")
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

        log.info(f"跳板机连接成功: {bastion_config['host']}")

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
        log.warning(f"命令执行超时: {command}")
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
        log.error(f"执行本地命令失败: {e}")
        return None, str(e)

def parse_npu_smi(output):
    """解析 npu-smi info 输出，支持单芯片和多芯片（如Ascend910双芯）NPU"""
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
        log.debug("parse_npu_smi: 未找到 NPU 表头")
        return []

    # 找到数据区起始（表头后的分隔线之后）
    data_start_idx = None
    for i in range(header_idx + 1, len(lines)):
        if lines[i].strip().startswith('+=') or lines[i].strip().startswith('+=='):
            data_start_idx = i + 1
            break
    if data_start_idx is None:
        log.debug("parse_npu_smi: 未找到数据分隔线")
        return []

    # 收集所有数据行（跳过分隔线），在进程表前停止
    device_lines = []
    for i in range(data_start_idx, len(lines)):
        line = lines[i]
        if ('Process' in line and '+-' in line) or ('NPU     Chip' in line):
            break
        if line.strip().startswith('|') and 'NPU' not in line:
            device_lines.append(line)

    if len(device_lines) == 0:
        log.debug("parse_npu_smi: 未采集到任何设备行")
        return []

    # === 解析：逐行扫描，识别"上行"（含名称）和"下行"（含Chip/BusId/HBM） ===
    # 上行格式: | NPU_ID  Name  | Health | Power Temp ... |
    # 下行格式: | Chip  Phy-ID  | Bus-Id | AICore Memory-Usage HBM-Usage |

    i = 0
    while i < len(device_lines):
        line = device_lines[i]

        # 跳过分隔线
        if line.strip().startswith('+=') or line.strip().startswith('+--'):
            i += 1
            continue

        # 尝试匹配上行（含 NPU 名称）
        upper_match = re.match(r'\|\s*(\d+)\s+([^\|]+?)\s*\|\s*([^|]+?)\s*\|\s*([\d.-]+)\s+([\d.-]+)', line)
        if not upper_match:
            i += 1
            continue

        npu_id = upper_match.group(1)
        name = upper_match.group(2).strip()
        health = upper_match.group(3).strip()
        power_raw = upper_match.group(4).strip()
        temperature = upper_match.group(5).strip()

        # 处理无功耗显示的情况（如 "-"）
        power = f"{float(power_raw):.1f}W" if power_raw != '-' else 'N/A'

        # 查找紧接的下行
        chip_line = None
        if i + 1 < len(device_lines):
            next_line = device_lines[i + 1]
            if not next_line.strip().startswith('+=') and not next_line.strip().startswith('+--'):
                chip_line = next_line
                i += 2
            else:
                # 下行是分隔线，跳过
                i += 1
                if i + 1 < len(device_lines):
                    chip_line = device_lines[i]
                    i += 1
                else:
                    i += 1
        else:
            i += 1

        # 从下行提取 Chip ID, AICore, HBM
        chip_id = npu_id
        utilization = "0%"
        memory_usage = "N/A"

        if chip_line:
            # 提取 Phy-ID（下行第二个字段，全局芯片编号）
            chip_match = re.match(r'\|\s*\d+\s+(\d+)', chip_line)
            if chip_match:
                chip_id = chip_match.group(1)

            # 提取 AICore(%)
            aicore_match = re.search(r'\|\s*\d+\s+\d+\s*\|\s*[^\|]+\s*\|\s*([\d.]+)', chip_line)
            if aicore_match:
                utilization = f"{int(float(aicore_match.group(1)))}%"

            # 提取 HBM-Usage(MB) —— 最后一个数字对
            hbm_match = re.search(r'(\d+)\s*/\s*(\d+)\s*\|?\s*$', chip_line)
            if hbm_match:
                used = int(hbm_match.group(1))
                total = int(hbm_match.group(2))
                memory_usage = f"{used}MB / {total}MB"

        device = {
            'id': chip_id,
            'name': name,
            'temp': f"{temperature}°C" if temperature != '-' else 'N/A',
            'power': power,
            'memory_usage': memory_usage,
            'utilization': utilization,
            'health': health
        }
        devices.append(device)

    log.debug(f"parse_npu_smi: 解析到 {len(devices)} 个NPU设备")
    return devices

def parse_nvidia_smi(output):
    """解析nvidia-smi输出，支持多卡"""
    if not output:
        return []

    devices = []
    import re

    log.debug(f"nvidia-smi 输出长度: {len(output)} 字符")

    lines = [line for line in output.split('\n')]

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line or '|' not in line:
            i += 1
            continue

        if ('----' in line or 'NVIDIA-SMI' in line or '+=====' in line or
            '+---' in line or 'GPU  Name' in line or 'Fan  Temp' in line or
            'Processes:' in line or 'GPU   GI' in line):
            i += 1
            continue

        if re.search(r'\|\s*\d+\s+NVIDIA', line):
            log.debug(f"找到GPU行: {line}")

            try:
                gpu_parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(gpu_parts) < 1:
                    i += 1
                    continue

                gpu_main_info = gpu_parts[0]
                log.debug(f"GPU主要信息: {gpu_main_info}")

                # 提取GPU ID和名称 - 修复正则表达式
                # 匹配: "0  NVIDIA H100 80GB HBM3          On"
                id_name_match = re.match(r'(\d+)\s+([A-Za-z0-9\s\-]+?)(?:\s+(On|Off))?$', gpu_main_info)
                if not id_name_match:
                    log.debug(f"无法提取GPU ID和名称: {gpu_main_info}")
                    i += 1
                    continue

                gpu_id = id_name_match.group(1)
                gpu_name = id_name_match.group(2).strip()
                log.debug(f"GPU ID: {gpu_id}, 名称: {gpu_name}")

                if i + 1 >= len(lines):
                    log.debug(f"GPU {gpu_id}: 没有后续行可供解析")
                    i += 1
                    continue

                usage_line = lines[i + 1].strip()
                log.debug(f"性能行: {usage_line}")

                parts = [part.strip() for part in usage_line.split('|')]

                if len(parts) < 4:
                    log.debug(f"GPU {gpu_id}: 性能行分割后只有 {len(parts)} 部分，跳过")
                    i += 1
                    continue

                perf_part = parts[1]
                mem_part = parts[2]
                util_part = parts[3]

                log.debug(f"性能部分: {perf_part}, 显存部分: {mem_part}, 利用率部分: {util_part}")

                temp_match = re.search(r'(\d+)C', perf_part)
                temperature = f"{temp_match.group(1)}°C" if temp_match else 'N/A'

                power_pattern = r'([N/A]+|[\d\.]+W)\s*/\s*([\d\.]+W|[\d\.]+)'
                power_match = re.search(power_pattern, perf_part)
                if power_match:
                    usage_raw = power_match.group(1)
                    cap_raw = power_match.group(2)
                    usage_clean = usage_raw.replace('W', '').strip()
                    cap_clean = cap_raw.replace('W', '').strip()
                    if usage_clean == 'N/A' or usage_clean == 'N/A':
                        power_str = f"N/A / {cap_clean}W"
                    else:
                        power_str = f"{usage_clean}W / {cap_clean}W"
                else:
                    power_str = "N/A / N/A"

                mem_match = re.search(r'(\d+)MiB\s*/\s*(\d+)MiB', mem_part)
                if mem_match:
                    used_mem = mem_match.group(1)
                    total_mem = mem_match.group(2)
                    memory_str = f"{used_mem}MB / {total_mem}MB"
                else:
                    memory_str = "N/A"

                util_match = re.search(r'(\d+)%(?:\s+|$)', util_part)
                utilization = f"{util_match.group(1)}%" if util_match else 'N/A'

                device = {
                    'id': gpu_id,
                    'name': gpu_name,
                    'temp': temperature,
                    'power': power_str,
                    'memory_usage': memory_str,
                    'utilization': utilization
                }

                devices.append(device)
                log.debug(f"成功解析GPU: {device}")

            except Exception as e:
                log.warning(f"解析GPU信息失败: {e}, 行: {line}")

        i += 1

    print(f"总共解析到 {len(devices)} 个GPU设备")
    return devices

def get_storage_info(ssh=None, is_local=False, mounts=None):
    """获取存储空间信息 - 支持可配置挂载点"""
    storage_info = {}

    # 确定要检测的挂载点列表
    if mounts:
        directories = [m['path'] for m in mounts]
    else:
        # 兼容旧配置：默认检测 / 和 /home
        directories = ['/', '/home']

    if is_local and not mounts and platform.system() == 'Windows':
        directories = ['C:', 'D:'] if os.path.exists('D:') else ['C:']

    # 构建 path -> endpoint 映射
    path_endpoint_map = {}
    if mounts:
        for m in mounts:
            if 'endpoint' in m and m['endpoint']:
                path_endpoint_map[m['path']] = m['endpoint']

    try:
        for directory in directories:
            try:
                if is_local and platform.system() == 'Windows':
                    command = f'wmic logicaldisk where "DeviceID=\'{directory}\'" get Size,FreeSpace /value'
                    output, error = execute_local_command(command)
                    if not error and output:
                        size_match = re.search(r'Size=(\d+)', output)
                        free_match = re.search(r'FreeSpace=(\d+)', output)
                        if size_match and free_match:
                            total_size = int(size_match.group(1))
                            free_space = int(free_match.group(1))
                            used_space = total_size - free_space
                            usage_percent = (used_space / total_size) * 100 if total_size > 0 else 0

                            info = {
                                'total': format_bytes(total_size),
                                'used': format_bytes(used_space),
                                'free': format_bytes(free_space),
                                'usage_percent': round(usage_percent, 1),
                                'status': 'warning' if usage_percent > 85 else 'normal'
                            }
                            if directory in path_endpoint_map:
                                info['endpoint'] = path_endpoint_map[directory]
                            storage_info[directory] = info
                else:
                    # Linux系统（本地或远程）
                    if is_local:
                        output, error = execute_local_command(f'df -h {directory}')
                    else:
                        output, error = execute_command(ssh, f'df -h {directory}')

                    if not error and output:
                        lines = output.strip().split('\n')
                        if len(lines) >= 2:
                            data = lines[1].split()
                            if len(data) >= 6:
                                total = data[1]
                                used = data[2]
                                available = data[3]
                                usage = data[4].replace('%', '')

                                info = {
                                    'total': total,
                                    'used': used,
                                    'free': available,
                                    'usage_percent': int(usage),
                                    'status': 'warning' if int(usage) > 85 else 'normal'
                                }
                                if directory in path_endpoint_map:
                                    info['endpoint'] = path_endpoint_map[directory]
                                storage_info[directory] = info
            except Exception as e:
                log.warning(f"检测目录 {directory} 失败: {e}")
                continue

    except Exception as e:
        log.error(f"获取存储信息失败: {e}")

    return storage_info

def expand_endpoint_host(host_spec):
    """展开端点主机规格，支持多种格式：
    - 字符串单个IP: "192.168.0.1"
    - IP段: "192.168.1.101~108" 表示从192.168.1.101到192.168.1.108
    - 数组: ["192.168.0.1", "192.168.0.2", "192.168.0.5"]
    """
    if isinstance(host_spec, list):
        return host_spec
    if isinstance(host_spec, str) and '~' in host_spec:
        parts = host_spec.split('~')
        if len(parts) == 2:
            base_ip = parts[0]
            octets = base_ip.split('.')
            if len(octets) == 4:
                base_prefix = '.'.join(octets[:3])
                start = int(octets[3])
                end_part = parts[1].strip()
                if '.' in end_part:
                    # 完整IP格式: 192.168.1.101~192.168.1.108
                    end_octets = end_part.split('.')
                    end = int(end_octets[-1])
                else:
                    # 仅最后一段: 192.168.1.101~108
                    end = int(end_part)
                return [f"{base_prefix}.{i}" for i in range(start, end + 1)]
    return [host_spec]

def _ping_single_host(host, timeout, is_local, ssh=None):
    """检测单个主机的连通性"""
    try:
        if is_local:
            if platform.system() == 'Windows':
                output, error = execute_local_command(f'ping -n 1 -w {timeout * 1000} {host}', timeout=timeout + 2)
            else:
                output, error = execute_local_command(f'ping -c 1 -W {timeout} {host}', timeout=timeout + 2)
        else:
            output, error = execute_command(ssh, f'ping -c 1 -W {timeout} {host}', timeout=timeout + 2)

        if error or not output:
            return {'host': host, 'status': 'unreachable', 'latency': None}

        output_lower = output.lower()
        if '100% packet loss' in output_lower or 'unreachable' in output_lower or 'timed out' in output_lower or 'could not find host' in output_lower:
            return {'host': host, 'status': 'unreachable', 'latency': None}

        # 提取延迟
        latency_match = re.search(r'(?:min/avg/max|time[=<])([\d.]+)\s*ms', output, re.IGNORECASE)
        if not latency_match:
            latency_match = re.search(r'时间[=<]([\d.]+)ms', output, re.IGNORECASE)
        latency = latency_match.group(1) if latency_match else None

        return {'host': host, 'status': 'reachable', 'latency': latency}

    except Exception as e:
        print(f"检测端点连通性失败 {host}: {e}")
        return {'host': host, 'status': 'error', 'latency': None}


def check_endpoint_connectivity(endpoint_spec, ssh=None, is_local=False):
    """检测存储端点连通性（ping）- 并行检测多个IP"""
    timeout = 2  # 2秒超时
    hosts = expand_endpoint_host(endpoint_spec['host'])

    # 如果配置了名称，使用配置的名称；否则使用第一个IP作为名称
    ep_name = endpoint_spec.get('name', hosts[0])

    # 并行ping所有主机
    results = []
    if len(hosts) == 1:
        results = [_ping_single_host(hosts[0], timeout, is_local, ssh)]
    else:
        with ThreadPoolExecutor(max_workers=min(len(hosts), 16)) as executor:
            futures = {executor.submit(_ping_single_host, h, timeout, is_local, ssh): h for h in hosts}
            for future in as_completed(futures, timeout=timeout + 5):
                try:
                    results.append(future.result(timeout=timeout + 3))
                except Exception as e:
                    host = futures[future]
                    log.debug(f"ping {host} 超时: {e}")
                    results.append({'host': host, 'status': 'error', 'latency': None})

    # 统计结果
    reachable_count = sum(1 for r in results if r['status'] == 'reachable')
    total_latency = sum(float(r['latency']) for r in results if r['latency'])

    # 如果只有一个IP，直接返回单个结果
    if len(hosts) == 1:
        return {
            'name': ep_name,
            'host': endpoint_spec['host'],
            'status': results[0]['status'] if results else 'error',
            'latency': results[0]['latency'] if results else None,
            'details': results
        }
    else:
        avg_latency = f"{total_latency/reachable_count:.1f}" if reachable_count > 0 else None
        unreachable_hosts = [r['host'] for r in results if r['status'] in ('unreachable', 'error')]
        return {
            'name': ep_name,
            'host': endpoint_spec['host'],
            'status': 'reachable' if reachable_count == len(hosts) else ('partial' if reachable_count > 0 else 'unreachable'),
            'latency': avg_latency,
            'reachable_count': reachable_count,
            'total_count': len(hosts),
            'unreachable_hosts': unreachable_hosts,
            'details': results
        }

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

def _check_endpoints(host, endpoints_config, ssh=None, is_local=False):
    """检测端点连通性，每次实时检测，与设备/存储同步更新"""
    endpoints_info = {}
    if not endpoints_config:
        return endpoints_info
    for ep in endpoints_config:
        try:
            ep_result = check_endpoint_connectivity(ep, ssh=ssh, is_local=is_local)
            ep_host = ep['host']
            ep_key = ep.get('name', str(ep_host))
            endpoints_info[ep_key] = ep_result
        except Exception as e:
            print(f"检测端点 {ep.get('name', '')} 失败: {e}")
    return endpoints_info


def get_server_info(server_config):
    """获取单个服务器信息 - 设备/存储/端点独立采集，互不影响"""
    server_name = server_config['name']
    host = server_config['host']
    server_type = server_config.get('type', 'gpu')

    # 检查是否为本地机器
    is_local = server_config.get('local', False) or host == 'localhost' or host == '127.0.0.1'

    # 获取存储监控配置
    storage_config = server_config.get('storage', {})
    mounts = storage_config.get('mounts', None) if storage_config else None
    endpoints_config = storage_config.get('endpoints', []) if storage_config else []

    # 初始化各部分数据
    devices = []
    storage_info = {}
    endpoints_info = {}
    errors = []

    if is_local:
        # ---- 本地监控 ----

        # 1. 采集设备信息
        try:
            if server_type == 'npu':
                command = 'npu-smi info'
            else:
                command = 'nvidia-smi'

            output, error = execute_local_command(command)

            if error:
                errors.append(f'设备检测: {error}')
            else:
                if server_type == 'npu':
                    devices = parse_npu_smi(output)
                else:
                    devices = parse_nvidia_smi(output)
        except Exception as e:
            errors.append(f'设备检测异常: {e}')
            print(f"本地设备检测失败 {server_name}: {e}")

        # 2. 采集存储信息
        try:
            if storage_config:
                storage_info = get_storage_info(is_local=True, mounts=mounts)
        except Exception as e:
            errors.append(f'存储检测异常: {e}')
            print(f"本地存储检测失败 {server_name}: {e}")

        # 3. 采集端点连通性
        try:
            endpoints_info = _check_endpoints(host, endpoints_config, is_local=True)
        except Exception as e:
            errors.append(f'端点检测异常: {e}')
            print(f"本地端点检测失败 {server_name}: {e}")

        status = 'online' if devices else ('error' if errors else 'online')
        return {
            'name': server_name,
            'host': host,
            'status': status,
            'type': server_type,
            'error': '; '.join(errors) if errors and not devices else None,
            'devices': devices,
            'storage': storage_info,
            'endpoints': endpoints_info,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'local': True
        }

    else:
        # ---- 远程监控 ----

        # SSH连接
        auth_config = server_config.get('auth')
        if not auth_config:
            auth_config = {
                'type': 'password',
                'username': server_config.get('username'),
                'password': server_config.get('password')
            }

        bastion_config = server_config.get('bastion')
        ssh = None
        try:
            ssh = ssh_connect(
                host,
                server_config.get('port', 22),
                auth_config,
                bastion_config
            )
        except Exception as e:
            print(f"SSH连接异常 {server_name}: {e}")

        if not ssh:
            return {
                'name': server_name,
                'host': host,
                'status': 'offline',
                'error': 'SSH连接失败',
                'devices': [],
                'storage': {},
                'endpoints': {},
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

        try:
            # 1. 采集设备信息
            try:
                if server_type == 'npu':
                    command = 'npu-smi info'
                else:
                    command = 'nvidia-smi'

                output, error = execute_command(ssh, command)

                if error:
                    errors.append(f'设备检测: {error}')
                else:
                    if server_type == 'npu':
                        devices = parse_npu_smi(output)
                    else:
                        devices = parse_nvidia_smi(output)
            except Exception as e:
                errors.append(f'设备检测异常: {e}')
                print(f"远程设备检测失败 {server_name}: {e}")

            # 2. 采集存储信息
            try:
                if storage_config:
                    storage_info = get_storage_info(ssh=ssh, is_local=False, mounts=mounts)
            except Exception as e:
                errors.append(f'存储检测异常: {e}')
                print(f"远程存储检测失败 {server_name}: {e}")

            # 3. 采集端点连通性
            try:
                endpoints_info = _check_endpoints(host, endpoints_config, ssh=ssh, is_local=False)
            except Exception as e:
                errors.append(f'端点检测异常: {e}')
                print(f"远程端点检测失败 {server_name}: {e}")

            ssh.close()

            status = 'online' if devices else ('error' if errors else 'online')
            return {
                'name': server_name,
                'host': host,
                'status': status,
                'type': server_type,
                'error': '; '.join(errors) if errors and not devices else None,
                'devices': devices,
                'storage': storage_info,
                'endpoints': endpoints_info,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'local': False
            }

        except Exception as e:
            if ssh:
                try:
                    ssh.close()
                except:
                    pass
            return {
                'name': server_name,
                'host': host,
                'status': 'error',
                'error': str(e),
                'devices': devices,
                'storage': storage_info,
                'endpoints': endpoints_info,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'local': False
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
                    # 150秒超时心跳，2次共300秒（5分钟）触发更新
                    message = client_queue.get(timeout=150)
                    yield message
                except queue.Empty:
                    # 每2次心跳（约5分钟）触发一次服务器更新
                    heartbeat_count += 1
                    if heartbeat_count % 2 == 0:
                        print("SSE定时刷新（5分钟间隔）")
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
    """获取mock数据用于前端测试 - 20台服务器"""
    import random

    def make_server(idx, name, dev_count, dev_type, storage_mounts=2, endpoints=1):
        devices = [
            {'id': str(i),
             'name': 'NVIDIA A100' if dev_type == 'gpu' else 'Ascend 910B',
             'temp': f'{random.randint(55,82)}°C',
             'power': f'{random.randint(250,400)}W / 400W' if dev_type == 'gpu' else f'{random.randint(200,300)}W / 300W',
             'memory_usage': f'{random.randint(15000,38000)}MB / 40960MB',
             'utilization': f'{random.randint(40,98)}%'}
            for i in range(dev_count)
        ]

        storage = {}
        mounts = ['/', '/home', '/data', '/mnt/storage'][:storage_mounts]
        for mount in mounts:
            total = random.choice(['500G', '1.0T', '2.0T', '5.0T'])
            used_pct = random.randint(30, 95)
            storage[mount] = {
                'total': total,
                'used': f"{int(float(total[:-1]) * used_pct / 100)}{total[-1]}",
                'free': f"{int(float(total[:-1]) * (100-used_pct) / 100)}{total[-1]}",
                'usage_percent': used_pct,
                'status': 'warning' if used_pct > 85 else 'normal'
            }

        eps = {}
        for epi in range(endpoints):
            ip_count = random.choice([1, 2, 5])
            if ip_count == 1:
                reachable = random.choice([True, True, False])
                single_host = f'192.168.0.{random.randint(1,254)}'
                eps[f'endpoint-{epi+1}'] = {
                    'name': f'存储端点{epi+1}',
                    'host': single_host,
                    'status': 'reachable' if reachable else 'unreachable',
                    'latency': f'{random.uniform(0.2,5.0):.1f}' if reachable else None,
                    'details': [{
                        'host': single_host,
                        'status': 'reachable' if reachable else 'unreachable',
                        'latency': f'{random.uniform(0.2,5.0):.1f}' if reachable else None
                    }]
                }
            else:
                all_reachable = random.choice([True, True, False])
                ips = [f'10.0.0.{100+i}' for i in range(ip_count)]
                details = []
                for ip in ips:
                    ip_ok = all_reachable or random.choice([True, False])
                    details.append({
                        'host': ip,
                        'status': 'reachable' if ip_ok else 'unreachable',
                        'latency': f'{random.uniform(0.2,5.0):.1f}' if ip_ok else None
                    })
                reachable_ips = [d for d in details if d['status'] == 'reachable']
                unreachable_ips = [d['host'] for d in details if d['status'] != 'reachable']
                avg_lat = f'{sum(float(d["latency"]) for d in reachable_ips)/len(reachable_ips):.1f}' if reachable_ips else None
                eps[f'nas-cluster-{epi+1}'] = {
                    'name': f'NAS集群{epi+1}',
                    'host': ips,
                    'status': 'reachable' if len(reachable_ips) == ip_count else ('partial' if reachable_ips else 'unreachable'),
                    'latency': avg_lat,
                    'reachable_count': len(reachable_ips),
                    'total_count': ip_count,
                    'unreachable_hosts': unreachable_ips,
                    'details': details
                }

        return {
            'name': f'{name}{idx}',
            'host': f'192.168.1.{10+idx}',
            'status': 'online',
            'type': dev_type,
            'devices': devices,
            'storage': storage,
            'endpoints': eps,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'local': False
        }

    mock_servers = []

    # 8台8卡GPU服务器
    for i in range(1, 9):
        mock_servers.append(make_server(i, 'GPU训练', 8, 'gpu', 3, 2))

    # 4台4卡NPU服务器
    for i in range(1, 5):
        mock_servers.append(make_server(i, 'NPU推理', 4, 'npu', 2, 2))

    # 6台2卡GPU服务器
    for i in range(1, 7):
        mock_servers.append(make_server(i, 'GPU开发', 2, 'gpu', 2, 1))

    # 2台1卡NPU服务器
    for i in range(1, 3):
        mock_servers.append(make_server(i, 'NPU测试', 1, 'npu', 1, 1))

    return jsonify(mock_servers)

if __name__ == '__main__':
    # 初始化数据
    update_all_servers()

    # 启动后台更新线程
    update_thread = threading.Thread(target=background_update, daemon=True)
    update_thread.start()

    # 启动服务器
    app.run(host='0.0.0.0', port=5000, debug=True)