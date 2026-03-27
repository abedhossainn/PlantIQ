# PlantIQ Frontend Dockerfile
# Next.js TypeScript React

FROM node:20-alpine

WORKDIR /app

# Copy package files only (build context is ./frontend)
COPY package.json .
COPY package-lock.json ./

# Install dependencies
RUN npm ci --prefer-offline --no-audit

# Copy configuration files needed for Next.js
COPY tsconfig.json .
COPY next.config.ts .
COPY postcss.config.mjs .

# Create dummy app directory structure (will be volume-mounted in development)
RUN mkdir -p app components lib pages public types

# Expose Next.js dev server port
EXPOSE 3000

# Default command (can be overridden by docker-compose)
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
