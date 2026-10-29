# Состояние OFME

Дата среза: **2026-10-28**. Документ фиксирует, что реально доведено до
устройства, где проходят границы реализации и как это проверить. Он дополняет
`REQUIREMENTS_TRACEABILITY.md` (матрица требований) и
`COMPETITIVE_GAP_ANALYSIS.md` (рыночные пробелы).

## 1. Итог итерации

Закрыты последние «фантомные» функции, которые были в UI/API, но не доезжали
до OPNsense:

| Область | Было | Стало | Где |
|---|---|---|---|
| NAT | push без владения и без повторяемости | идемпотентный push в `/api/firewall/d_nat`, `/api/firewall/source_nat`, `/api/firewall/one_to_one`, маркер `OFME-`, adoption `OFME:`, pruning | `services/configuration.py` (`nat_payload`, `deploy_nat`) |
| VLAN | push без сверки | ключ «родительский интерфейс + tag», обновление только при отличии, pruning | `services/configuration.py` (`vlan_payload`, `deploy_vlans`) |
| DHCP | только модели и CRUD | Kea DHCPv4: сабнеты и резервации, сопоставление по subnet/MAC, `option_data`, pruning осиротевших резерваций | `services/configuration.py` (`deploy_dhcp`), `POST /api/v1/dhcp/apply` |
| DNS | только модели и CRUD | Unbound host overrides (A/AAAA/MX/TXT), ключ «имя + тип + данные», pruning; CNAME — host alias на управляемый A/AAAA override; PTR/SRV/NS и отключённые записи — в `skipped` с причиной | `services/configuration.py` (`deploy_dns`), `POST /api/v1/dns/apply` |
| VPN-as-code | политика валидировалась, но не исполнялась | `VpnPolicyDeployer`: WireGuard (сервер + клиенты), IPsec (phase1/phase2 на пира), OpenVPN (CA + сертификат + серверный инстанс); детерминированные ключи, pruning, dry-run, teardown | `services/vpn_policy.py`, `DeploymentService.deploy` |
| SD-WAN WireGuard | один серверный объект, один ключ на обе стороны | на каждое устройство своя пара ключей и адрес туннеля; сервер + клиентские объекты, связь через relation `peers`; оба конца ребра настраиваются; re-apply = no-op | `services/sdwan.py` (`_apply_wireguard_endpoint`) |
| Teardown | удалённые туннели оставались на устройстве | удаление WireGuard-серверов/пиров, IPsec phase1/2 и OpenVPN-инстансов для туннелей, выпавших из плана; счётчик `tunnels_removed` | `services/sdwan.py` (`_remove_tunnel`), `TopologyDeployResult` |
| Rollback | только статус и аудит | снапшоты `before/after` для rules/NAT/VLAN/VPN и повторное применение на устройства; для VPN-политики, которой раньше не было, — teardown | `services/gitops.py` (`deploy`, `_restore_state`, `rollback`) |

Единый маркер владения — `OFME-` (например `OFME-web`). Объекты старых
релизов с `OFME:` по-прежнему распознаются, принимаются «в владение» и
удаляются при pruning, поэтому миграция не создаёт дубликатов.

## 2. Как это устроено

### 2.1 Два независимых пути для VPN

* **Топология SD-WAN** (`POST /api/v1/sdwan/topologies/{id}/deploy`) — рёбра
  между управляемыми устройствами. Ключи и адреса туннелей хранятся в
  `WireGuardKey`, планировщик `TopologyEngine` детерминирован.
* **VPN-политика** (`POST /api/v1/policies/{id}/deploy`, kind `VpnPolicy`) —
  один endpoint (сервер, пиры, туннельная сеть), который реплицируется на
  выбранные устройства. Приватные ключи в YAML не хранятся: они выводятся
  через HKDF из `SECRET_KEY` + имя политики + ID устройства, поэтому повторный
  apply не меняет ключи.

Пути не пересекаются по объектам, но используют один маркер владения и одно
правило идемпотентности.

### 2.2 Правило идемпотентности

`needs_update(existing, payload)` сравнивает только те поля, которые вернул
аппарат, нормализует список/строку и булевы значения. Поля, которых нет в
ответе, игнорируются. Поэтому второй apply даёт
`created = updated = deleted = 0` и не вызывает `reconfigure`.

Исключение — relation-поля (`peers`, `servers`): OPNsense возвращает их
словарём UUID, а payload передаёт списком. Для них набор UUID сравнивается
явно (`_relation_ids`), иначе каждый apply считался бы изменением.

### 2.3 Rollback

`PolicyDeployment.snapshot` хранит `before` и `after`:

* rules/NAT/VLAN — снимок таблиц желаемого состояния;
* VPN — скомпилированный `spec` предыдущего успешного деплоймента
  (для первого деплоймента — `null`, что означает «объектов не было»).

`rollback` восстанавливает записи в БД, применяет их тем же deployer'ом и
переводит деплоймент в `ROLLED_BACK` (или `FAILED`, если были ошибки).
Полное восстановление из подписанного бэкапа остаётся отдельным путём
(`POST /api/v1/backups/{id}/restore`).

## 3. Что остаётся ограничением

Это осознанные границы, а не незавершённые заглушки:

1. **ISC DHCP не программируется** — поддерживается только Kea DHCPv4.
   Скоупы ISC в Kea-модель не переносятся.
2. **DNS**: PTR, SRV и NS нельзя выразить в host-модели Unbound — они
   возвращаются в `skipped`. CNAME публикуется как host alias: для клиента
   ответ совпадает, но цепочки CNAME и TTL самой записи на устройстве нет.
   Записи с `enabled=false` не удаляются, а пропускаются.
3. **VPN-политика не раздаёт клиентские конфиги**: пиры задаются публичными
   ключами в YAML; приватный ключ пира и готовый `.conf` не экспортируются.
   WireGuard-ключи сервера детерминированы, но не ротируются автоматически.
4. **OpenVPN**: создаётся только серверный инстанс с управляемым CA и
   сертификатом. Клиентских инстансов, пользовательского PKI, MFA и статуса
   подключений нет. Если CA уже есть на устройстве, а его ключа нет в политике,
   apply возвращает `skipped` с причиной (нужно удалить управляемый CA).
5. **IPsec**: phase1/phase2 и teardown есть, HA-последовательности
   (сначала backup, потом master) нет.
6. **Нет живого OPNsense в этом окружении**: payload'ы построены по
   upstream-моделям OPNsense (`Server.xml`, `Client.xml`, `Unbound.xml`,
   DNat/Filter, Kea, trust), проверены fake-клиентом и dry-run через API.
   Round-trip на реальном устройстве нужно прогнать перед полевым пилотом.
7. **Агент по-прежнему пишет только aliases и firewall rules**. NAT, VLAN,
   DHCP, DNS и VPN применяются через REST API, интерфейсы и статические
   маршруты — через свои endpoint'ы/шаблоны (G-06).
8. **Steering/failover SD-WAN остаётся advisory** (G-09): выбор пути
   считается и показывается, но gateway groups на устройстве не создаются.
9. **Виртуализация/коммутаторы/Wi-Fi** — вне scope (см. волну 2 в
   `COMPETITIVE_GAP_ANALYSIS.md`).

## 4. Как проверить

### 4.1 Гейты

```bash
cd ofme/backend
ruff check app tests
ruff format --check app tests
pytest -q                       # с TEST_DATABASE_URL: 193 passed
pytest -q                       # без БД: 139 passed, 54 skipped

python scripts/export_openapi.py -o ../api/openapi.yaml --check
python scripts/export_openapi.py -o ../api/openapi.json --check

cd ../frontend
npm run lint && npm run typecheck && npm test -- --run && npm run build
```

Ожидаемые значения на этом срезе: ruff — `152 files already formatted`;
OpenAPI — 212 paths / 282 schemas; frontend — 28 тестов в 6 файлах.

### 4.2 Точечные тесты

```bash
pytest -q tests/test_config_deploy.py   # 8 тестов: rules/NAT/VLAN/DHCP/DNS
pytest -q tests/test_vpn_policy.py      # 9 тестов: WireGuard/IPsec/OpenVPN
pytest -q tests/test_core_features.py -k vpn
```

`test_config_deploy.py` проверяет: per-kind NAT payload, adoption `OFME:`,
pruning, list-form `option_data`, CNAME → host alias, отключённые записи в
`skipped`, dry-run, неизвестный ресурс.

`test_vpn_policy.py` проверяет: dry-run без вызова устройства, сервер + пиры,
relation `peers`, идемпотентность, pruning, `skipped` для пира без ключа и
IPsec-пира без endpoint, OpenVPN CA/cert/instance, случай «CA без ключа»,
teardown.

### 4.3 Живые проверки (Docker-стек)

```bash
# API и фронтенд
curl -s http://localhost:8000/healthz
curl -s http://localhost:8080/healthz

# dry-run DHCP/DNS (ничего не пишет на устройство)
curl -s -X POST http://localhost:8000/api/v1/dhcp/apply \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"device_id":"<uuid>","dry_run":true}'

# единый apply: по умолчанию только rules
curl -s -X POST http://localhost:8000/api/v1/configuration/apply \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"device_ids":["<uuid>"],"dry_run":true,"resources":["rules","nat","vlans","dhcp","dns"]}'

# VPN-политика: dry-run показывает payload'ы, устройство не вызывается
curl -s -X POST http://localhost:8000/api/v1/policies/<policy_id>/deploy \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"device_ids":["<uuid>"],"dry_run":true}'
```

Проверено на этом срезе: dry-run VPN-политики вернул
`server=OFME-live-vpn-check`, пира `OFME-live-vpn-check-peer-branch`,
`created=updated=deleted=0`, `applied=false`, статус деплоймента `completed`.
Dry-run DNS с CNAME возвращает запись в `aliases`, а не в `skipped`.

## 5. Статус реестра пробелов

Закрыты: **G-07** (VPN-политика исполняется `DeploymentService`), **G-08**
(per-peer ключи, адресация туннелей, оба конца ребра), **G-10** (teardown
IPsec/OpenVPN/WireGuard), **G-26** (HA/CARP failover), **G-27** (DHCP push),
**G-28** (DNS push), **G-29** (реальный rollback со снапшотом).

Остаются: **G-06** (агент пишет только aliases/rules), **G-09**
(steering advisory), а также инфраструктурные G-03/G-04/G-05/G-11/G-15…G-25
из `REQUIREMENTS_TRACEABILITY.md` §9. Ни один из них не блокирует сценарий
«policy-as-code → устройство → откат».
