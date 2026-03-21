FROM n8nio/n8n:2.11.4

COPY docker-entrypoint.sh /docker-entrypoint.sh

USER root
RUN chmod +x /docker-entrypoint.sh
USER node

ENTRYPOINT ["/docker-entrypoint.sh"]