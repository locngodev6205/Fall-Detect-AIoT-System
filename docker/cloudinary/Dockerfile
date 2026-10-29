FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY docker/cloudinary/check.py /opt/annha/check.py
RUN useradd --no-create-home --uid 10001 cloudcheck
USER cloudcheck
ENTRYPOINT ["python", "/opt/annha/check.py"]
CMD ["--validate-only"]
