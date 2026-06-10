# 快速开始

通过三个简单示例，快速了解 Healthy Agent 的核心功能。

## 示例 1: 使用内核调度

```python
from healthy_agent import Kernel, Task

# 创建内核实例
kernel = Kernel()

# 定义任务
def hello_task():
    return "Hello from Healthy Agent!"

# 提交任务并执行
task = Task(name="hello", func=hello_task, priority=1)
result = kernel.submit(task)
print(result.output)
```

## 示例 2: 使用执行器

```python
from healthy_agent import Executor

# 创建执行器，支持重试和超时
executor = Executor(
    max_retries=3,
    timeout=30
)

# 执行函数
result = executor.execute(lambda: "Task completed")
print(result)
```

## 示例 3: 启动 Web 服务器

```python
from healthy_agent.api import app

# 启动 REST API 服务
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

访问 `http://localhost:8000/docs` 查看 API 文档。

## 下一步

- 学习 [配置系统](configuration.md) 自定义行为
- 探索 [核心概念](../concepts/architecture.md) 理解架构
- 查看 [技能指南](../guides/skills.md) 开发自定义技能
