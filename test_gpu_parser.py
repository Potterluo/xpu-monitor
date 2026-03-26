#!/usr/bin/env python3
"""测试GPU解析功能"""

import re

# 您提供的nvidia-smi输出
test_output = """Thu Mar 26 14:38:10 2026
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 570.195.03             Driver Version: 570.195.03     CUDA Version: 12.8     |
|-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA H100 80GB HBM3          On  |   00000000:18:00.0 Off |                    0 |
| N/A   34C    P0            116W /  700W |   79101MiB /  81559MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
|   1  NVIDIA H100 80GB HBM3          On  |   00000000:38:00.0 Off |                    0 |
| N/A   35C    P0            122W /  700W |   79101MiB /  81559MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
|   2  NVIDIA H100 80GB HBM3          On  |   00000000:48:00.0 Off |                    0 |
| N/A   29C    P0            116W /  700W |   79101MiB /  81559MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
|   3  NVIDIA H100 80GB HBM3          On  |   00000000:59:00.0 Off |                    0 |
| N/A   29C    P0            112W /  700W |   79101MiB /  81559MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
|   4  NVIDIA H100 80GB HBM3          On  |   00000000:98:00.0 Off |                    0 |
| N/A   35C    P0            120W /  700W |   79101MiB /  81559MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
|   5  NVIDIA H100 80GB HBM3          On  |   00000000:B8:00.0 Off |                    0 |
| N/A   36C    P0            121W /  700W |   79101MiB /  81559MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
|   6  NVIDIA H100 80GB HBM3          On  |   00000000:C8:00.0 Off |                    0 |
| N/A   29C    P0            120W /  700W |   79101MiB /  81559MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
|   7  NVIDIA H100 80GB HBM3          On  |   00000000:D9:00.0 Off |                    0 |
| N/A   30C    P0            116W /  700W |   79101MiB /  81559MiB |      0%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A         2753460      C   VLLM::Worker_TP0                      79028MiB |
|    1   N/A  N/A         2753461      C   VLLM::Worker_TP1                      79028MiB |
|    2   N/A  N/A         2753462      C   VLLM::Worker_TP2                      79028MiB |
|    3   N/A  N/A         2753463      C   VLLM::Worker_TP3                      79028MiB |
|    4   N/A  N/A         2753464      C   VLLM::Worker_TP4                      79028MiB |
|    5   N/A  N/A         2753465      C   VLLM::Worker_TP5                      79028MiB |
|    6   N/A  N/A         2753466      C   VLLM::Worker_TP6                      79028MiB |
|    7   N/A  N/A         2753467      C   VLLM::Worker_TP7                      79028MiB |
+-----------------------------------------------------------------------------------------+"""

def parse_nvidia_smi_fixed(output):
    """修复后的nvidia-smi解析函数"""
    if not output:
        return []

    devices = []

    print("=== nvidia-smi 原始输出 ===")
    print(output)
    print("=== 结束 ===\n")

    lines = [line for line in output.split('\n')]

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # 跳过空行和没有管道符的行
        if not line or '|' not in line:
            i += 1
            continue

        # 排除表头和分隔符
        if '----' in line or 'NVIDIA-SMI' in line or '+=====' in line or '+---' in line or 'GPU  Name' in line:
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

                # 提取GPU ID和名称
                # 匹配类似: "0  NVIDIA H100 80GB HBM3          On"
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
                power_match = re.search(r'(N/A|[\d\.]+)\s*/\s*([\d\.]+)W', perf_part)
                if power_match:
                    usage = power_match.group(1)
                    cap = power_match.group(2)
                    # 统一格式：N/A / 700W 或 116W / 700W
                    power_str = f"{usage}W / {cap}W" if usage != 'N/A' else f"N/A / {cap}W"
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

# 测试解析
if __name__ == "__main__":
    devices = parse_nvidia_smi_fixed(test_output)

    print("\n=== 解析结果 ===")
    for idx, device in enumerate(devices, 1):
        print(f"GPU {idx}: {device}")
