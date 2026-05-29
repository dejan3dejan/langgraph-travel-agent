FROM node:22-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim
RUN npm install -g serve
COPY --from=build /app/dist /app
EXPOSE 3000
CMD ["serve", "-s", "/app", "-l", "3000"]
