# TwinSight 단일 서버 이미지: React 대시보드를 빌드해 FastAPI가 /dashboard/로 함께 제공한다.
# Render(Docker)와 로컬 docker 모두 같은 이미지를 쓴다.

# 1단계: 프론트 빌드
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# VITE_ 값은 빌드 시점에 번들에 들어간다. 비밀값(DB, 팀 키)은 넣지 않는다.
ARG VITE_API_BASE=/api
ARG VITE_DEMO_TWIN=0
ARG VITE_CARTO_KEY=
ENV VITE_API_BASE=$VITE_API_BASE VITE_DEMO_TWIN=$VITE_DEMO_TWIN VITE_CARTO_KEY=$VITE_CARTO_KEY
RUN npm run build

# 2단계: 백엔드 실행
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
RUN useradd --create-home --uid 10001 twinsight
COPY --chown=twinsight:twinsight backend/__init__.py backend/__init__.py
COPY --chown=twinsight:twinsight backend/app backend/app
# main.py가 영상 검증(lab) 모듈을 불러오며 detection.warnings(표준 라이브러리만 사용)가 필요하다.
# YOLO 모델·ultralytics는 넣지 않으므로 영상 검증 추론은 이 서버에서 동작하지 않는다.
COPY --chown=twinsight:twinsight detection/__init__.py detection/warnings.py detection/
COPY --chown=twinsight:twinsight --from=frontend /src/frontend/dist frontend/dist
RUN mkdir -p backend/data && chown twinsight:twinsight backend/data
USER twinsight
# Render는 PORT를 넘겨준다. 로컬에서는 8000.
EXPOSE 8000
CMD ["sh", "-c", "exec python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
