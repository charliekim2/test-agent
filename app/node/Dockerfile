FROM node:24-slim
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .

CMD ["node", "index.js"]
