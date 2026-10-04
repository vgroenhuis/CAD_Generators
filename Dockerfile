FROM python:3.12-slim

# build123d's OCCT bindings dynamically link against these even for
# headless geometry work (no actual rendering/display involved).
RUN apt-get update && apt-get install -y --no-install-recommends \
	libgl1 libglu1-mesa libxrender1 libxext6 \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[web]"

EXPOSE 8000
CMD ["uvicorn", "web_app.server:app", "--host", "0.0.0.0", "--port", "8000"]
