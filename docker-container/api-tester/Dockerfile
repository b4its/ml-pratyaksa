FROM alpine:3.19

RUN apk add --no-cache curl jq

COPY api-test.sh /usr/local/bin/api-test.sh
RUN chmod +x /usr/local/bin/api-test.sh

# Keep container alive for interactive use
CMD ["sleep", "infinity"]
