## Отгрузка Status: WB + Ozon FBS

Приложение полностью работает через API маркетплейсов:

- заказы не создаются вручную;
- данные подтягиваются из:
  - `https://api.wildberries.ru/api/v3/orders`
  - `https://api-seller.ozon.ru/v3/posting/fbs/list`
- синхронизация выполняется фоново каждые 15 минут через APScheduler;
- история статусов каждого заказа хранится в БД.

## Что есть в проекте

- **FastAPI** (API + WebApp)
- **SQLite + SQLAlchemy**
- **Telegram-бот (aiogram)**
- **APScheduler** для фоновой синхронизации
- **Экспорт заказов** в CSV и Excel

## Статусы заказов (13)

1. Новый заказ  
2. Заказ на сборке  
3. Передан в доставку  
4. Принят на складе  
5. Товар в пути к покупателю  
6. Прибыл на ПВЗ покупателя  
7. Выкупили  
8. Возврат  
9. Покупатель отказался от товара  
10. Возврат вернули как брак  
11. Возврат в пути от покупателя  
12. Возврат прибыл на ПВЗ продавца  
13. Продавец товар забрал

## Быстрый запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

WebApp: `http://localhost:8000/`

## Настройки API ключей

Ключи хранятся в таблице `settings`:

- `wb_token`
- `ozon_client_id`
- `ozon_api_key`

Указать/изменить ключи можно из вкладки **«Настройки»** в WebApp.

## Основные API-эндпоинты

- `GET /api/meta/statuses` — справочник статусов
- `GET /api/orders?marketplace=wb|ozon` — список заказов + история
- `GET /api/dashboard/{marketplace}` — сводка по WB/Ozon
- `GET /api/settings` / `PUT /api/settings` — чтение/сохранение ключей
- `POST /api/sync/run` — ручной запуск синхронизации
- `GET /api/export/orders.csv` — экспорт CSV
- `GET /api/export/orders.xlsx` — экспорт Excel

## Бот

Кнопки:

- `Заказы WB`
- `Заказы Ozon`
- `Сводка за сегодня`
- `Настройки`

`Заказы WB/Ozon` показывают последние 10 заказов с текущими статусами.
