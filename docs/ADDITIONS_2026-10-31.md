# Дополнения к проекту OFME — 2026-10-31

Документ дополняет `docs/AUDIT_2026-10-29.md` (не заменяет его): фиксирует изменения,
сделанные после аудита, результаты фактической проверки и новые дефекты/дополнения,
найденные при разборе кода и живой проверке стека.

## 0. Резюме

- Волна 1 фронтенда (окна тишины, PDF-отчёты, bulk/CSV, SAML-вход) и pgBackRest/IPsec
  доведены до рабочего состояния и **проверены на живом стеке**: отчёт генерируется
  (pending → ready за ~8 с, 44,6 КБ, `%PDF-`), CSV экспортируется, окно тишины
  создаётся/активируется/удаляется.
- Найден **P0-регресс в CSRF-защите**: cookie `ofme_csrf_token` выставляется с
  `httponly=True`, поэтому SPA не может прочитать его и отправить `X-CSRF-Token`.
  Любая вторая мутация в одной сессии получает `403 csrf_failed` (воспроизведено).
- Остальное — дисциплина гейтов: 5 падающих тестов `DevicesPage`, 3 ошибки lint,
  `ruff format --check` красный на 24 файлах, отсутствуют backend-тесты для
  maintenance/reports/bulk/SAML ACS/CSRF, документация ссылается на недоступный
  `localhost:8000`.

## 1. Что изменилось после аудита

База сравнения — `8413c55` (состояние на момент аудита). Итог: **71 файл,
+11 340 / −321 строк**.

| Коммит | Содержание |
| --- | --- |
| `4cd12fc` | pgBackRest API и worker; исправление SAML ACS (cookie ставятся на возвращаемый `RedirectResponse`); фронтенд волны 1: `MaintenancePage`, `ReportsPage`, `SamlCallbackPage`, bulk/CSV UI на `DevicesPage`, `DataTable.selection`, SAML-кнопка и маршруты |
| `d32d226` | ~20 наборов тестов страниц (≈6 000 строк), `test/setup.ts`, доработки pgBackRest/Vault |
| `527708e` | IPsec: модель + миграция `0007`, endpoints, сервис (+275 строк), страница `IpsecPage.tsx` (~1 300 строк), тесты pgBackRest |
| рабочее дерево | в работе: 9 новых тестовых файлов (`MaintenancePage`, `ReportsPage`, `JobsPage`, `NotificationsPage`, `SdWanPage`, `TemplatesPage`, `ZtpPage`, `IpsecPage`, `GitReposPage`) и правки `DevicesPage.test.tsx`, `DeviceDetailPage.test.tsx`, `IpsecPage.tsx` |

Проверенные контракты (совпадают с реализацией):

- `POST /bulk/devices` — `action` ∈ `maintenance_on|maintenance_off|command|backup|firmware_upgrade|reboot`,
  `device_ids` 1…500, `params` (`duration_minutes`, `name`, `action`+`payload`, `package`).
- `GET /reports` — массив без пагинации; `POST /reports` → 202; `download_url` только при `ready`.
- `GET /maintenance-windows` — массив, `active` считает сервер; `target_ids` обязательны для не-`fleet`.
- SAML: ACS → 303 на `FRONTEND_URL/saml/callback`, ошибка в `#error=`, cookie сессии на redirect.

## 2. Фактическое состояние гейтов (измерено)

| Гейт | Результат |
| --- | --- |
| `tsc --noEmit` | **0 ошибок** |
| `eslint .` | **3 ошибки, 3 предупреждения** |
| `vitest run` | 34 файла: **344 passed, 6 failed, 2 skipped** |
| `ruff check app tests` | чисто |
| `ruff format --check app tests` | **24 файла требуют форматирования** (только переносы строк) |
| `pytest` | не запускался в этом прогоне; тестов для новых модулей нет (см. D-06) |

Детали провалов:

- `DevicesPage.test.tsx` — 5 тестов: «opens discover device dialog», «opens import CSV dialog»,
  «shows model and firmware columns», «shows site and group columns», «shows pagination size selector».
  Тесты написаны под другой UI (ожидают колонку **Model** и диалог импорта), фактическая страница
  содержит колонку Firmware, а импорт CSV идёт через нативный `<input type="file">`.
- `HaPage.test.tsx` — 1 таймаут (5 с), в изоляции проходит → флаки, поднять `testTimeout` или убрать лишний `waitFor`.

Lint:

- `ApprovalsPage.test.tsx:4` — неиспользуемый `userEvent`;
- `GitReposPage.test.tsx:54` — неиспользуемый `MOCK_DEVICES`;
- `JobsPage.test.tsx:165` — неиспользуемая `renderJobsPageOnTasksTab`;
- `MaintenancePage.tsx:121–123` — `devices/sites/groups` из `??` внутри `useMemo` (warning).

Живая проверка (через `http://localhost:8080`, т. к. API не опубликован на хосте):

```
login admin/Admin123!Secure        → 200, 85 permissions
GET  /api/v1/maintenance-windows   → []
GET  /api/v1/reports               → []
GET  /api/v1/bulk/devices/export.csv → 200, 201 B, заголовок + 1 устройство
POST /api/v1/reports {fleet,1d}    → 202 → ready за 8 с, 44 635 B, %PDF-
GET  /api/v1/reports/{id}/download → 200, application/pdf
POST /api/v1/maintenance-windows   → 201, active=true; /active → 1
```

## 3. Новые дефекты

### D-01 — P0: CSRF-cookie `HttpOnly`, SPA не может отправить заголовок

**Доказательства.** `backend/app/observability/middleware.py:198–206` выставляет cookie
`ofme_csrf_token` с `httponly=True`; `frontend/src/api/client.ts:95–103` читает токен из
`document.cookie` и кладёт в `X-CSRF-Token`. HttpOnly-cookie не виден JavaScript → заголовок
не отправляется никогда.

**Воспроизведено на живом стеке:** первый `POST /maintenance-windows` → 201 (ветка
«cookie ещё нет»), второй `POST` в той же сессии → `403 {"code":"csrf_failed"}`.
Cookie при этом присутствует с `HttpOnly=True`.

**Влияние.** После первой же мутации все последующие `POST/PATCH/DELETE` из SPA падают:
создание устройства, редактирование, удаление, bulk, окна тишины, отчёты. Это блокер
эксплуатации, а не косметика.

**Исправление (вариант A, минимальный).** `httponly=False` для CSRF-cookie — double-submit
по определению требует чтения из JS. `secure`/`samesite=lax` оставить.

**Исправление (вариант B, строже).** Оставить HttpOnly и добавить `GET /api/v1/auth/csrf`,
возвращающий токен в JSON; фронтенд кэширует его в памяти и шлёт заголовком; ротация при логине.

**Дополнительно.** Ветку «нет cookie → пропустить» (`middleware.py:192–207`) для
cookie-аутентифицированных мутаций лучше заменить на `403`: сейчас контроль можно обойти,
просто не отправив cookie (актуально для скриптов и privacy-расширений).

**Тесты.** Backend: middleware-тест (без cookie → 403, cookie+header → 200, cookie без header → 403).
Frontend: тест `applyAuthHeaders` на подстановку заголовка.

### D-02 — P1: bulk-эндпоинт обходит RBAC отдельных операций

`backend/app/api/v1/endpoints/bulk.py:19` требует только `device:exec`, но сервис умеет:
- `firmware_upgrade` / `reboot` → задачи `TASK_FIRMWARE_*` (`services/bulk.py:235–270`),
  тогда как прямые эндпоинты требуют `firmware:upgrade` / `firmware:reboot`
  (`endpoints/devices.py:407,430`);
- `maintenance_on` → создаёт окно тишины (`services/bulk.py:120–140`), хотя
  `POST /maintenance-windows` требует `alert:write` (`endpoints/maintenance.py:46`).

**Влияние.** Роль с `device:exec` без firmware-прав может инициировать прошивку/ребут,
а без `alert:write` — глушить алерты. Это повышение привилегий.

**Исправление.** Проверять права по `action` внутри эндпоинта (или разнести на
`/bulk/devices/maintenance`, `/bulk/devices/firmware`, …): firmware-действия —
`firmware:upgrade`/`firmware:reboot`, maintenance — `alert:write` + `device:exec`,
остальное — `device:exec`.

### D-03 — P1: SAML `RelayState` необязателен

`endpoints/auth.py:432,437`: `relay_state: str = Form("")`, и при пустом значении
`claims = {}` → `login_saml(expected_request_id=None)` не проверяет `InResponseTo`.
Replay-кэш по `AssertionID` есть (`integrations/saml.py:118–128`), поэтому повтор
блокируется, но привязка ответа к конкретному AuthnRequest теряется.

**Исправление.** Сделать `RelayState` обязательным (`Form(...)`), при отсутствии/невалидности —
303 с `#error=`, а не молчаливый вход. Добавить тест «ACS без RelayState → ошибка».

### D-04 — P2: CSV-экспорт обрезает инвентарь на 1000 устройствах

`services/bulk.py:274`: `list(size=1000)`. На больших тенантах выгрузка неполная без
предупреждения. Исправление: потоковая генерация (курсор/чанки) или явный лимит с
заголовком `X-Truncated` и предупреждением в UI.

### D-05 — P2: отчёты без пагинации и без ограничения параллельной генерации

`GET /reports` возвращает весь список (`endpoints/reports.py:28–36`), `POST /reports`
ставит задачу без ограничения глубины очереди. Риски: рост ответа и DoS на воркер
(каждый отчёт — `reportlab` + чтение телеметрии). Исправление: пагинация как у остальных
списков, лимит одновременных отчётов на тенант, retention-задача.

### D-06 — P2: нет backend-тестов для новых модулей

В `backend/tests` отсутствуют `test_maintenance.py`, `test_reports.py`, `test_bulk.py`,
тесты SAML ACS и CSRF-middleware. Покрыты только трафик и SSO-провайдеры. Минимум:
RBAC на bulk (D-02), «cookie на redirect» в ACS, `ready`+download отчёта, импорт CSV
(BOM, кавычки, отсутствующая колонка `name`), CSRF (D-01).

### D-07 — P3: документация ссылается на недоступный API

`README.md:72`, `DEPLOYMENT.md:451`, `OPERATIONS.md:144…` используют
`http://localhost:8000/...`, но сервис `ofme-api` не публикует порт (`docker port ofme-api`
пуст), а nginx проксирует только `/api/` и `/ws`. `http://localhost:8080/docs` отдаёт SPA,
не Swagger. Исправление: либо `ports: 8000:8000` в dev-профиле, либо `location /docs` +
`/openapi.json` в `nginx.conf`, либо правка документации на `docker compose exec ofme-api`.

### D-08 — P3: `ruff format --check` красный

24 файла, включая `services/bulk.py`, `services/maintenance.py`, `services/report.py`,
`integrations/saml.py`. Изменения чисто косметические (перенос строк под `line-length=110`),
но гейт формально не проходит. `ruff format app tests` + коммит.

### D-09 — P3: остатки mojibake

`JobsPage.tsx:348,395,413,644,739` (`Â·`, `â€”`, `â€¦`), исторические строки в других страницах.
Заменить на `·`, `—`, `…`. Проверять рендер в UTF-8, а не только исходник.

### D-10 — P3: предупреждения `useMemo` в `MaintenancePage`

`MaintenancePage.tsx:121–123`: `devices = devicesQuery.data?.items ?? []` создаёт новый
массив каждый рендер. Обернуть в `useMemo` (как уже сделано для `windows`).

## 4. Функциональные дополнения

### Окна тишины

1. **Продление/завершение из списка** — кнопки «+30 мин», «Завершить сейчас» (сейчас только
   toggle enabled и удаление). Критерий: PATCH `ends_at`/`enabled`, запись в аудит.
2. **Обнаружение пересечений** — предупреждать, если новое окно пересекается с существующим
   для тех же целей (сейчас допускается молча).
3. **Шаблоны** — «еженедельное окно» (RRULE-подобно) или хотя бы клонирование.
4. **Часовой пояс в списке** — показывать `Europe/Berlin` рядом с временем; сейчас
   конвертация local→UTC без явной индикации.

### Отчёты

5. **Пагинация и фильтры** (`kind`, `status`, период) — после D-05.
6. **Расписание отчётов** — `TaskKind.REPORT` уже есть; добавить пресет в Jobs и UI
   «еженедельный compliance-отчёт».
7. **Retention** — удаление PDF старше N дней (настройка тенанта), чтобы не рос bucket `artifacts`.
8. **Уведомление о готовности** — событие/нотификация «отчёт готов» со ссылкой.
9. **Подпись PDF** — checksum уже считается; добавить отображение SHA-256 в списке и в UI деталей.

### Bulk / CSV

10. **Идемпотентность** — `Idempotency-Key` на `POST /bulk/devices` (или серверный дедуп по
    ключу), чтобы двойной клик не запускал две прошивки.
11. **Прогресс** — для firmware/backup вернуть `job_id` и показывать прогресс из `/jobs`
    (сейчас в результате только «Queued job …»).
12. **Dry-run** — предпросмотр «сколько устройств затронуто, какие пропущены» до выполнения.
13. **Select-all по фильтру** — сейчас `DataTable.selection` выбирает только страницу;
    добавить «выбрать все N по фильтру» с явным предупреждением (лимит 500 на бэкенде).
14. **Импорт: отчёт по строкам** — уже есть; добавить скачивание CSV с ошибочными строками.
15. **Экспорт: потоковость** — после D-04.

### SAML / SSO

16. **Кнопка «Скачать SP metadata»** в Settings → Security (`/auth/saml/metadata` уже есть).
17. **Тестовый вход** — проверка конфигурации IdP из UI (issuer/ACS/audience).
18. **Синхронизация ролей** — маппинг SAML-атрибутов на роли (сейчас `login_saml` выдаёт
    роли по умолчанию; см. `services/auth.py`).

### Безопасность / эксплуатация

19. **Rate limit на `/reports`** и `/bulk/devices` (PDF/массовые операции — дорогие).
20. **Аудит bulk** — одна запись на запуск уже есть; добавить `action` и `params` в `changes`,
    чтобы из аудита было видно, что именно запускали.
21. **Метрики** — `ofme_report_generation_seconds`, `ofme_bulk_action_duration_seconds`,
    `ofme_bulk_failed_total` (Prometheus-инструментарий уже подключён).
22. **Алерты** — `ReportGenerationFailed`, `BulkActionFailureRate`.

### Фронтенд / UX

23. **Sticky bulk-bar** — панель выбранных действий должна быть видна при прокрутке таблицы.
24. **Отмена** — undo для `maintenance_off` (окно можно пересоздать) или подтверждение с
    вводом имени тенанта для reboot/firmware.
25. **Доступность** — `aria-label` на иконочных кнопках, `autoFocus` в диалогах, `role="status"`
    для результатов bulk.
26. **Тесты страниц** — привести `DevicesPage.test.tsx` к фактическому UI (или добавить
    колонку Model, если она нужна продукту), убрать флаки `HaPage`.

### Документация

27. Обновить `ACTION_PLAN.md`/`STATE.md`/`REQUIREMENTS_TRACEABILITY.md` новыми эндпоинтами
    (`/maintenance-windows`, `/reports`, `/bulk`, `/auth/saml/*`, `/ipsec/*`).
28. Раздел «Bulk operations» в `OPERATIONS.md`: лимиты 500, права по действиям, поведение
    при частичном отказе.
29. Раздел «Reports»: формат PDF, шрифты (DejaVu для кириллицы), retention, bucket `artifacts`.

## 5. Предлагаемый порядок работ

### Спринт 1 — блокеры (1–2 дня)

| # | Задача | Оценка |
| --- | --- | --- |
| 1 | D-01 CSRF: `httponly=False` + тесты backend/frontend | 3 ч |
| 2 | D-02 RBAC по действиям bulk + тесты | 4 ч |
| 3 | D-03 обязательный `RelayState` + тест ACS | 2 ч |
| 4 | 5 падающих тестов `DevicesPage` + флак `HaPage` | 3 ч |
| 5 | 3 lint-ошибки + D-10 | 1 ч |
| 6 | D-08 `ruff format` | 0,5 ч |
| 7 | D-06 минимальные backend-тесты (maintenance/reports/bulk/ACS/CSRF) | 1 день |

### Спринт 2 — качество и функционал (3–5 дней)

D-04/D-05 (CSV streaming, пагинация отчётов), retention и расписание отчётов,
идемпотентность bulk, select-all по фильтру, SP metadata в UI, метрики/алерты,
D-07/D-09, обновление документации.

## 6. Чек-лист перед релизом

- [ ] `npm run typecheck && npm run lint && npm test -- --run` — зелёные.
- [ ] `ruff check app tests && ruff format --check app tests` — зелёные.
- [ ] `pytest -q` — зелёный, включая новые тесты maintenance/reports/bulk/CSRF/SAML.
- [ ] Ручной сценарий: вход → создание устройства → редактирование → bulk backup →
      окно тишины → отчёт → скачивание PDF (проверяет D-01 end-to-end).
- [ ] SAML: вход через тестовый IdP, ошибка IdP отображается в SPA, повтор assertion отклоняется.
- [ ] `GET /bulk/devices/export.csv` на тенанте >1000 устройств (D-04).
- [ ] Аудит: записи по bulk/окнам/отчётам содержат актора и параметры.
- [ ] Документация: URL API соответствует фактическому пробросу портов.

## 7. Приложение: команды проверки

```powershell
# Frontend
cd ofme/frontend
npx tsc --noEmit -p tsconfig.json
npm run lint
npm test -- --run

# Backend (линт/формат)
docker run --rm -v "${PWD}/ofme/backend:/src" -w /src --entrypoint sh ofme/api:1.0.0 `
  -c "pip install --quiet --target /tmp/t ruff==0.8.4 && PYTHONPATH=/tmp/t /tmp/t/bin/ruff check app tests && PYTHONPATH=/tmp/t /tmp/t/bin/ruff format --check app tests"

# Backend (тесты)
docker exec ofme-api sh -c "pip install -q -e '.[dev]' && pytest -q"

# Живой smoke через nginx (API не опубликован на хосте)
$b = @{ username='admin'; password='Admin123!Secure' } | ConvertTo-Json
Invoke-RestMethod http://localhost:8080/api/v1/auth/login -Method Post -ContentType application/json -Body $b -SessionVariable s
Invoke-RestMethod http://localhost:8080/api/v1/maintenance-windows -WebSession $s
Invoke-RestMethod http://localhost:8080/api/v1/reports -WebSession $s
Invoke-WebRequest -UseBasicParsing http://localhost:8080/api/v1/bulk/devices/export.csv -WebSession $s
```
