# 视频去重工具 - CPU 版镜像
# 构建: docker build -t videodedup .
# 运行: docker run --rm -v <数据目录>:/data videodedup --help

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# FFmpeg（裁切必需）+ OpenCV headless 运行所需的少量系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用 Docker 层缓存）
COPY requirements-core.txt ./
RUN pip install -r requirements-core.txt

# 拷贝源码
COPY app ./app
COPY cli.py ./

# 数据挂载点（reference / target / output / cache）
RUN mkdir -p /data/reference /data/target /data/output /cache

ENTRYPOINT ["python", "cli.py"]
CMD ["--help"]
