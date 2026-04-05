# LightSmith Backend Dockerfile
# 多阶段构建，最终镜像 < 200MB

# ============================
# Stage 1: Builder
# ============================
# 基于轻量级的 Python 3.11 官方镜像，命名为 builder，用于后续编译和安装依赖。
# 这条语句从 python:3.11-slim 基础镜像启动一个新的构建阶段，并将该阶段命名为 builder。
# 它并不是“引入”一个镜像到当前上下文，而是基于这个镜像创建一个临时容器层，用于后续的编译、安装等操作。
FROM python:3.11-slim AS builder

# 设置工作目录
WORKDIR /app

# 安装构建依赖（PostgreSQL 客户端库）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# 复制依赖清单
COPY pyproject.toml ./

# 安装 Python 依赖到虚拟环境
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir .

# ============================
# Stage 2: Runtime
# ============================
FROM python:3.11-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# 安装运行时依赖（仅 PostgreSQL 客户端库）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libpq5 && \
    rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN useradd -m -u 1000 lightsmith && \
    mkdir -p /app && \
    chown -R lightsmith:lightsmith /app

# 切换到应用目录
WORKDIR /app

# 从 builder 复制虚拟环境
COPY --from=builder /opt/venv /opt/venv

# 复制应用代码（排除不必要的文件）
COPY --chown=lightsmith:lightsmith app ./app
COPY --chown=lightsmith:lightsmith alembic ./alembic
COPY --chown=lightsmith:lightsmith alembic.ini ./

# 切换到非 root 用户
USER lightsmith

# 暴露端口
EXPOSE 8000

# 健康检查（使用 FastAPI 健康端点）
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"

# 启动命令（使用 uvicorn）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
