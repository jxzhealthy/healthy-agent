# Healthy Agent

**A CPU-scheduling-inspired runtime kernel for LLM agent workloads**

Healthy Agent 是一个创新的智能体运行时框架，借鉴操作系统 CPU 调度理念，为 LLM 智能体工作负载提供高效的资源管理和任务调度能力。

## 核心特性

- **内核级调度**: 基于优先级的任务调度系统，优化资源利用
- **弹性执行器**: 支持重试、超时控制和熔断机制
- **技能系统**: 模块化技能管理，支持动态加载
- **记忆系统**: 短期和长期记忆支持，上下文管理
- **可观测性**: 内置监控、日志和指标收集
- **Web API**: RESTful API 和 WebSocket 支持

## 快速安装

```bash
pip install healthy-agent
```

或使用 uv（推荐）：

```bash
uv add healthy-agent
```

## 开始使用

查看 [快速开始](getting-started/quickstart.md) 了解如何在几分钟内运行你的第一个智能体。

## 文档导航

- **[入门指南](getting-started/installation.md)**: 安装和配置
- **[核心概念](concepts/architecture.md)**: 理解架构设计
- **[使用指南](guides/skills.md)**: 技能和工具开发
- **[API 参考](api/rest.md)**: REST API 文档
