FROM node:22-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY index.html ./
COPY tsconfig.json ./
COPY tsconfig.node.json ./
COPY vite.config.ts ./
COPY playwright.config.ts ./
COPY src ./src
COPY e2e ./e2e

EXPOSE 5173

CMD ["npm", "run", "dev"]
