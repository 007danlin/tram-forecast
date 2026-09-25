FROM node:22.16.0-alpine AS build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM scratch AS export
COPY --from=build /app/frontend/dist/ /
