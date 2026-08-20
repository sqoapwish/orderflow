# OrderFlow Web

Next.js-интерфейс OrderFlow. Все браузерные запросы идут на same-origin `/api/v1` и проксируются в
FastAPI через `ORDERFLOW_API_INTERNAL_URL`.

```bash
npm ci
npm run dev
```

По умолчанию UI доступен на <http://localhost:3000>, а локальный API ожидается на
<http://localhost:8002>. Для production-сборки используйте `npm run build` или Dockerfile.

Проверки: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.
