# 配置系统

Healthy Agent 使用 TOML 格式配置文件，支持环境变量覆盖。

## 配置文件

在项目根目录创建 `healthy_agent.toml`：

```toml
[kernel]
max_workers = 4
queue_size = 100
scheduling_policy = "priority"

[executor]
max_retries = 3
timeout = 30
retry_delay = 1

[logging]
level = "INFO"
format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

[observability]
enabled = true
metrics_port = 9090
```

## 配置段说明

### kernel

- `max_workers`: 最大工作线程数
- `queue_size`: 任务队列大小
- `scheduling_policy`: 调度策略（priority/fifo）

### executor

- `max_retries`: 最大重试次数
- `timeout`: 任务超时时间（秒）
- `retry_delay`: 重试间隔（秒）

### logging

- `level`: 日志级别（DEBUG/INFO/WARNING/ERROR）
- `format`: 日志格式字符串

### observability

- `enabled`: 是否启用监控
- `metrics_port`: 指标暴露端口

## 环境变量覆盖

使用 `HEALTHY_AGENT_` 前缀的环境变量覆盖配置：

```bash
export HEALTHY_AGENT_KERNEL_MAX_WORKERS=8
export HEALTHY_AGENT_LOGGING_LEVEL=DEBUG
```

## 优先级

配置加载优先级（从高到低）：

1. 环境变量
2. 命令行参数
3. 配置文件
4. 默认值

## 下一步

查看 [内核概念](../concepts/kernel.md) 了解调度机制详情。
