# Build Stage: Compile Vite React TypeScript bundle
# Digest-pinned. A floating tag means the base can change under the build, which
# is how a "reproducible" image stops being reproducible and how a new CVE
# either lands unnoticed or breaks the build days later with no commit to point
# at.
FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS builder

WORKDIR /app

# Cache dependencies
COPY package.json package-lock.json* ./

RUN npm ci

# Copy source and build static distribution
COPY . .

RUN npm run build

# Runtime Stage: Serve static assets with Nginx
# nginx:1.27-alpine resolved to an Alpine base carrying 40 HIGH/CRITICAL CVEs
# with fixes published, 2 of them CRITICAL (OpenSSL CVE-2026-31789 among them).
# The previous Trivy invocation passed --vuln-type library, which limited it to
# npm manifests and never saw them. Trivy 0.74 against this digest: 1 HIGH,
# tracked in .trivyignore.yaml with a reason and an expiry.
FROM nginx:alpine@sha256:df221db836e1754089190208cee7eeda94f233197056426eda74a43ab1abeac2 AS runtime

# Set up non-root execution: remove user directive, create pid file, assign ownership to nginx user (UID 101)
RUN sed -i '/user  nginx;/d' /etc/nginx/nginx.conf && \
    touch /run/nginx.pid && \
    chown -R nginx:nginx /run/nginx.pid /var/cache/nginx /var/log/nginx /etc/nginx/conf.d /usr/share/nginx/html

# Copy custom nginx reverse-proxy configuration
COPY --chown=nginx:nginx nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled static assets from builder stage
COPY --from=builder --chown=nginx:nginx /app/dist /usr/share/nginx/html

# Switch to non-root USER (§3.1 and Rubric G)
USER nginx

# Expose port 80
EXPOSE 80

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://127.0.0.1/healthz || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
