FROM python:3.12-slim
WORKDIR /experiment
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY demo.py .
ENTRYPOINT ["python", "demo.py"]
