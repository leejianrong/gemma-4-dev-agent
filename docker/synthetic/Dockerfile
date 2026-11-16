# Test image for the synthetic task set. It needs network ONLY at build time (pip). Runs use
# --network none (see synthetic/run_tests.py). The repos themselves are mounted, not installed:
# the image holds pytest and the competition image's test stack (requirements.txt, mirrors
# pod/test_env.sh), so a repo is admitted by what that stack can import.
FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && useradd -m -u 1000 runner
USER runner
WORKDIR /scratch
