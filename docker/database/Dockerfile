FROM postgres:16.14-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && test -r /etc/ssl/certs/ca-certificates.crt
COPY backend/database/postgresql /opt/annha/schema
COPY docker/database/db-tool.sh /usr/local/bin/annha-db
RUN chmod 0755 /usr/local/bin/annha-db
ENTRYPOINT ["/usr/local/bin/annha-db"]
CMD ["inspect"]
