# OFME vs. cloud-managed networking platforms — анализ пробелов

Дата: 2026-10-28. База: текущее состояние репозитория `ofme/` (190 путей OpenAPI,
79 прав, 27 страниц консоли, 12 контейнеров) и публичные материалы Zyxel Nebula
Control Center, UniFi Site Manager, FortiGate Cloud / FortiManager Cloud.

Документ отвечает на вопрос «чего нет в OFME по сравнению с облачными системами
управления сетью» и намеренно отделяет **отсутствующее** от **формально
существующего, но не доезжающего до устройства**.

---

## 1. Краткий вывод

OFME — это **платформа управления парком межсетевых экранов OPNsense** с сильным
уклоном в policy-as-code, аудит и комплаенс. Nebula, UniFi Site Manager и
FortiCloud — это **платформы управления всей сетью**: шлюз + коммутаторы + точки
доступа + клиенты + security-подписки, в SaaS-модели, с мобильными приложениями и
MSP-порталом.

Отсюда главный разрыв — не в качестве отдельных функций, а в **охвате**:

| Слой | OFME | Конкуренты |
|---|---|---|
| Firewall / security gateway | ✅ | ✅ |
| Коммутаторы (порты, PoE, VLAN, LACP, STP) | ❌ | ✅ |
| Wi-Fi (SSID, roaming, guest, captive portal) | ❌ | ✅ |
| Инвентарь клиентов и политики на клиента | ❌ | ✅ |
| Security-подписки (IPS, AV, web/DNS-фильтрация, app control) | ❌ | ✅ |
| Аналитика трафика (NetFlow/sFlow/DPI, top talkers) | ❌ | ✅ |
| IPAM | ❌ | ⚠️/✅ |
| Отчёты и планировщик отчётов | ❌ | ✅ |
| SaaS-доставка, мобильное приложение, push | ❌ | ✅ |
| MSP: white-label, биллинг, self-service | ❌ | ✅ |
| Policy-as-code, approval workflow, GitOps | ✅ | ❌ |
| Комплаенс CIS/ISO/NIST/NIS2/PCI/SOC2 с evidence | ✅ | ⚠️ |
| Hash-chained аудит, подписанные бэкапы | ✅ | ⚠️ |

**Позиционирование.** OFME сегодня конкурентоспособен как «firewall fleet +
governance», но не как «единая панель управления сетью». Чтобы закрыть разрыв,
нужны три волны: (1) довести существующие объекты до устройства и добавить
телеметрию трафика/клиентов, (2) добавить L2/Wi-Fi/security-слой, (3) добавить
SaaS/MSP-обвязку.

---

## 2. Что в OFME уже есть (сильные стороны)

Подтверждено кодом, а не только UI:

| Возможность | Доказательство |
|---|---|
| Инвентарь, discovery, ZTP с PKI, сертификаты, команды, прошивки | `api/v1/endpoints/devices.py`, `ztp.py`, `services/ztp.py`, `services/pki.py` |
| Firewall-правила: CRUD, порядок, конфликты/затенение, diff, preview, deploy | `rules.py`, `services/configuration.py`, `plugin/.../ConfigSync.php` |
| NAT, aliases, VLAN, маршруты, интерфейсы, DHCP, DNS — модели и API | `models/config.py`, `services/networking.py`, `services/configuration.py` |
| Идемпотентный push NAT/VLAN/DHCP/DNS на устройство (`OFME-`, pruning, dry-run) | `services/configuration.py`, `integrations/opnsense/client.py`, `tests/test_config_deploy.py` |
| Policy-as-code: YAML, валидация, симуляция, promotion, drift, Git (GitHub/GitLab/Azure DevOps) | `services/gitops.py`, `services/git_sync.py`, `policies.py`, `git.py` |
| VPN-as-code: WireGuard/IPsec/OpenVPN из `VpnPolicy`, детерминированные ключи, pruning, rollback | `services/vpn_policy.py`, `tests/test_vpn_policy.py` |
| Change-request + four-eyes approval | `models/policy.py`, `ApprovalsPage.tsx` |
| SD-WAN: топологии hub-spoke/mesh/regional, SLA, steering, WireGuard/IPsec/OpenVPN push (сервер + пиры) | `services/sdwan.py`, `sdwan.py` |
| HA/CARP: кластеры, опрос статуса, управляемый failover через `advskew` | `services/ha.py`, `ha.py`, `HaPage.tsx` |
| Бэкапы: gzip XML, AES-256-GCM, SHA-256 + HMAC, verify-before-restore | `services/backup.py` |
| Аудит: глобальная SHA-256 цепочка, integrity endpoint, CSV export | `services/audit.py` |
| Комплаенс: CIS, ISO 27001, NIS2, PCI DSS, SOC 2, evidence | `services/compliance.py` |
| Мультитенантность, 6 ролей + кастомные роли, 79 прав, API-ключи, TOTP, OIDC/LDAP | `rbac/permissions.py`, `users.py`, `services/auth.py` |
| Realtime WebSocket, Prometheus/Grafana/Loki/OTel, K8s/Helm/ArgoCD | `api/ws.py`, `monitoring/`, `deploy/` |

Это ровно те вещи, которых нет у Nebula/UniFi/FortiCloud в сопоставимом виде:
GitOps-процесс, четырёхглазое согласование, доказуемый аудит, комплаенс-отчёты.

---

## 3. Матрица возможностей

Обозначения: ✅ есть, ⚠️ частично/с оговоркой, ❌ нет.

| Возможность | OFME | Nebula | UniFi SM | FortiCloud |
|---|---|---|---|---|
| Управление firewall | ✅ | ✅ | ✅ | ✅ |
| Коммутаторы: порты, PoE, LACP, STP, mirroring | ❌ | ✅ | ✅ | ✅ |
| Wi-Fi: SSID, WPA3, roaming, mesh, radio | ❌ | ✅ | ✅ | ✅ |
| Guest Wi-Fi, captive portal, ваучеры | ❌ | ✅ | ✅ | ✅ |
| RADIUS / 802.1X / MAC-auth | ❌ | ✅ | ✅ | ✅ |
| Инвентарь клиентов (MAC/IP/OS/vendor/трафик) | ❌ | ✅ | ✅ | ⚠️ |
| Блокировка/пауза клиента, лимиты на клиента | ❌ | ✅ | ✅ | ⚠️ |
| IPS/IDS, signature updates | ❌ | ✅ | ✅ | ✅ |
| Anti-malware, web/DNS-фильтрация, app control | ❌ | ✅ | ✅ | ✅ |
| SSL-инспекция, GeoIP, threat feeds | ❌ | ⚠️ | ⚠️ | ✅ |
| Аналитика трафика: NetFlow/sFlow/IPFIX/DPI | ❌ | ⚠️ | ✅ | ✅ |
| QoS / traffic shaping / DSCP | ❌ | ✅ | ✅ | ✅ |
| IPAM: план подсетей, конфликты, свободные адреса | ❌ | ⚠️ | ⚠️ | ❌ |
| DHCP/DNS управление | ✅ Kea + Unbound overrides | ✅ | ✅ | ✅ |
| VLAN | ✅ CRUD + идемпотентный push | ✅ | ✅ | ✅ |
| NAT | ✅ CRUD + идемпотентный push | ✅ | ✅ | ✅ |
| Site-to-site VPN | ✅ WireGuard/IPsec/OpenVPN, policy-as-code + топология | ✅ | ✅ | ✅ |
| Client VPN / VPN-портал пользователя | ❌ | ✅ | ✅ | ✅ |
| SD-WAN | ⚠️ advisory steering | ✅ | ✅ | ✅ |
| Динамическая маршрутизация (OSPF/BGP) | ❌ | ⚠️ | ⚠️ | ✅ |
| IPv6 (адресация, RA, DHCPv6, firewall) | ❌ | ✅ | ✅ | ✅ |
| SNMP (polling/traps/конфиг) | ❌ | ✅ | ✅ | ✅ |
| Syslog forwarding / SIEM | ❌ | ✅ | ✅ | ✅ |
| Packet capture, traceroute, speed test | ❌ | ⚠️ | ✅ | ✅ |
| L2-топология (LLDP/CDP), карта связей | ❌ | ✅ | ✅ | ✅ |
| Firmware: статус, upgrade, reboot | ✅ | ✅ | ✅ | ✅ |
| Staged/ring rollout, baseline версии | ❌ | ✅ | ✅ | ✅ |
| Config backup/restore, версионирование | ✅ | ✅ | ⚠️ | ✅ |
| Шаблоны конфигурации, группы, сайты | ✅ | ✅ | ✅ | ✅ |
| ZTP / zero-touch onboarding | ✅ | ✅ | ✅ | ✅ |
| Policy-as-code / GitOps | ✅ | ❌ | ❌ | ⚠️ |
| Approval workflow (four-eyes) | ✅ | ❌ | ❌ | ❌ |
| Drift detection + remediation | ✅ | ⚠️ | ⚠️ | ⚠️ |
| Комплаенс-фреймворки и evidence | ✅ | ❌ | ❌ | ⚠️ |
| Аудит с защитой целостности | ✅ | ⚠️ | ⚠️ | ⚠️ |
| Мультитенантность / MSP | ✅ | ✅ | ✅ | ✅ |
| White-label, брендирование, кастомный домен | ❌ | ⚠️ | ✅ | ✅ |
| Биллинг, метрирование, подписки | ❌ | ✅ | ⚠️ | ✅ |
| Self-service портал для клиента MSP | ❌ | ⚠️ | ⚠️ | ✅ |
| Отчёты PDF/Excel, планировщик | ❌ | ✅ | ✅ | ✅ |
| Кастомизируемый дашборд | ❌ | ✅ | ✅ | ✅ |
| Мобильное приложение, push | ❌ | ✅ | ✅ | ✅ |
| SSO: OIDC/LDAP | ✅ | ✅ | ✅ | ✅ |
| SSO: SAML 2.0 / SCIM | ❌ | ✅ | ✅ | ✅ |
| Уведомления: email/Slack/webhook | ✅ | ✅ | ✅ | ✅ |
| Уведомления: SMS/Teams/PagerDuty/Telegram | ❌ | ⚠️ | ⚠️ | ✅ |
| Тикетинг (Jira/ServiceNow) | ❌ | ⚠️ | ⚠️ | ✅ |
| REST API + OpenAPI | ✅ | ✅ | ✅ | ✅ |
| Terraform / Ansible / SDK / CLI | ❌ | ❌ | ⚠️ | ⚠️ |
| SaaS-доставка (без своего сервера) | ❌ | ✅ | ✅ | ✅ |
| Доказанный масштаб 10k+ | ⚠️ | ✅ | ✅ | ✅ |

---

## 4. Отсутствующий функционал: подробно

### P0 — без этого сравнение с «cloud network management» не выдерживается

#### C-01. Управление коммутаторами
**Чего нет:** сущности «коммутатор», «порт», «профиль порта»; настройки PoE
(on/off/cycle/schedule/budget), VLAN на порту (access/trunk/native/allowed),
LACP, STP/RSTP, port isolation, mirroring, storm control, LLDP, 802.1X на порту,
port description/label, счётчики ошибок и трафика по порту.
**Доказательство отсутствия:** `models/topology.py` — `Device` не имеет типа
устройства; в `api/v1/endpoints/` нет `switches.py`/`ports.py`; grep по
`poe|802.1x|lldp|lacp` по `backend/app` даёт 0; `integrations/opnsense/client.py`
содержит только firewall-API.
**Почему важно:** это половина ценности Nebula/UniFi — «один экран на всю
площадку». Без коммутаторов OFME управляет только периметром.
**Что нужно:** модель `Switch`/`SwitchPort`/`PortProfile`, адаптер под вендора
(SNMP + REST), UI-таблица портов, массовое применение профилей.

#### C-02. Wi-Fi и гостевая сеть
**Чего нет:** SSID и security-профили (WPA2/WPA3-Enterprise), привязка SSID к
VLAN, radio-профили (каналы, мощность, band steering), mesh, roaming, client
isolation, расписания Wi-Fi, captive portal (splash-страницы, ваучеры, SMS/email
авторизация), RADIUS/802.1X, MAC-auth.
**Доказательство:** grep `ssid|wireless|captive|voucher|radius` по
`backend/app`, `frontend/src`, `plugin/` — 0 совпадений по существу.
**Почему важно:** guest/captive portal — обязательная функция в рознице,
HoReCa, образовании; у всех трёх конкурентов она в базе.
**Что нужно:** либо интеграция с контроллером AP (UniFi/Omada/Nebula), либо
собственный адаптер; отдельно — сервис ваучеров и портал.

#### C-03. Инвентарь клиентов и политики на клиента
**Чего нет:** сущности «клиент» (MAC, IP, hostname, OS/fingerprint, vendor,
точка подключения, RSSI, трафик up/down, uptime, последний визит); действий
«заблокировать», «поставить на паузу», «лимит скорости», «в группу политик»;
истории подключений; уведомлений о новом устройстве.
**Что есть:** только read-only лизинг DHCP по устройству
(`GET /api/v1/sdwan/devices/{id}/dhcp/leases`) и ARP-данные, не сохраняемые как
сущность.
**Почему важно:** «кто в сети и что делает» — центральный экран Nebula/UniFi.
**Что нужно:** сбор ARP/DHCP/LLDP с агента, модель `Client`, агрегация по
MAC, UI-список с фильтрами и действиями.

#### C-04. Security-подписки: IPS/IDS, AV, web/DNS-фильтрация, app control
**Чего нет:** профилей безопасности, применения IPS-политик к VLAN/интерфейсам,
обновления сигнатур, журнала угроз, блокировок по категориям/репутации/GeoIP,
антивируса, SSL-инспекции, app control (по приложениям, а не портам).
**Доказательство:** 0 совпадений `suricata|ips|ids` по существу в
`backend/app`; в `models/enums.py` нет security-перечислений; в консоли нет
страницы Security/Threats.
**Почему важно:** FortiCloud и Nebula продают именно это; OFME управляет
firewall, но не Security Fabric.
**Что нужно:** интеграция с Suricata/ET Open на OPNsense, ingestion событий,
модель `ThreatEvent`/`SecurityProfile`, консоль и алерты. Собственный движок
писать не нужно — нужен оркестратор правил и видимость.

#### C-05. Телеметрия трафика и аналитика
**Чего нет:** байтов/пакетов по интерфейсам, утилизации WAN, top talkers, top
приложений, истории полосы, NetFlow/sFlow/IPFIX-коллектора.
**Доказательство:** `Telemetry.php::interfaces()` отдаёт только `status`, `mac`,
`mtu`, IP; `DeviceTelemetrySnapshot` (`models/metrics.py`) не содержит полей
трафика; `MetricType` не имеет `traffic`/`bandwidth`.
**Почему важно:** дашборд Nebula показывает WAN utilization и клиентов по
потреблению; у OFME дашборд — CPU/RAM/диск. Это заметный визуальный разрыв.
**Что нужно:** сбор `ifconfig`/`pfctl` счётчиков, `MetricType.TRAFFIC`, графики
по интерфейсу и устройству, далее — sFlow-коллектор для top talkers.

#### C-06. QoS / traffic shaping
**Чего нет:** шейперов, лимитов на интерфейс/клиента/SSID, приоритизации по
DSCP, правил «приложение → класс», WAN-оптимизации.
**Доказательство:** grep `qos|shap` — только случайные вхождения, нет моделей
и endpoint'ов.
**Почему важно:** без shaping SD-WAN-steering остаётся рекомендательным, а
«лимит гостям» невозможен.
**Что нужно:** модель `TrafficShaper`/`QosPolicy`, push в OPNsense (ipfw/dummynet),
UI.

#### C-07. IPAM
**Чего нет:** реестра подсетей и адресов на уровне тенанта, обнаружения
пересечений подсетей между сайтами, свободных адресов, привязки адрес → устройство/клиент,
IPv6-плана.
**Что есть:** валидация пула и конфликтов MAC/IP внутри одного DHCP-скоупа
(`services/networking.py`).
**Почему важно:** у UniFi/Nebula IPAM частичный, но у OFME его нет вовсе —
при мультисайтовости это ручная работа.
**Что нужно:** модель `Subnet`/`IpAddress`, авто-наполнение из DHCP/ARP,
проверка пересечений при создании сайта/VLAN.

#### C-08. Отчёты и экспорт
**Чего нет:** PDF/Excel-отчётов, планировщика отчётов, executive summary,
SLA-отчётов по доступности, отчётов по трафику/инцидентам, кастомизируемого
дашборда.
**Что есть:** CSV-экспорт аудита и CSV в некоторых списках.
**Почему важно:** MSP сдаёт клиенту monthly report; без него OFME не
покупают как сервис.
**Что нужно:** шаблоны отчётов (Jinja/WeasyPrint), Celery-задача, доставка
email/S3, UI-планировщик.

### P1 — заметно ограничивает эксплуатацию

#### C-09. SNMP и syslog/SIEM
Нет ни SNMP-поллинга, ни трапов, ни конфигурации SNMP на устройствах, ни
форвардинга syslog/CEF (внутренний G-05). Для NMS/SIEM-интеграций OFME —
чёрный ящик.

#### C-10. L2-топология и LLDP
Карта сайтов (`SiteMap.tsx`) — географическая. Нет карты связей «кто с кем
соединён», LLDP-соседей, визуализации uplink'ов. У конкурентов это базовый экран.

#### C-11. IPv6 и динамическая маршрутизация
`InterfaceCreate.subnet_bits` ограничен 0..32 (только IPv4); нет DHCPv6/RA,
IPv6-правил, OSPF/BGP, BFD. Для операторов и крупных площадок это блокер.

#### C-12. Remote diagnostics
Агент умеет `ping`, `collect_diagnostics`, `reload_firewall`
(`CommandRunner.php`), но нет `traceroute`, `pcap/tcpdump`, DNS-lookup,
speed test, port bounce, WoL, удалённого GUI/SSH устройства.
Конкуренты дают «диагностику из облака» без VPN.

#### C-13. Массовые операции и импорт
Нет bulk-действий по парку (кроме batch-прошивки), нет CSV-импорта устройств,
нет массового применения шаблона/правила/команды, нет «выбрать 50 устройств →
действие».

#### C-14. Firmware lifecycle
Есть статус/upgrade/reboot и batch-задача, но нет baseline-версии по группе,
ring/staged rollout, canary, окон обслуживания, авто-обновления, отката,
собственного репозитория прошивок (внутренний G-18).

#### C-15. Жизненный цикл актива
Нет warranty/EOL/EOS, даты покупки, стоимости, RMA/замены, лицензий и
подписок с истечением. `TenantPlan` — только enum, без метрик и биллинга.

#### C-16. Уведомления и on-call
Каналы: email, Slack, generic webhook (`services/notifications.py`). Нет SMS,
Teams, PagerDuty/Opsgenie, Telegram, push. Нет эскалаций, дежурств, группировки
алертов, окон тишины (maintenance windows), подавления на время работ.

#### C-17. Отчётность по безопасности и уязвимостям
Нет фида CVE/security advisory по прошивкам, оценки posture, проверки
конфигурации на уязвимости beyond compliance-каталогов.

#### C-18. SAML 2.0 и SCIM
OIDC/Entra ID/LDAP есть, SAML — нет (G-03); SCIM-провижининга нет. Крупный
enterprise часто требует именно SAML.

#### C-19. Клиентский VPN и ZTNA
OpenVPN push — только server instance, без пользовательского портала, PKI
пользователей, MFA на VPN, posture-check. Нет ZTNA/SASE-сценария.

#### C-20. Резервный контур управления
Compose — один экземпляр API/воркера; K8s-манифесты есть, но нет
multi-region, реплик БД, автоматического DR-переключения, статус-страницы.

### P2 — экосистема и UX

#### C-21. SaaS-доставка и relay
OFME ставится только к себе (compose/K8s). Нет хостинга, cloud relay,
подключения устройства за NAT без публичного API, «облачного» онбординга по
серийнику, бесплатного тарифа.

#### C-22. Мобильные приложения и push
Нет iOS/Android, push-уведомлений, QR-онбординга, «сканировать серийник».

#### C-23. MSP-обвязка
Нет white-label/брендирования, кастомного домена, self-service портала клиента,
биллинга/метрик использования, партнёрской иерархии, шаблонов договоров/SLA.

#### C-24. Интеграции с тикетингом и ChatOps
Нет Jira/ServiceNow/Zendesk, кроме generic webhook; нет двусторонней
синхронизации инцидентов.

#### C-25. IaC и SDK
Нет Terraform provider, Ansible collection, официальных SDK, CLI. OpenAPI есть,
но генерация клиентов — ручная. Для MSP-автоматизации это важно.

#### C-26. Событийные webhooks (outbound)
Есть webhook-канал уведомлений и входящие Git-webhooks, но нет подписки на
доменные события (`device.offline`, `drift.detected`, `deployment.failed`) с
retry/подписью.

#### C-27. i18n и локализация
Интерфейс только на английском; Nebula — многоязычный. Для EU/регионов это
требование закупки.

#### C-28. Кастомизация дашборда
Виджеты фиксированы; нет drag-and-drop, сохранённых представлений, «мои
устройства», per-role dashboards.

#### C-29. Сравнение конфигураций между устройствами
Есть diff «политика vs устройство» и список бэкапов, но нет diff «устройство A
vs устройство B» и визуального таймлайна изменений конфигурации.

#### C-30. Масштаб и производительность
10k+ не бенчмаркались (G-24); метрики хранятся в PostgreSQL с retention 90 дней,
нет TSDB, шардирования, read-replica. У конкурентов масштаб доказан.

---

## 5. «Есть в UI, но не доезжает до устройства»

Это важнее, чем список отсутствующих страниц: для покупателя такая функция
считается отсутствующей. Из внутреннего реестра пробелов
(`REQUIREMENTS_TRACEABILITY.md`):

| Объект | В UI/API | На устройстве | Gap |
|---|---|---|---|
| NAT | CRUD, apply, dry-run | идемпотентный push в `/api/firewall/d_nat`, `/api/firewall/source_nat` и `/api/firewall/one_to_one`, маркер `OFME-`, pruning | — |
| VLAN | CRUD, apply, dry-run | идемпотентный push в `/api/interfaces/vlan_settings/*`, ключ «интерфейс + tag», pruning | — |
| DHCP-скоупы/резервации | CRUD + валидация, apply, dry-run | Kea DHCPv4: сабнеты и резервации, сопоставление по subnet/MAC, pruning; ISC не программируется | — |
| DNS-записи | CRUD + валидация, apply, dry-run | Unbound host overrides (A/AAAA/MX/TXT), ключ «имя + тип + данные»; CNAME — host alias на управляемый A/AAAA override; PTR/SRV/NS в `skipped` | — |
| WireGuard | сервер + peer | на каждое устройство — отдельная пара ключей и адрес туннеля; сервер + клиентские объекты, связь через relation `peers`; оба конца ребра настраиваются, re-apply = no-op, ушедшие пиры удаляются | — |
| OpenVPN | server instance | CA и сертификат создаются и переиспользуются, push идемпотентен, teardown вместе с туннелем/политикой; нет клиентских инстансов и статуса подключений | §1.1 |
| IPsec | phase1/2 + apply | идемпотентно по `description`, teardown при удалении туннеля; нет HA-последовательности | §1.1 |
| VPN-политика (policy-as-code) | compile/validate + deploy | `VpnPolicyDeployer` исполняет WireGuard/IPsec/OpenVPN из `DeploymentService`, детерминированные ключи из `SECRET_KEY`, pruning, dry-run, снапшот для rollback | — |
| Rollback деплоймента | статус + аудит | снапшот `before/after` для rules/NAT/VLAN/VPN, повторное применение на устройства, teardown VPN-объектов, если политики раньше не было | — |
| Агент | aliases + firewall rules | остальное — через REST OPNsense (NAT/VLAN/DHCP/DNS/VPN) или руками | G-06 |

HA/CARP больше не «только мониторинг»: `HaService.failover` меняет `advskew` на
обоих узлах и применяет VIP (`services/ha.py`, `POST /api/v1/ha/clusters/{id}/failover`);
G-26 перенесён в resolved в трассировочной матрице.

---

## 6. Чего нет у конкурентов, а у OFME есть

Это основа для позиционирования, а не для копирования:

1. **Policy-as-code с Git** — политики как YAML, PR-flow, promotion между
   environment'ами, drift. У Nebula/UniFi/FortiCloud этого нет.
2. **Four-eyes approval** как серверное правило, а не регламент.
3. **Доказуемый аудит** — глобальная hash-цепочка + integrity endpoint.
4. **Комплаенс** — CIS/ISO 27001/NIS2/PCI DSS/SOC 2 с evidence и remediation.
5. **Подписанные шифрованные бэкапы** с verify-before-restore.
6. **ZTP с собственной PKI** и привязкой сертификата к серийнику.
7. **Мультитенантность на уровне приложения** с явным `X-Tenant-Id` для SuperAdmin.
8. **Открытый API 3.1 + self-hosted** — для regulated-клиентов, которым нельзя
   в публичное облако.

---

## 7. Приоритизированный план

Оценка: S ≤ 2 недели, M ≤ 2 месяца, L ≤ 2 квартала, XL — программа.

### Волна 1 — «честный control plane» (0–3 месяца)

| # | Работа | Зачем | Размер |
|---|---|---|---|
| 1 | ~~Довести NAT/VLAN/DHCP/DNS/VPN до устройства (write-методы + идемпотентность)~~ — **сделано**: NAT/VLAN/DHCP/DNS/VPN идемпотентно применяются; VPN-политика исполняется `DeploymentService` (`VpnPolicyDeployer`), топология — через deploy | закрывает 4 «фантомные» функции | — |
| 2 | Счётчики трафика по интерфейсам + `MetricType.TRAFFIC` + графики WAN | самый заметный разрыв в дашборде | M |
| 3 | Инвентарь клиентов из ARP/DHCP/LLDP + блокировка/пауза | базовый экран конкурентов | M |
| 4 | SNMP polling/traps + syslog forwarding | интеграция с NMS/SIEM | M |
| 5 | Bulk-операции и CSV-импорт устройств | эксплуатация парка | S |
| 6 | Отчёты PDF + планировщик | MSP-сценарий | M |
| 7 | Maintenance windows / alert silencing, SMS/Teams/PagerDuty | снижение шума | S |
| 8 | SAML 2.0 + SCIM | enterprise-закупка | M |
| 9 | ~~Реальный rollback деплоймента (снапшот правил)~~ — **сделано**: `snapshot.before/after` для rules/NAT/VLAN/VPN и повторное применение на устройства (G-29 закрыт) | закрывает G-29 | — |

### Волна 2 — «сеть, а не только периметр» (3–9 месяцев)

| # | Работа | Размер |
|---|---|---|
| 10 | Модель коммутатора/портов + PoE/VLAN/LACP/STP + UI | XL |
| 11 | Wi-Fi: SSID, security, VLAN-mapping, radio | XL |
| 12 | Captive portal + ваучеры + guest | L |
| 13 | RADIUS/802.1X | L |
| 14 | IPS/IDS-оркестрация (Suricata) + журнал угроз + алерты | L |
| 15 | Web/DNS-фильтрация и app control (интеграция, не свой движок) | L |
| 16 | QoS/traffic shaping | M |
| 17 | IPAM | M |
| 18 | L2-топология (LLDP) и карта связей | M |
| 19 | IPv6 + OSPF/BGP | L |
| 20 | Remote diagnostics: traceroute, pcap, speed test, WoL | M |

### Волна 3 — «платформа» (9–18 месяцев)

| # | Работа | Размер |
|---|---|---|
| 21 | SaaS-предложение + relay + онбординг по серийнику | XL |
| 22 | Мобильное приложение + push | L |
| 23 | MSP: white-label, self-service, биллинг/метрирование | XL |
| 24 | Terraform provider, Ansible collection, SDK, CLI | L |
| 25 | Событийные webhooks с retry/подписью | S |
| 26 | Staged firmware rollout + baseline + EOL/warranty | M |
| 27 | i18n, кастомный дашборд, diff между устройствами | M |
| 28 | Бенчмарк 10k+ и TSDB для метрик | L |

---

## 8. Что копировать не нужно

- **Собственный антивирус/DPI-движок** — дорого и бессмысленно; нужна
  оркестрация существующих (Suricata, ClamAV, ET Open) и видимость.
- **SASE/ZTNA целиком** — лучше партнёрство/интеграция, чем своя глобальная сеть.
- **Собственный гиперскейл-контроллер Wi-Fi** — на первом этапе достаточно
  адаптера к существующему контроллеру.
- **Биллинг** — на первом этапе достаточно метрик использования и экспорта в
  биллинг-систему партнёра.

---

## 9. Итог одной фразой

OFME уже сильнее конкурентов в **управлении изменениями и доказуемости**
(policy-as-code, approvals, audit, compliance), но уступает им в **широте
охвата** (L2/Wi-Fi/клиенты/security-подписки/аналитика трафика) и в
**способе доставки** (SaaS, мобильные приложения, MSP-обвязка, отчёты).
Ближайший практический шаг — не добавлять новые страницы, а закрыть разрыв
«UI есть — устройство не изменилось» и добавить телеметрию трафика и клиентов:
это даёт максимум воспринимаемой ценности на единицу работы.
