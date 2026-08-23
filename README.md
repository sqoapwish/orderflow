# OrderFlow

[![CI](https://github.com/sqoapwish/orderflow/actions/workflows/ci.yml/badge.svg)](https://github.com/sqoapwish/orderflow/actions/workflows/ci.yml)

OrderFlow — полнофункциональный MVP управления заказами, оплатами и складскими остатками интернет-магазина. FastAPI-бэкенд и Next.js-интерфейс объединяют покупательский и операционный сценарии, а надёжность обеспечивают конкурентное резервирование, идемпотентность, подписанные webhooks, Transactional Outbox, аудит и наблюдаемость.

> Текущий статус: версия `1.0.0`, демонстрационный MVP завершён. Покупатель может пройти путь от регистрации и каталога до checkout и платёжной сессии; менеджер получает заказы, аналитику и склад, администратор — аудит. Реальный банковский эквайринг намеренно заменён воспроизводимым Mock Payment Provider.

## Что уже работает

- адаптивный Next.js-интерфейс на русском языке в едином визуальном стиле;
- покупательский путь: регистрация, вход, каталог, выбор склада, корзина и checkout;
- операционные экраны: заказы, аналитический dashboard, остатки и аудит;
- автоматическое обновление access-токена по ротационному refresh-токену;
- same-origin BFF-прокси между браузером и FastAPI без публикации внутреннего адреса API;
- FastAPI с версионированием `/api/v1` и OpenAPI/Swagger;
- регистрация, вход, выход и получение текущего пользователя;
- access/refresh JWT, серверные сессии, ротация refresh-токенов и защита от их повторного использования;
- роли `customer`, `manager`, `admin` и переиспользуемая проверка прав;
- Argon2id-хэширование паролей без хранения открытых паролей или refresh-токенов;
- вложенные категории с защитой от циклов и безопасным архивированием;
- товары с уникальными slug и SKU, ценой в минимальных денежных единицах и изображением;
- публичный поиск каталога, фильтры цены и категории, сортировка и пагинация;
- управление каталогом только для ролей `manager` и `admin`;
- несколько складов, физические, зарезервированные и доступные остатки;
- поступления, списания, корректировки и перемещения с неизменяемой историей;
- идемпотентные резервы с освобождением и погашением;
- конкурентная защита PostgreSQL от отрицательных остатков и двойной продажи;
- персональная корзина клиента с актуальными ценами и выбором склада;
- добавление, изменение количества, удаление и очистка позиций корзины;
- атомарный checkout с обязательным `Idempotency-Key`;
- неизменяемые снимки названия, SKU, цены и валюты в позициях заказа;
- общий commit заказа, резервов и очистки корзины с полным rollback при ошибке;
- собственная история заказов клиента и просмотр всех заказов менеджером;
- идемпотентные платёжные сессии Mock Payment Provider без обращения к реальному банку;
- HMAC-SHA256 webhooks с безопасным сравнением подписи, временным окном и защитой от replay;
- строгие статусы заказа: `pending_payment`, `paid`, `payment_failed`, `cancelled`, `refunded`;
- атомарное погашение или освобождение складских резервов по результату платежа;
- идемпотентный полный возврат без автоматического возврата товара на склад;
- Transactional Outbox: события заказа и платежа сохраняются вместе с бизнес-изменением;
- доставка событий через отдельные Celery-очереди и RabbitMQ с publisher confirms;
- пакетный конкурентный dispatcher с `FOR UPDATE SKIP LOCKED`;
- экспоненциальные retries и перевод исчерпанных событий в `dead_letter`;
- идемпотентный Inbox, который отклоняет изменённый повтор одного `event_id`;
- неизменяемый аудит доменных действий с исполнителем, объектом и `correlation_id`;
- безопасный whitelist деталей аудита без паролей, токенов и подписей;
- административный API аудита с фильтрами и пагинацией;
- отчёты по выручке, успешным, неуспешным и возвращённым платежам;
- топ проданных товаров и отчёт по низким доступным остаткам;
- защищённый Analytics API для `manager` и `admin` с фильтром дат;
- краткоживущий Redis cache-aside с безопасным fallback на PostgreSQL;
- Prometheus-метрики HTTP и сохранённых состояний Outbox;
- структурированные access-логи с маршрутом, статусом и длительностью запроса;
- асинхронная инфраструктура PostgreSQL, Redis и RabbitMQ;
- Celery worker с безопасными настройками доставки задач;
- Alembic и первая миграционная граница;
- liveness- и readiness-проверки;
- структурированные JSON-логи и сквозной `X-Correlation-ID`;
- единый JSON-формат HTTP-ошибок;
- Docker Compose с health checks и отдельной тестовой БД;
- Ruff, mypy, Pytest и integration-тест инфраструктуры;
- GitHub Actions: качество, тесты, миграции, Docker build и поиск секретов;
- Dependabot для Python, npm, GitHub Actions и Docker-образов.

## Границы MVP

- платёжная сессия создаётся в Mock Payment Provider и не принимает реальные платёжные данные;
- публичная регистрация безопасно создаёт только роль `customer`;
- наполнение каталога и назначение ролей выполняются через защищённый API или административные инструменты, а не через публичный интерфейс;
- UI показывает основные рабочие сценарии, но не заменяет специализированную ERP/WMS.

## Архитектура

Основное приложение — модульный монолит. Модули разворачиваются вместе, но бизнес-правила и работа с данными разделены по предметным областям.

```mermaid
flowchart TD
    Client["Клиент или менеджер"] --> Web["Next.js UI"]
    Web --> Proxy["Same-origin API proxy"]
    Proxy --> API["FastAPI API"]
    API --> Modules["Доменные модули"]
    Modules --> PostgreSQL["PostgreSQL"]
    Modules --> Redis["Redis"]
    Modules --> Outbox["Outbox-события"]
    Outbox --> Dispatcher["Celery dispatcher"]
    Dispatcher --> RabbitMQ["RabbitMQ"]
    RabbitMQ --> Consumer["Celery consumer"]
    Consumer --> Inbox["Inbox deduplication"]
    Consumer --> Audit["Неизменяемый аудит"]
    API --> Analytics["Отчёты analytics"]
    Analytics --> PostgreSQL
    Analytics --> Redis
    API --> Metrics["/metrics"]
    Prometheus["Prometheus"] --> Metrics
```

Подробности и принятые решения: [документация архитектуры](docs/architecture.md) и [ADR](docs/adr/0001-modular-monolith.md).

## Стек

| Область | Технологии |
|---|---|
| API | Python 3.12, FastAPI, Pydantic, PyJWT |
| Интерфейс | Next.js 16, React 19, TypeScript 5.9, CSS |
| Данные | PostgreSQL 17, SQLAlchemy 2 async, asyncpg, Alembic |
| Безопасность | Argon2id, access/refresh JWT, серверные сессии и RBAC |
| Кэш и очередь | Redis 8, RabbitMQ 4, Celery 5 |
| Качество | Ruff, mypy strict, Pytest, pytest-asyncio |
| Инфраструктура | Docker, Docker Compose, GitHub Actions, uv |
| Диагностика | JSON-логи, Correlation ID, health checks, Prometheus metrics |

Точные совместимые версии зависимостей зафиксированы в `uv.lock` и `frontend/package-lock.json`.

## Быстрый запуск через Docker

Требования: Docker Desktop с Docker Compose.

PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
docker compose exec api python scripts/seed_demo.py
```

Prometheus подключается отдельным профилем и не расходует ресурсы при обычном запуске:

```powershell
docker compose --profile monitoring up --build -d
```

- метрики приложения: [http://localhost:8002/metrics](http://localhost:8002/metrics);
- Prometheus: [http://localhost:9090](http://localhost:9090).

После запуска:

- интерфейс: <http://localhost:3000>
- Swagger: <http://localhost:8002/docs>
- liveness: <http://localhost:8002/api/v1/health/live>
- readiness: <http://localhost:8002/api/v1/health/ready>
- RabbitMQ UI: <http://localhost:15673>
- PostgreSQL для DBeaver: `localhost:5435`

Последняя команда создаёт локальные товары, склад и три тестовых аккаунта и печатает данные для
входа. Seed идемпотентен и программно запрещён в `staging` и `production`; пароли можно переопределить
через `ORDERFLOW_DEMO_CUSTOMER_PASSWORD`, `ORDERFLOW_DEMO_MANAGER_PASSWORD` и
`ORDERFLOW_DEMO_ADMIN_PASSWORD`.

## Аутентификация

| Метод | Endpoint | Назначение |
|---|---|---|
| `POST` | `/api/v1/auth/register` | Создать пользователя с ролью `customer` и первую сессию |
| `POST` | `/api/v1/auth/login` | Проверить пароль и создать отдельную сессию |
| `POST` | `/api/v1/auth/refresh` | Однократно использовать refresh-токен и получить новую пару |
| `POST` | `/api/v1/auth/logout` | Отозвать refresh-сессию; повторный logout безопасен |
| `GET` | `/api/v1/auth/me` | Получить актуального пользователя по Bearer access-токену |

Публичная регистрация всегда создаёт только `customer`: клиент не может передать себе роль менеджера или администратора. Access-токен живёт 15 минут, refresh-сессия — 30 дней. В PostgreSQL хранится SHA-256-хэш refresh-токена, а не сам токен. При обновлении строка сессии блокируется `SELECT FOR UPDATE`; повторное использование старого токена отзывает всю сессию.

## Каталог

| Метод | Endpoint | Доступ и назначение |
|---|---|---|
| `GET` | `/api/v1/catalog/categories` | Публичный список активных категорий |
| `GET` | `/api/v1/catalog/categories/{slug}` | Публичная активная категория |
| `POST` | `/api/v1/catalog/categories` | Создание, только `manager`/`admin` |
| `PATCH` | `/api/v1/catalog/categories/id/{category_id}` | Изменение, только `manager`/`admin` |
| `DELETE` | `/api/v1/catalog/categories/id/{category_id}` | Архивирование, только `manager`/`admin` |
| `GET` | `/api/v1/catalog/products` | Публичный поиск и страница активных товаров |
| `GET` | `/api/v1/catalog/products/{slug}` | Публичный активный товар |
| `POST` | `/api/v1/catalog/products` | Создание, только `manager`/`admin` |
| `PATCH` | `/api/v1/catalog/products/id/{product_id}` | Изменение, только `manager`/`admin` |
| `DELETE` | `/api/v1/catalog/products/id/{product_id}` | Архивирование, только `manager`/`admin` |

Список товаров принимает `search`, `category_id`, `min_price_minor`, `max_price_minor`, `sort_by`, `sort_direction`, `page` и `page_size`. Поиск работает по названию и SKU без учёта регистра; в ответе есть общее количество записей и страниц. Публичные запросы никогда не возвращают архивный товар или товар из архивной категории.

Цена хранится целым числом в минимальных денежных единицах: `199900` означает `1999.00 RUB`. Это исключает ошибки двоичного округления `float` и позволит будущему заказу точно зафиксировать цену на момент покупки. `DELETE` не удаляет строки физически, а меняет `is_active`, чтобы будущая история заказов не потеряла ссылки на товары.

## Складской учёт

Операционные endpoint складского модуля требуют роль `manager` или `admin`. Публичное чтение доступности конкретного активного товара используется каталогом и не изменяет данные.

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/api/v1/inventory/availability/{product_id}` | Публичные доступные остатки активного товара по активным складам |
| `GET/POST` | `/api/v1/inventory/warehouses` | Список и создание складов |
| `PATCH/DELETE` | `/api/v1/inventory/warehouses/{warehouse_id}` | Изменение и архивирование пустого склада |
| `GET` | `/api/v1/inventory/stock` | Остатки с фильтрацией и пагинацией |
| `POST` | `/api/v1/inventory/stock/receipts` | Поступление товара |
| `POST` | `/api/v1/inventory/stock/write-offs` | Списание доступного товара |
| `POST` | `/api/v1/inventory/stock/adjustments` | Корректировка по результату пересчёта |
| `POST` | `/api/v1/inventory/stock/transfers` | Перемещение между складами |
| `GET` | `/api/v1/inventory/movements` | История движений и резервов |
| `POST` | `/api/v1/inventory/reservations` | Идемпотентное создание резерва |
| `GET` | `/api/v1/inventory/reservations/{reservation_id}` | Получение резерва |
| `POST` | `/api/v1/inventory/reservations/{reservation_id}/release` | Освобождение резерва |
| `POST` | `/api/v1/inventory/reservations/{reservation_id}/consume` | Погашение резерва при продаже |

`on_hand` хранит физическое количество, `reserved` — обещанное незавершённым операциям, а `available = on_hand - reserved`. PostgreSQL запрещает отрицательные значения и резерв больше физического остатка. Списание, перенос и новый резерв используют только `available`.

Операции блокируют затрагиваемые строки `stock_balances` через `SELECT FOR UPDATE` в детерминированном порядке. Уникальный `reservation_key` защищён transaction-level advisory lock: одинаковый повтор возвращает существующий резерв, а параллельные запросы не резервируют одну единицу дважды. Каждое изменение создаёт неизменяемое движение с дельтой, итоговым снимком остатка, исполнителем и общим `operation_id` для двух сторон перемещения.

## Корзина и заказы

Корзина доступна только роли `customer`, а заказы читают все аутентифицированные роли с разной
областью видимости.

| Метод | Endpoint | Доступ и назначение |
|---|---|---|
| `GET/DELETE` | `/api/v1/cart` | Получить или очистить свою корзину |
| `POST` | `/api/v1/cart/items` | Добавить товар и склад; повтор увеличивает количество |
| `PATCH/DELETE` | `/api/v1/cart/items/{item_id}` | Изменить количество или удалить позицию |
| `POST` | `/api/v1/orders/checkout` | Оформить корзину; только `customer`, обязателен `Idempotency-Key` |
| `GET` | `/api/v1/orders` | Клиент видит свои, `manager`/`admin` — все заказы |
| `GET` | `/api/v1/orders/{order_id}` | Получить доступный заказ со снимками позиций |
| `POST` | `/api/v1/orders/{order_id}/cancel` | Отменить ожидающий оплаты заказ и освободить резервы |

Корзина не копирует цену: каждый ответ показывает актуальные данные активного каталога. Одна
позиция определяется парой товар/склад, а все позиции должны иметь одну валюту. Архивный товар
остаётся виден в уже созданной корзине как недоступный, но оформить его нельзя.

Checkout сериализует операции клиента и одинаковый ключ запроса advisory lock PostgreSQL. Первый
успешный запрос создаёт заказ со статусом `pending_payment` и возвращает `201`; точный повтор
возвращает тот же заказ с `200`. Название, SKU, цена и валюта копируются в `order_items`, поэтому
последующее изменение каталога не переписывает историю покупки.

Заказ, все позиции, складские резервы, движения и очистка корзины сохраняются одним commit. Если
товара не хватает хотя бы на одном складе, транзакция полностью откатывается: заказ и частичные
резервы не остаются, корзина не очищается. Платёжный вызов намеренно не входит в эту транзакцию:
для него создан отдельный идемпотентный сценарий.

## Платежи и жизненный цикл заказа

Встроенный Mock Payment Provider не обращается к банку и предназначен для воспроизводимой
демонстрации платёжного сценария.

| Метод | Endpoint | Доступ и назначение |
|---|---|---|
| `POST` | `/api/v1/payments/sessions` | Клиент создаёт сессию для своего заказа; обязателен `Idempotency-Key` |
| `GET` | `/api/v1/payments` | Клиент видит свои, `manager`/`admin` — все платежи |
| `GET` | `/api/v1/payments/{payment_id}` | Получить доступный платёж и сведения о возврате |
| `POST` | `/api/v1/payments/{payment_id}/refunds` | Идемпотентный полный возврат, только `manager`/`admin` |
| `POST` | `/api/v1/payments/webhooks/mock` | Публичная точка приёма подписанного webhook провайдера |

Webhook подписывается HMAC-SHA256 по строке `<unix_timestamp>.<raw_body>`. API использует
`X-Payment-Timestamp` и `X-Payment-Signature`, сравнивает подпись через constant-time функцию,
отклоняет запросы старше пяти минут и сохраняет хэш тела под уникальным `event_id`. Точный повтор
возвращает `duplicate`, а повтор того же ID с другим телом отклоняется.

Событие `payment.succeeded` переводит заказ из `pending_payment` в `paid` и в одной транзакции
погашает все резервы: уменьшаются `reserved` и `on_hand`. `payment.failed` переводит заказ в
`payment_failed` и освобождает резервы. Отмена ожидающего заказа также освобождает их. Полный
refund разрешён только для успешной оплаты, фиксирует статусы `refunded` у платежа и заказа, но
не увеличивает складской остаток: физический возврат товара является отдельной складской операцией.

## Transactional Outbox

Изменение бизнес-состояния и соответствующее доменное событие имеют один PostgreSQL commit. Сейчас
создаются `order.created`, `order.cancelled`, `payment.succeeded`, `payment.failed` и
`payment.refunded`. Повтор идемпотентного checkout, webhook или refund не создаёт второе событие;
это дополнительно защищено уникальным `deduplication_key`.

Celery Beat регулярно запускает dispatcher. Он выбирает доступные `pending`-события пакетами через
`FOR UPDATE SKIP LOCKED`, поэтому несколько worker-процессов не забирают одну строку одновременно.
После подтверждённой публикации в RabbitMQ событие становится `published`. Временная ошибка
увеличивает `attempts` и назначает экспоненциальную задержку; после лимита строка переходит в
`dead_letter`, не блокируя остальные события.

Гарантия доставки — at-least-once: сбой между отправкой сообщения и фиксацией статуса может вызвать
повтор. Получатель сохраняет `event_id` и SHA-256 канонического сообщения в `inbox_events`: точный
повтор безопасно игнорируется, а тот же идентификатор с изменённым содержимым отклоняется. В логах
dispatcher и consumer сохраняются `event_id`, тип события и исходный `correlation_id`.

## Аудит

После первой доставки доменного события consumer в одной PostgreSQL-транзакции создаёт запись
`inbox_events` и соответствующую запись `audit_events`. Повторная доставка не создаёт второй аудит.
Для защиты истории PostgreSQL-trigger запрещает `UPDATE` и `DELETE` строк аудита.

Аудит хранит действие, исполнителя или системный источник, тип и идентификатор объекта,
`correlation_id`, время исходного события и только явно разрешённые детали. Произвольный payload не
копируется, поэтому пароль, JWT, подпись webhook или другой неожиданный секрет в историю не попадёт.

Только пользователь с текущей ролью `admin` может читать историю:

- `GET /api/v1/audit/events` — фильтры по действию, исполнителю, объекту, `correlation_id` и времени;
- `GET /api/v1/audit/events/{event_id}` — одна запись аудита.

## Аналитика

Отчёты читают подтверждённые бизнес-факты из PostgreSQL. Успешные, неуспешные и возвращённые
платежи агрегируются по неизменяемым Outbox-событиям, поэтому итог не зависит от текущего статуса
платежа после refund. Топ товаров связывает событие успешной оплаты со снимками позиций заказа, а
низкие остатки вычисляются из активных товаров, складов и `on_hand - reserved`.

Доступ имеют только текущие `manager` и `admin`:

- `GET /api/v1/analytics/sales` — итоги по валютам и дням, включая gross, refunds и net;
- `GET /api/v1/analytics/products/top` — топ товаров по оплаченному количеству;
- `GET /api/v1/analytics/inventory/low-stock` — пагинированные остатки ниже порога.

Период по умолчанию — последние 30 календарных дней, максимальный период — 366 дней. Результаты
на короткое время кешируются в Redis; TTL задаётся через
`ORDERFLOW_ANALYTICS_CACHE_TTL_SECONDS`. Redis не является источником истины: ошибка чтения,
записи или повреждённый JSON приводят к прозрачному выполнению PostgreSQL-запроса.

## Наблюдаемость

`GET /metrics` отдаёт Prometheus exposition format. В памяти процесса считаются количество,
статусы и latency HTTP-запросов. Состояния `pending`, `published`, `dead_letter`, число неудачных
попыток доставки и возраст старейшего ожидающего события читаются непосредственно из PostgreSQL,
поэтому эта часть метрик сохраняется после перезапуска API.

Маршруты используются как низкокардинальные labels вместо реальных UUID. Если PostgreSQL временно
недоступен, endpoint продолжает отдавать HTTP-метрики и выставляет
`orderflow_outbox_metrics_scrape_success 0`. В production доступ к `/metrics` следует ограничить
на уровне внутренней сети или reverse proxy.

## Интерфейс

Next.js-приложение находится в `frontend/`. Браузер обращается только к относительному адресу
`/api/v1`; Route Handler проксирует запросы во внутренний FastAPI URL из
`ORDERFLOW_API_INTERNAL_URL`. В Docker Compose API остаётся доступен как `http://api:8000`, а
пользователь открывает единый origin `http://localhost:3000`. Отдельная CORS-конфигурация не нужна.

Интерфейс выбирает навигацию по текущей роли. `customer` видит каталог, корзину и свои заказы;
`manager` — dashboard, все заказы и склад; `admin` дополнительно получает аудит. Access/refresh
токены хранятся только в `sessionStorage`, очищаются при закрытии вкладки и автоматически
обновляются один раз после ответа `401`.

Логи и остановка:

```powershell
docker compose logs -f api worker beat
docker compose down
```

## Локальная разработка

Требования: Python 3.12, [uv](https://docs.astral.sh/uv/) и Node.js 24.

```bash
uv sync --frozen
uv run uvicorn orderflow.main:app --reload --port 8002
```

Во втором терминале:

```bash
cd frontend
npm ci
npm run dev
```

Интерфейс откроется на <http://localhost:3000> и по умолчанию будет проксировать API на
`http://localhost:8002`.

Без запущенной инфраструктуры `/live` вернёт `200`, а `/ready` — `503` с состояниями компонентов. Это ожидаемое поведение: процесс жив, но ещё не готов принимать рабочую нагрузку.

## Проверки

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests scripts/seed_demo.py
uv run pytest -m "not integration"
uv run pytest --cov=orderflow --cov-report=term-missing
uv run alembic heads

cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

Integration-тесты проверяют инфраструктуру, полный auth-flow, каталог, конкурентные складские резервы, идемпотентный checkout, полный платёжный lifecycle, атомарное появление Outbox-событий, общий commit Inbox с аудитом, запрет изменения истории и аналитические отчёты на настоящем PostgreSQL. В CI PostgreSQL, Redis и RabbitMQ поднимаются автоматически.

## Миграции

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
uv run alembic check
```

`alembic check` должен выполняться при запущенной PostgreSQL и подтверждает, что изменения моделей не остались без миграции.

## Безопасность конфигурации

- `.env` и любые `.env.*` исключены из Git;
- в репозитории хранится только `.env.example` с локальными демонстрационными значениями;
- реальные ключи, пароли и токены передаются через переменные окружения или secret storage платформы;
- production-запуск отклоняется, если используется демонстрационный JWT-секрет;
- production-запуск отклоняется, если используется демонстрационный секрет подписи webhooks;
- GitHub Actions проверяет историю на случайно добавленные секреты;
- перед коммитом нужно проверить `git status` и не использовать реальные данные в тестах.

## Структура

```text
frontend/                 # Next.js UI и same-origin proxy к API
src/orderflow/
├── api/             # HTTP-маршруты и версионирование
├── core/            # настройки, ошибки, логирование, Correlation ID
├── infrastructure/  # PostgreSQL, Redis, RabbitMQ и readiness
├── modules/         # изолированные бизнес-модули
├── schemas/         # общие Pydantic-схемы
└── workers/         # Celery и фоновые задачи
```

## Лицензия

Лицензия пока не выбрана. Код нельзя считать автоматически разрешённым для повторного использования.
