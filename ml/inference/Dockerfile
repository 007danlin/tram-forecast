FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

LABEL org.opencontainers.image.base.name="python:3.12.14-slim-bookworm" \
      org.opencontainers.image.base.digest="sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
    NUMEXPR_NUM_THREADS=2 LOKY_MAX_CPU_COUNT=2
WORKDIR /app
COPY ml/requirements-inference.txt /app/ml/requirements-inference.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: -r ml/requirements-inference.txt \
    && python -m pip check
# The existing CLI imports these modules eagerly. No experiments, data, weights,
# forecasts, backend or frontend are copied. Training is never invoked at build.
COPY ml/__init__.py ml/__main__.py ml/cli.py ml/artifact.py ml/baselines.py \
     ml/data.py ml/evaluation.py ml/experiment_config.py ml/factors.py \
     ml/metrics.py ml/model.py ml/qa.py ml/settings.py ml/weather.py /app/ml/
COPY ml/inference/measure.py /app/ml/inference/measure.py
ENTRYPOINT ["python", "-m", "ml"]
CMD ["--help"]
