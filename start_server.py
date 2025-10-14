#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NPU/GPU 监控平台测试启动脚本
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    """主函数"""
    print("=== NPU/GPU 监控平台测试启动 ===")
    print()

    try:
        # 导入并启动应用
        from app import app
        print("应用导入成功")
        
        # 在开发模式下启动
        print("启动Web服务器...")
        print("访问地址: http://localhost:5000")
        print("按 Ctrl+C 停止服务")
        print()
        
        app.run(host='127.0.0.1', port=5000, debug=True)
        
    except KeyboardInterrupt:
        print("\n服务已停止")
    except Exception as e:
        print(f"启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()