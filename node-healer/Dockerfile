FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY node_healer ./node_healer
RUN useradd --uid 10001 --no-create-home healer
USER 10001
EXPOSE 9102
ENTRYPOINT ["python", "-m", "node_healer.main"]
