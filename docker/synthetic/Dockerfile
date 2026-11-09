# Test image for synthetic stage 2a. It needs network ONLY at build time (pip). Runs use
# --network none (see synthetic/run_tests.py). The repos themselves are mounted, not installed:
# only pytest and the repos' runtime dependencies are baked in.
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==8.4.2 click mdurl rich shellingham typing-extensions annotated-doc \
    && useradd -m -u 1000 runner
USER runner
WORKDIR /scratch
