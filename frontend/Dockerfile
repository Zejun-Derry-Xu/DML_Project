FROM node:22-alpine AS build
ARG BUILD_COMMIT=development
ENV BUILD_COMMIT=$BUILD_COMMIT
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build
RUN node -e "require('node:fs').writeFileSync('dist/version.json', JSON.stringify({commit:process.env.BUILD_COMMIT}))"

FROM nginx:1.29-alpine
ARG BUILD_COMMIT=development
LABEL org.opencontainers.image.revision=$BUILD_COMMIT
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

