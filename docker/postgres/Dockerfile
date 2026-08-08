FROM pgvector/pgvector:pg16-trixie@sha256:4ec7104bf04fff852b39d04502f9954e0e473c80323ccc058ab86bfe429f8500

# Compose always runs PostgreSQL as uid/gid 999, so the root-only gosu helper is
# unnecessary runtime attack surface.
USER root
RUN rm -f /usr/local/bin/gosu
USER 999:999
