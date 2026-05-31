FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_DATA_API_URL=http://localhost:8000
ARG VITE_INGEST_API_URL=http://localhost:8001
ENV VITE_DATA_API_URL=$VITE_DATA_API_URL
ENV VITE_INGEST_API_URL=$VITE_INGEST_API_URL
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
