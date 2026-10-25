# Development-oriented image that runs the Vite dev server.
FROM node:22-slim

WORKDIR /app

# Install dependencies first to leverage Docker layer caching.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173

# --host exposes the dev server outside the container.
CMD ["npm", "run", "dev", "--", "--host"]
