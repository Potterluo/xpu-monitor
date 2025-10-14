#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NPU/GPU 监控平台启动脚本
"""

import sys
import os

def check_python_version():
    """检查Python版本"""
    if sys.version_info < (3, 7):
        print("错误: 需要Python 3.7或更高版本")
        print(f"当前版本: {sys.version}")
        sys.exit(1)

def check_dependencies():
    """检查依赖包"""
    required_packages = [
        'flask', 'paramiko', 'requests'
    ]

    missing_packages = []

    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing_packages.append(package)

    if missing_packages:
        print("错误: 缺少以下依赖包:")
        for package in missing_packages:
            print(f"  - {package}")
        print("\n请运行以下命令安装依赖:")
        print("pip install -r requirements.txt")
        sys.exit(1)

def check_config():
    """检查配置文件"""
    config_file = 'config/servers.json'
    if not os.path.exists(config_file):
        print(f"警告: 配置文件 {config_file} 不存在")
        print("请创建配置文件并添加服务器信息")
        return False

    try:
        import json
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        if 'servers' not in config:
            print("错误: 配置文件格式错误，缺少'servers'字段")
            return False

        if not config['servers']:
            print("警告: 配置文件中没有服务器信息")

    except json.JSONDecodeError as e:
        print(f"错误: 配置文件JSON格式错误: {e}")
        return False
    except Exception as e:
        print(f"错误: 读取配置文件失败: {e}")
        return False

    return True

def main():
    """主函数"""
    print("=== XPU 监控平台 ===")
    print()

    # 检查Python版本
    print("检查Python版本...")
    check_python_version()
    print("✓ Python版本检查通过")

    # 检查依赖包
    print("检查依赖包...")
    check_dependencies()
    print("✓ 依赖包检查通过")

    # 检查配置文件
    print("检查配置文件...")
    config_ok = check_config()
    if config_ok:
        print("✓ 配置文件检查通过")
    else:
        print("⚠ 配置文件存在问题，但继续启动")

    print()
    print("启动Web服务器...")
    print("访问地址: http://localhost:5090")
    print("按 Ctrl+C 停止服务")
    print()

    try:
        # 导入并启动应用
        from app import app
        app.run(host='0.0.0.0', port=5090, debug=False)
    except KeyboardInterrupt:
        print("\n服务已停止")
    except Exception as e:
        print(f"启动失败: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()