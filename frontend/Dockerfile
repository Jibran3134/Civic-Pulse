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

# Copy custom nginx reverse-proxy configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled static assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose port 80
EXPOSE 80

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost/healthz || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
