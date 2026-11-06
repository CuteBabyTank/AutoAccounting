FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml constraints.txt ./
RUN pip install --no-cache-dir -c constraints.txt ".[dev]"

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
