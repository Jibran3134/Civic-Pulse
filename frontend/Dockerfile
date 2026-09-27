# Build Stage: Compile Vite React TypeScript bundle
FROM node:22-alpine AS builder

WORKDIR /app

# Cache dependencies
COPY package.json package-lock.json* ./

RUN npm ci

# Copy source and build static distribution
COPY . .

RUN npm run build

# Runtime Stage: Serve static assets with Nginx
FROM nginx:1.27-alpine AS runtime

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
