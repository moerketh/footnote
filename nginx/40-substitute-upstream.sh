#!/bin/sh
# Substitute API_UPSTREAM env var into nginx config at startup.
# Default: api:8000 (Docker Compose). Override for Container Apps.
export API_UPSTREAM="${API_UPSTREAM:-api:8000}"
sed -i "s|API_UPSTREAM_PLACEHOLDER|${API_UPSTREAM}|g" /etc/nginx/conf.d/default.conf