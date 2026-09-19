FROM node:22.16.0-alpine
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
EXPOSE 5173
CMD ["npm", "run", "preview"]
