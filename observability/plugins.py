"""
扩展点示例：在 Django 启动时注册自定义检测器。

# apps.py 或 AppConfig.ready()
from observability.insights import register_detector
from observability.plugins import my_detector

def ready(self):
    register_detector(my_detector)
"""

# 占位；实现见 insights.register_detector
