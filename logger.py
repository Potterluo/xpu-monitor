#!/usr/bin/env python3
"""
日志配置模块
提供统一的日志管理
"""

import logging
import sys
from datetime import datetime

LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

_loggers = {}
_log_level = logging.INFO


def setup_logging(level='INFO', log_file=None):
    """
    配置全局日志
    
    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 可选的日志文件路径
    """
    global _log_level
    
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    
    _log_level = level_map.get(level.upper(), logging.INFO)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(_log_level)
    
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(_log_level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root_logger.addHandler(console_handler)
    
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(_log_level)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        root_logger.addHandler(file_handler)


def get_logger(name):
    """
    获取指定名称的 logger
    
    Args:
        name: logger 名称，通常使用 __name__
    
    Returns:
        logging.Logger 实例
    """
    if name not in _loggers:
        logger = logging.getLogger(name)
        logger.setLevel(_log_level)
        _loggers[name] = logger
    return _loggers[name]


class LogTimer:
    """日志计时器，用于记录操作耗时"""
    
    def __init__(self, logger, operation, level='INFO'):
        self.logger = logger
        self.operation = operation
        self.level = level
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (datetime.now() - self.start_time).total_seconds()
        if exc_type is None:
            msg = f"{self.operation} 完成 (耗时: {elapsed:.2f}s)"
        else:
            msg = f"{self.operation} 失败: {exc_val} (耗时: {elapsed:.2f}s)"
        
        log_func = getattr(self.logger, self.level.lower())
        log_func(msg)
        return False


def log_call(func):
    """函数调用日志装饰器"""
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        func_name = func.__name__
        logger.debug(f"调用 {func_name}()")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"{func_name}() 返回成功")
            return result
        except Exception as e:
            logger.error(f"{func_name}() 执行失败: {e}")
            raise
    return wrapper
