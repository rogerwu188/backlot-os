FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk nodejs npm \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/backlotos
COPY components /opt/backlotos/components
RUN python -m pip install --no-cache-dir \
    /opt/backlotos/components/agentcut \
    /opt/backlotos/components/review-agent \
    /opt/backlotos/components/story-agent \
    /opt/backlotos/components/producer-supervisor-agent \
    /opt/backlotos/components/launcher
ENV AGENTCUT_SUBTITLE_FONT=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
CMD ["backlotos", "health"]
