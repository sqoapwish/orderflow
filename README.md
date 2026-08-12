# OrderFlow

[![CI](https://github.com/sqoapwish/orderflow/actions/workflows/ci.yml/badge.svg)](https://github.com/sqoapwish/orderflow/actions/workflows/ci.yml)

OrderFlow — backend-система управления заказами, оплатами и складскими остатками интернет-магазина. Проект развивается как модульный монолит уровня strong Junior+ с отдельными инженерными решениями уровня Middle: конкурентным резервированием товара, идемпотентностью, подписанными webhooks, Transactional Outbox, аудитом и наблюдаемостью.

> Текущий статус: завершены инженерная основа, аутентификация, каталог, складской учёт, корзина и транзакционное оформление заказа. Следующий бизнес-этап — платежи и строгий жизненный цикл заказа. Возможности не отмечаются готовыми до реализации и тестирования.

## Что уже работает

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
- асинхронная инфраструктура PostgreSQL, Redis и RabbitMQ;
- Celery worker с безопасными настройками доставки задач;
- Alembic и первая миграционная граница;
- liveness- и readiness-проверки;
- структурированные JSON-логи и сквозной `X-Correlation-ID`;
- единый JSON-формат HTTP-ошибок;
- Docker Compose с health checks и отдельной тестовой БД;
- Ruff, mypy, Pytest и integration-тест инфраструктуры;
- GitHub Actions: качество, тесты, миграции, Docker build и поиск секретов;
- Dependabot для Python, GitHub Actions и Docker-образов.

## Планируемые бизнес-возможности

- Mock Payment Provider, HMAC-webhooks, возвраты и защита от дублей;
- строгий конечный автомат статусов заказа;
- Transactional Outbox, retries и dead-letter обработка;
- аудит, аналитика, метрики и минимальный демонстрационный интерфейс.

## Архитектура

Основное приложение — модульный монолит. Модули разворачиваются вместе, но бизнес-правила и работа с данными разделены по предметным областям.

```mermaid
flowchart TD
    Client["Клиент или менеджер"] --> API["FastAPI API"]
    API --> Modules["Доменные модули"]
    Modules --> PostgreSQL["PostgreSQL"]
    Modules --> Redis["Redis"]
    Modules --> Outbox["Outbox-события"]
    Outbox --> Worker["Celery Worker"]
    Worker --> RabbitMQ["RabbitMQ"]
```

Подробности и принятые решения: [документация архитектуры](docs/architecture.md) и [ADR](docs/adr/0001-modular-monolith.md).

## Стек

| Область | Технологии |
|---|---|
| API | Python 3.12, FastAPI, Pydantic, PyJWT |
| Данные | PostgreSQL 17, SQLAlchemy 2 async, asyncpg, Alembic |
| Безопасность | Argon2id, access/refresh JWT, серверные сессии и RBAC |
| Кэш и очередь | Redis 8, RabbitMQ 4, Celery 5 |
| Качество | Ruff, mypy strict, Pytest, pytest-asyncio |
| Инфраструктура | Docker, Docker Compose, GitHub Actions, uv |
| Диагностика | JSON-логи, Correlation ID, health checks |

Точные совместимые версии всех Python-зависимостей зафиксированы в `uv.lock`.

## Быстрый запуск через Docker

Требования: Docker Desktop с Docker Compose.

PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

После запуска:

- Swagger: <http://localhost:8002/docs>
- liveness: <http://localhost:8002/api/v1/health/live>
- readiness: <http://localhost:8002/api/v1/health/ready>
- RabbitMQ UI: <http://localhost:15673>
- PostgreSQL для DBeaver: `localhost:5435`

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

Все endpoint складского модуля требуют роль `manager` или `admin`.

| Метод | Endpoint | Назначение |
|---|---|---|
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

Корзина не копирует цену: каждый ответ показывает актуальные данные активного каталога. Одна
позиция определяется парой товар/склад, а все позиции должны иметь одну валюту. Архивный товар
остаётся виден в уже созданной корзине как недоступный, но оформить его нельзя.

Checkout сериализует операции клиента и одинаковый ключ запроса advisory lock PostgreSQL. Первый
успешный запрос создаёт заказ со статусом `pending_payment` и возвращает `201`; точный повтор
возвращает тот же заказ с `200`. Название, SKU, цена и валюта копируются в `order_items`, поэтому
последующее изменение каталога не переписывает историю покупки.

Заказ, все позиции, складские резервы, движения и очистка корзины сохраняются одним commit. Если
товара не хватает хотя бы на одном складе, транзакция полностью откатывается: заказ и частичные
резервы не остаются, корзина не очищается. Платёжный вызов намеренно не входит в эту транзакцию и
будет реализован на следующем этапе.

Логи и остановка:

```powershell
docker compose logs -f api worker
docker compose down
```

## Локальная разработка

Требования: Python 3.12 и [uv](https://docs.astral.sh/uv/).

```bash
uv sync --frozen
uv run uvicorn orderflow.main:app --reload --port 8002
```

Без запущенной инфраструктуры `/live` вернёт `200`, а `/ready` — `503` с состояниями компонентов. Это ожидаемое поведение: процесс жив, но ещё не готов принимать рабочую нагрузку.

## Проверки

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -m "not integration"
uv run pytest --cov=orderflow --cov-report=term-missing
uv run alembic heads
```

Integration-тесты проверяют инфраструктуру, полный auth-flow, каталог, конкурентные складские резервы и идемпотентный checkout на настоящем PostgreSQL. В CI PostgreSQL, Redis и RabbitMQ поднимаются автоматически.

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
- GitHub Actions проверяет историю на случайно добавленные секреты;
- перед коммитом нужно проверить `git status` и не использовать реальные данные в тестах.

## Структура

```text
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
