# 安装指南

Healthy Agent 支持多种安装方式，选择最适合你的方式。

## 使用 pip 安装

最通用的安装方式：

```bash
pip install healthy-agent
```

## 使用 uv 安装（推荐）

uv 是更快的 Python 包管理器：

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建项目并添加依赖
uv init my-agent-project
cd my-agent-project
uv add healthy-agent
```

## 从源码安装

如需最新开发版本或贡献代码：

```bash
git clone https://github.com/your-org/healthy-agent.git
cd healthy-agent
pip install -e .
```

## 验证安装

```python
import healthy_agent
print(healthy_agent.__version__)
```

## 系统要求

- Python 3.9+
- 操作系统：Linux, macOS, Windows
- 内存：建议 2GB+

## 下一步

安装完成后，查看 [快速开始](quickstart.md) 了解如何使用 Healthy Agent。
