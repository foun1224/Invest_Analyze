FROM python:3.11-slim
ENV TZ=Asia/Taipei PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN pip install --no-cache-dir -e .
# 預設進入點:傳子命令即可,如 docker run img run-daily --date 2026-06-30
ENTRYPOINT ["python", "-m", "chipflow.cli"]
CMD ["--help"]
