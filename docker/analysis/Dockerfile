# Analysis image: Python plus numpy, nothing else. Built once with network; always run with
# --network none and the data mounted read-only (see `make score-local`).
FROM python:3.12-slim
RUN pip install --no-cache-dir numpy==2.2.6 && useradd -m -u 1000 runner
USER runner
WORKDIR /job
