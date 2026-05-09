# Build React (Vite) static assets, then serve with nginx.
FROM node:20-bookworm AS build
WORKDIR /app

ARG VITE_API_BASE_URL=/api/v1
ARG VITE_FACTORY_AGENT_BASE_URL=/agent
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_FACTORY_AGENT_BASE_URL=${VITE_FACTORY_AGENT_BASE_URL}

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx-frontend.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
