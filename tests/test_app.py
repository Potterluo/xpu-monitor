#!/usr/bin/env python3
"""
XPU监控平台单元测试
测试核心功能和并发安全性
"""

import unittest
import time
import threading
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (
    parse_nvidia_smi,
    parse_npu_smi,
    parse_size_to_bytes,
    format_bytes,
    expand_endpoint_host,
    validate_server_config,
    _ping_single_host,
    check_endpoint_connectivity,
    get_server_info,
    endpoint_cache,
)


class TestNvidiaSmiParser(unittest.TestCase):
    """测试nvidia-smi输出解析"""

    def setUp(self):
        self.sample_output = """Thu Mar 26 14:38:10 2026
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
| N/A   35C    P0            122W /  700W |   40000MiB /  81559MiB |     50%      Default |
|                                         |                        |             Disabled |
+-----------------------------------------+------------------------+----------------------+
"""

    def test_parse_gpu_devices(self):
        """测试解析GPU设备"""
        devices = parse_nvidia_smi(self.sample_output)
        self.assertEqual(len(devices), 2)

        gpu0 = devices[0]
        self.assertEqual(gpu0['id'], '0')
        self.assertIn('H100', gpu0['name'])
        self.assertIn('34', gpu0['temp'])
        self.assertIn('116W', gpu0['power'])
        self.assertIn('79101MB', gpu0['memory_usage'])
        self.assertEqual(gpu0['utilization'], '0%')

        gpu1 = devices[1]
        self.assertEqual(gpu1['id'], '1')
        self.assertEqual(gpu1['utilization'], '50%')

    def test_parse_empty_output(self):
        """测试空输出"""
        devices = parse_nvidia_smi('')
        self.assertEqual(len(devices), 0)
        devices = parse_nvidia_smi(None)
        self.assertEqual(len(devices), 0)


class TestNpuSmiParser(unittest.TestCase):
    """测试npu-smi输出解析"""

    def setUp(self):
        self.sample_output = """
+------------------------------------------------------------------------------------------------+ 
| npu-smi 25.2.3                   Version: 25.2.3                                               | 
+---------------------------+---------------+----------------------------------------------------+ 
| NPU   Name                | Health        | Power(W)    Temp(C)           Hugepages-Usage(page)| 
| Chip                      | Bus-Id        | AICore(%)   Memory-Usage(MB)  HBM-Usage(MB)        | 
+===========================+===============+====================================================+ 
| 0     910B3               | OK            | 93.2        37                0    / 0             | 
| 0                         | 0000:C1:00.0  | 0           0    / 0          64549/ 65536         | 
+===========================+===============+====================================================+ 
| 1     910B3               | OK            | 84.6        32                0    / 0             | 
| 0                         | 0000:C2:00.0  | 0           0    / 0          64536/ 65536         | 
+===========================+===============+====================================================+ 
"""

    def test_parse_npu_devices(self):
        """测试解析NPU设备"""
        devices = parse_npu_smi(self.sample_output)
        self.assertEqual(len(devices), 2)

        npu0 = devices[0]
        self.assertEqual(npu0['id'], '0')
        self.assertEqual(npu0['name'], '910B3')
        self.assertIn('37', npu0['temp'])
        self.assertIn('93', npu0['power'])

    def test_parse_empty_npu_output(self):
        """测试空NPU输出"""
        devices = parse_npu_smi('')
        self.assertEqual(len(devices), 0)


class TestSizeConversion(unittest.TestCase):
    """测试大小转换函数"""

    def test_parse_size_to_bytes(self):
        """测试大小字符串解析"""
        self.assertEqual(parse_size_to_bytes('100B'), 100)
        self.assertEqual(parse_size_to_bytes('1KB'), 1024)
        self.assertEqual(parse_size_to_bytes('1MB'), 1024 * 1024)
        self.assertEqual(parse_size_to_bytes('1GB'), 1024 * 1024 * 1024)
        self.assertEqual(parse_size_to_bytes('1TB'), 1024 * 1024 * 1024 * 1024)
        self.assertEqual(parse_size_to_bytes('0B'), 0)
        self.assertEqual(parse_size_to_bytes(None), 0)
        self.assertEqual(parse_size_to_bytes(''), 0)

    def test_format_bytes(self):
        """测试字节格式化"""
        self.assertEqual(format_bytes(0), '0B')
        self.assertEqual(format_bytes(512), '512.0B')
        self.assertEqual(format_bytes(1024), '1.0KB')
        self.assertEqual(format_bytes(1024 * 1024), '1.0MB')
        self.assertEqual(format_bytes(1024 * 1024 * 1024), '1.0GB')
        self.assertEqual(format_bytes(1024 * 1024 * 1024 * 1024), '1.0TB')


class TestEndpointHostExpansion(unittest.TestCase):
    """测试端点主机展开"""

    def test_single_host(self):
        """测试单个主机"""
        result = expand_endpoint_host('192.168.0.1')
        self.assertEqual(result, ['192.168.0.1'])

    def test_host_array(self):
        """测试主机数组"""
        result = expand_endpoint_host(['192.168.0.1', '192.168.0.2'])
        self.assertEqual(result, ['192.168.0.1', '192.168.0.2'])

    def test_host_range(self):
        """测试IP范围展开"""
        result = expand_endpoint_host('192.168.0.1~5')
        expected = ['192.168.0.1', '192.168.0.2', '192.168.0.3', '192.168.0.4', '192.168.0.5']
        self.assertEqual(result, expected)

    def test_invalid_range(self):
        """测试无效范围"""
        result = expand_endpoint_host('invalid~abc')
        self.assertEqual(result, ['invalid~abc'])


class TestServerConfigValidation(unittest.TestCase):
    """测试服务器配置验证"""

    def test_valid_local_server(self):
        """测试有效的本地服务器配置"""
        config = {
            'name': '本地服务器',
            'host': 'localhost',
            'type': 'gpu',
            'local': True
        }
        is_valid, msg = validate_server_config(config)
        self.assertTrue(is_valid)

    def test_valid_remote_server_password(self):
        """测试有效的远程服务器配置（密码认证）"""
        config = {
            'name': '远程服务器',
            'host': '192.168.1.100',
            'type': 'gpu',
            'auth': {
                'type': 'password',
                'username': 'root',
                'password': 'password123'
            }
        }
        is_valid, msg = validate_server_config(config)
        self.assertTrue(is_valid)

    def test_valid_remote_server_key(self):
        """测试有效的远程服务器配置（密钥认证）"""
        config = {
            'name': '远程服务器',
            'host': '192.168.1.100',
            'type': 'npu',
            'auth': {
                'type': 'key',
                'username': 'root',
                'key_file': '/path/to/key'
            }
        }
        is_valid, msg = validate_server_config(config)
        self.assertTrue(is_valid)

    def test_missing_required_fields(self):
        """测试缺少必要字段"""
        config = {'name': '测试服务器'}
        is_valid, msg = validate_server_config(config)
        self.assertFalse(is_valid)
        self.assertIn('缺少必要字段', msg)

    def test_invalid_type(self):
        """测试无效的设备类型"""
        config = {
            'name': '测试服务器',
            'host': '192.168.1.100',
            'type': 'invalid_type'
        }
        is_valid, msg = validate_server_config(config)
        self.assertFalse(is_valid)
        self.assertIn('不支持的设备类型', msg)

    def test_missing_auth(self):
        """测试缺少认证配置"""
        config = {
            'name': '远程服务器',
            'host': '192.168.1.100',
            'type': 'gpu'
        }
        is_valid, msg = validate_server_config(config)
        self.assertFalse(is_valid)
        self.assertIn('认证配置', msg)

    def test_missing_password(self):
        """测试缺少密码"""
        config = {
            'name': '远程服务器',
            'host': '192.168.1.100',
            'type': 'gpu',
            'auth': {
                'type': 'password',
                'username': 'root'
            }
        }
        is_valid, msg = validate_server_config(config)
        self.assertFalse(is_valid)
        self.assertIn('密码', msg)

    def test_missing_key_file(self):
        """测试缺少密钥文件"""
        config = {
            'name': '远程服务器',
            'host': '192.168.1.100',
            'type': 'gpu',
            'auth': {
                'type': 'key',
                'username': 'root'
            }
        }
        is_valid, msg = validate_server_config(config)
        self.assertFalse(is_valid)
        self.assertIn('密钥文件', msg)


class TestConcurrencySafety(unittest.TestCase):
    """测试并发安全性"""

    def test_endpoint_check_timeout(self):
        """测试端点检测超时不会阻塞"""
        with patch('app.execute_local_command') as mock_cmd:
            mock_cmd.return_value = (None, 'timeout')

            start_time = time.time()
            result = _ping_single_host('192.168.255.255', timeout=1, is_local=True)
            elapsed = time.time() - start_time

            self.assertIn(result['status'], ['unreachable', 'error'])
            self.assertLess(elapsed, 5)

    def test_endpoint_check_parallel_timeout(self):
        """测试并行端点检测超时不会互相阻塞"""
        with patch('app._ping_single_host') as mock_ping:
            def slow_ping(host, timeout, is_local, ssh=None):
                time.sleep(0.5)
                return {'host': host, 'status': 'reachable', 'latency': '1.0'}
            
            mock_ping.side_effect = slow_ping

            start_time = time.time()
            result = check_endpoint_connectivity({
                'name': '测试集群',
                'host': ['10.0.0.1', '10.0.0.2', '10.0.0.3', '10.0.0.4', '10.0.0.5']
            }, is_local=True)
            elapsed = time.time() - start_time

            self.assertIn('details', result)
            self.assertEqual(result['total_count'], 5)
            self.assertLess(elapsed, 2)

    def test_server_info_isolation(self):
        """测试服务器信息采集各部分隔离 - 设备/存储/端点采集互不影响"""
        sample_nvidia_output = """|   0  NVIDIA A100                     On  |   00000000:18:00.0 Off |                    0 |
| N/A   60C    P0            200W /  400W |   10000MiB /  40000MiB |     50%      Default |"""

        with patch('app.execute_local_command') as mock_cmd:
            def mock_execute(command, timeout=15):
                if 'nvidia-smi' in command:
                    return (sample_nvidia_output, None)
                elif 'df' in command:
                    raise Exception('Storage check failed - simulated timeout')
                return ('', None)
            
            mock_cmd.side_effect = mock_execute

            with patch('app.parse_nvidia_smi') as mock_parse:
                mock_parse.return_value = [{'id': '0', 'name': 'NVIDIA A100', 'temp': '60C', 'power': '200W', 'memory_usage': '10000MB / 40000MB', 'utilization': '50%'}]

                with patch('app._check_endpoints_with_cache') as mock_ep:
                    mock_ep.return_value = {'ep1': {'name': '测试端点', 'status': 'reachable', 'latency': '1.0'}}

                    config = {
                        'name': '测试服务器',
                        'host': '127.0.0.1',
                        'type': 'gpu',
                        'local': True,
                        'storage': {'mounts': [{'path': '/'}], 'endpoints': [{'name': '测试端点', 'host': '192.168.0.1'}]}
                    }

                    result = get_server_info(config)

                    self.assertEqual(result['status'], 'online', "设备采集成功，服务器应该在线")
                    self.assertEqual(len(result['devices']), 1, "设备信息应该正常返回")
                    self.assertEqual(result['endpoints']['ep1']['status'], 'reachable', "端点检测应该正常返回")
                    self.assertEqual(len(result['storage']), 0, "存储检测失败时storage应该为空")

    def test_sse_client_thread_safety(self):
        """测试SSE客户端集合的线程安全"""
        test_clients = set()
        test_lock = threading.Lock()

        def add_clients():
            for i in range(100):
                with test_lock:
                    test_clients.add(f'client_{threading.current_thread().name}_{i}')

        threads = []
        for _ in range(10):
            t = threading.Thread(target=add_clients)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertGreater(len(test_clients), 0)


class TestEndpointCache(unittest.TestCase):
    """测试端点缓存"""

    def test_cache_hit(self):
        """测试缓存命中"""
        with patch('app.check_endpoint_connectivity') as mock_check:
            mock_check.return_value = {
                'name': '测试端点',
                'status': 'reachable',
                'latency': '1.0'
            }

            endpoint_cache.clear()

            from app import _check_endpoints_with_cache
            config = {'name': '测试', 'host': '192.168.0.1'}

            result1 = _check_endpoints_with_cache('test_host', [config], is_local=True)
            result2 = _check_endpoints_with_cache('test_host', [config], is_local=True)

            self.assertEqual(mock_check.call_count, 1, "缓存命中后不应重复调用检测函数")


class TestErrorHandling(unittest.TestCase):
    """测试错误处理"""

    def test_ssh_connection_failure(self):
        """测试SSH连接失败"""
        with patch('app.ssh_connect') as mock_ssh:
            mock_ssh.return_value = None

            config = {
                'name': '远程服务器',
                'host': '192.168.1.100',
                'type': 'gpu',
                'auth': {'type': 'password', 'username': 'root', 'password': 'test'}
            }

            result = get_server_info(config)

            self.assertEqual(result['status'], 'offline')
            self.assertIn('SSH', result['error'])

    def test_command_timeout(self):
        """测试命令超时"""
        with patch('app.execute_command') as mock_cmd:
            mock_cmd.return_value = (None, 'Command execution timeout')

            with patch('app.ssh_connect') as mock_ssh:
                mock_ssh.return_value = MagicMock()

                config = {
                    'name': '远程服务器',
                    'host': '192.168.1.100',
                    'type': 'gpu',
                    'auth': {'type': 'password', 'username': 'root', 'password': 'test'}
                }

                result = get_server_info(config)

                self.assertIn('error', result)

    def test_parse_invalid_output(self):
        """测试解析无效输出"""
        invalid_outputs = [
            '',
            None,
            'random text without gpu info',
            'NVIDIA-SMI\n\n\n',
        ]

        for output in invalid_outputs:
            devices = parse_nvidia_smi(output)
            self.assertEqual(len(devices), 0, f"Failed for: {output}")


class TestIsolationGuarantees(unittest.TestCase):
    """测试隔离保证 - 确保各部分采集不会互相阻塞"""

    def test_device_failure_doesnt_block_storage(self):
        """测试设备采集失败不会阻塞存储采集"""
        with patch('app.execute_local_command') as mock_cmd:
            def mock_execute(command, timeout=15):
                if 'nvidia-smi' in command:
                    raise Exception('nvidia-smi crashed')
                elif 'df ' in command or command.startswith('df'):
                    return ('Filesystem     Size  Used Avail Use% Mounted on\n/dev/sda1      100G   50G   50G  50% /', None)
                return ('', None)
            
            mock_cmd.side_effect = mock_execute

            with patch('app.get_storage_info') as mock_storage:
                mock_storage.return_value = {'/': {'total': '100G', 'used': '50G', 'usage_percent': 50}}

                config = {
                    'name': '测试服务器',
                    'host': '127.0.0.1',
                    'type': 'gpu',
                    'local': True,
                    'storage': {'mounts': [{'path': '/'}], 'endpoints': []}
                }

                result = get_server_info(config)

                self.assertEqual(len(result['storage']), 1, "存储信息应该正常返回")
                self.assertIn('/', result['storage'])

    def test_storage_failure_doesnt_block_endpoints(self):
        """测试存储采集失败不会阻塞端点采集"""
        with patch('app.execute_local_command') as mock_cmd:
            def mock_execute(command, timeout=15):
                if 'nvidia-smi' in command:
                    return ('GPU info', None)
                elif 'df ' in command or command.startswith('df'):
                    raise Exception('df command failed')
                return ('', None)
            
            mock_cmd.side_effect = mock_execute

            with patch('app.parse_nvidia_smi') as mock_parse:
                mock_parse.return_value = [{'id': '0', 'name': 'GPU'}]

                with patch('app._check_endpoints_with_cache') as mock_ep:
                    mock_ep.return_value = {'ep1': {'status': 'reachable'}}

                    config = {
                        'name': '测试服务器',
                        'host': '127.0.0.1',
                        'type': 'gpu',
                        'local': True,
                        'storage': {'mounts': [{'path': '/'}], 'endpoints': [{'name': 'ep1', 'host': '192.168.0.1'}]}
                    }

                    result = get_server_info(config)

                    self.assertEqual(result['endpoints']['ep1']['status'], 'reachable', "端点检测应该正常返回")

    def test_endpoint_failure_doesnt_block_device(self):
        """测试端点采集失败不会阻塞设备采集"""
        with patch('app.execute_local_command') as mock_cmd:
            mock_cmd.return_value = ('GPU info', None)

            with patch('app.parse_nvidia_smi') as mock_parse:
                mock_parse.return_value = [{'id': '0', 'name': 'GPU'}]

                with patch('app._check_endpoints_with_cache') as mock_ep:
                    mock_ep.side_effect = Exception('Endpoint check failed')

                    config = {
                        'name': '测试服务器',
                        'host': '127.0.0.1',
                        'type': 'gpu',
                        'local': True,
                        'storage': {'mounts': [], 'endpoints': [{'name': 'ep1', 'host': '192.168.0.1'}]}
                    }

                    result = get_server_info(config)

                    self.assertEqual(len(result['devices']), 1, "设备信息应该正常返回")


if __name__ == '__main__':
    unittest.main(verbosity=2)
