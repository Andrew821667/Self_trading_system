# Техническое задание

# Автономная агентная торговая система

**Версия:** 2.0 FINAL  
**Дата:** 21 августа 2026 г.  
**Основание:** консолидированная концепция v4.0 + финальные поправки v4.1 + ревизия ТЗ v1.0 (14 правок — раздел 0.1)  
**Статус:** ФИНАЛЬНОЕ ТЗ, утверждено. Все входные решения владельца приняты и зафиксированы (раздел 0.2). Открытыми остаются только интеграционные приложения (выбор брокера и источников данных) — они заполняются в ходе работ и не блокируют старт.

---

# 0. Назначение документа

Настоящее ТЗ переводит концепцию в реализуемую систему.

ТЗ определяет:
- границы продукта;
- этапы разработки;
- модули;
- контракты между модулями;
- модели данных;
- требования к исследовательскому контуру;
- требования к Document/Event Intelligence;
- Risk Engine и Safety Plane;
- исполнение и автономность;
- требования к журналу;
- отказоустойчивость;
- тесты;
- критерии приёмки;
- порядок допуска к paper/live/A2.

ТЗ **не выбирает конкретного брокера и рынок** до завершения входных решений и E-1. Конкретные API-контракты брокера оформляются отдельным Integration Specification.

## 0.1. Изменения версии 1.1

| № | Правка | Разделы |
|---|---|---|
| 1 | Version pinning экстракции и золотой регрессионный набор документов | 6.5, E1, 22.3 |
| 2 | Неоднозначность определяется структурно + двойная экстракция; confidence не является торговым гейтом; очередь ручного контроля качества | 6.4 |
| 3 | Event replay harness — прогон исторических документов через боевой конвейер | E5, 22.3, 23 |
| 4 | Приёмка A0 дополнена минимумом полных циклов `N_cycles`; календарные дни сами по себе не приёмка для редких семейств | 23 |
| 5 | Закрыта лазейка «обоснованно перспективный E-1»: E0 открывает только вердикт «подтверждён» | 31 |
| 6 | Правило изменённых/переопубликованных документов: `structured_event_superseded`, пересмотр позиции, запрет молчаливой замены | 6.6, 20 |
| 7 | Instrument master: справочник issuer ↔ instruments; неоднозначное разрешение → AMBIGUOUS | E1, 6.4, 26 |
| 8 | Backup & disaster recovery: ежедневный бэкап вне хоста, restore-учение в приёмке P-этапа | 19.3, P0–P3, 22.4, 22.5 |
| 9 | Эволюция схем событий: upcasters при replay, тест на смешанные версии | 20, 22.4 |
| 10 | Приёмка E-1 дополнена оценкой реализуемости по ликвидности | Stage E-1 |
| 11 | Определён источник налоговых цифр в отчётности | 21.3 |
| 12 | Дисциплина времени: UTC, NTP, source lag | 2.6 |
| 13 | `legal_use_status` перечислен и принудительно исполняется ingestion | 6.1 |
| 14 | Версия, основание, настоящий раздел | шапка, 0.1 |

## 0.2. Зафиксированные входные решения (версия 2.0)

Все пять решений владельца по разделу 32 приняты. ТЗ утверждено.

```text
1. Семейство:   E-1 — корпоративные процедуры выкупа/приобретения акций
2. Рынок:       Российская Федерация
3. Комплаенс:   вариант 1 — сектор АПК и все связанные с профессиональной
                деятельностью владельца эмитенты исключены из универсума
                безусловно (дисквалификатор Д-10 чек-листа)
4. Капитал:     до 1 млн ₽ (рабочее допущение; критерий успеха включает
                переиспользуемое ядро и опцион на масштабирование)
5. Расходы:     уровень 0 до положительного вердикта E-1
```

Замороженные артефакты этапа E-1 (шаги 1 и 3 раздела 31 выполнены):

```text
edge_thesis_R0_v1.md       SHA-256 824f35a033c94d1becfbbc8fb444881d140ce96945f5a7d1ea1e561f0090cdcc
event_checklist_E1_v1.md   SHA-256 ed7d8e50f4cbf301ac57e3460109baf8877f7b7e09a4239216350b0c6452580d
```

## 0.3. Роль владельца — исчерпывающий список

Владельцу НЕ требуется квалификация в биржевой торговле, статистике или
программировании. Слепую классификацию событий выполняет LLM-конвейер по
замороженному чек-листу; всю разработку выполняют агенты по настоящему ТЗ.

Владелец делает только следующее, и ничего кроме:

```text
1. Подписывает вердикты точек принятия решения №0–№4
2. Имеет право вето на замороженные артефакты до начала следующего этапа
3. Снимает состояние halted после инцидентов
4. Подписывает и изменяет Policy Envelope (потолок капитала, разрешённые
   рынки, срок действия)
5. Пополняет сегрегированный счёт (вручную; система этого не может)
6. Читает отчёты — дневной по желанию, экономический годовой обязательно
```

Опционально и в любой момент: правка чек-листа как юриста (создаёт новую
версию артефакта). Не является условием ни одного этапа.

---

# 1. Цель системы

## 1.1. Функциональная цель

Создать автономную агентную торговую систему, способную:

1. наблюдать заранее определённые публичные источники и рыночные данные;
2. обнаруживать потенциально значимые ситуации;
3. преобразовывать документы и события в структурированные факты;
4. классифицировать ситуации в заранее допущенные семейства;
5. применять замороженные спецификации стратегий;
6. формировать торговые намерения;
7. проверять их комплаенсом и детерминированным Risk Engine;
8. исполнять допустимые действия;
9. сопровождать позиции по зарегистрированной ProtectivePolicy;
10. измерять результат после издержек и налогов;
11. выявлять деградацию;
12. переводить стратегии в WATCH / QUARANTINE / RETIRED;
13. в A2 работать без подтверждения каждой сделки человеком.

## 1.2. Экономическая цель

Положительный чистый финансовый результат:

```text
gross pnl
− trading costs
− slippage
− financing / FX costs
− taxes
− fixed operating costs
> benchmark при сопоставимом риске
```

При отсутствии подтверждённого преимущества система не должна переходить в производственный live-контур.

## 1.3. Целевая автономность

Первая производственная цель — `A2 Autonomous Execution`.

Человек в A2:
- задаёт Policy Envelope;
- задаёт потолок капитала;
- утверждает Risk Policy;
- ведёт restricted list;
- может остановить систему;
- рассматривает инциденты и экономический обзор.

Человек **не подтверждает штатную сделку** и не принимает дискреционное решение по рынку.

---

# 2. Нефункциональные принципы

## 2.1. Fail-closed

При неизвестности критического состояния:

```text
данные неизвестны
позиция неизвестна
защита неизвестна
Risk Engine недоступен
Policy Envelope истёк
reconciliation mismatch
```

новые входы запрещены.

## 2.2. Воспроизводимость

Любое торговое решение должно быть воспроизводимо по:
- snapshot данных;
- версии документа/источника;
- Strategy Specification;
- Execution Specification;
- Risk Rule Set;
- Policy Envelope;
- structured extraction;
- журналу событий.

LLM при replay повторно не вызывается.

## 2.3. Изоляция LLM

LLM/Research процессы:
- не имеют брокерских ключей;
- не имеют сетевого доступа к Execution Service;
- не имеют права изменять Safety Plane;
- не формируют заявку напрямую.

## 2.4. Immutable live specifications

Live-версия:
- стратегии;
- исполнения;
- ProtectivePolicy;
- чек-листа;
- структурной схемы события

не изменяется без создания новой версии и прохождения требуемых гейтов.

## 2.5. Safety Plane precedence

Решение Safety Plane окончательно.

Агент не может:
- отменить отказ;
- увеличить q_max;
- расширить universe;
- снять restricted instrument;
- изменить capital ceiling;
- поднять leverage;
- изменить hard limits.

## 2.6. Дисциплина времени

- все метки времени в UTC; локальное время — только в отчётах;
- хосты синхронизированы по NTP; рассинхронизация сверх порога → incident;
- для документов различаются `published_at` (часы источника) и `first_seen_at` / `recorded_at` (наши часы); сравнение между ними допускается только с учётом измеренного source lag.

---

# 3. План поставки

## Stage E-1 — Edge Thesis Validation

**До разработки основного ПО.**

Результат:
- `edge_thesis.md`;
- dataset реальных событий;
- frozen checklist;
- blind labels;
- outcome dataset;
- placebo/control;
- письменный verdict.

Приёмка:
- R0 оформлен;
- документирован structural reason;
- определено falsification condition;
- дана оценка capacity;
- история событий собрана без просмотра исходов на этапе разметки;
- оценена реализуемость по ликвидности при капитале владельца;
- verdict подписан владельцем.

Если не пройдено — разработка E0 не начинается.

---

## Stage E0 — Event & Decision Journal Foundation

Результат:
- PostgreSQL;
- append-only journal;
- domain events;
- artifact registry;
- replay;
- configuration registry.

Приёмка:
- состояние тестового портфеля восстанавливается из журнала;
- изменение записанного события невозможно штатным API;
- версии артефактов привязаны к событиям;
- replay идемпотентен.

---

## Stage E1 — Data + Document/Event Intelligence

Результат:
- рыночные данные;
- торговые календари;
- corporate actions;
- public source registry;
- document ingestion;
- document store;
- parser/normalizer;
- structured extractor;
- event classifier;
- instrument master — справочник issuer ↔ instruments (листинги, классы акций, изменения по корпоративным действиям).

Приёмка:
- документ можно повторно получить из Document Store;
- хранится hash и first_seen_at;
- extraction имеет schema version;
- невалидный extraction блокируется;
- событие с отсутствующим public source не попадает в Strategy Engine;
- historical point-in-time dataset воспроизводим;
- golden extraction set собран, эталоны проверены вручную, действующая пара модель/промпт его проходит;
- событие разрешается в конкретные инструменты через instrument master; неоднозначное разрешение → AMBIGUOUS.

---

## Stage E2 — Backtest & Execution Simulation

Результат:
- готовый backtest engine adapter;
- Strategy Specification;
- Execution Specification;
- ProtectivePolicy simulation;
- cost model;
- benchmarks;
- placebo arm.

Приёмка:
- сигнал дня T не исполняется на данных, недоступных в T;
- backtest использует тот же strategy code path;
- execution spec едина для backtest/paper;
- комиссии и slippage включены;
- protective policy моделируется;
- benchmark report генерируется автоматически.

---

## Stage E3 — Research Protocol

Результат:
- hypothesis registry;
- campaign budget;
- R3-A;
- R3-B;
- walk-forward;
- Holdout A;
- sealed Vault B interface;
- R0–R6 gates;
- research report.

Приёмка:
- прогон невозможен без hypothesis_id;
- research protocol фиксируется до просмотра результата;
- замена R3-A ↔ R3-B после результата запрещена;
- holdout access логируется;
- placebo/control проходит весь pipeline;
- экономический gate учитывает fixed costs.

---

## Stage E4 — Safety Core

Результат:
- Compliance Gate;
- Risk Engine;
- q_max envelope;
- factor limits;
- portfolio allocator;
- netting;
- Cash Manager;
- restricted list;
- public source check;
- manipulation guard.

Приёмка:
- property-based tests проходят;
- ни один случайный intent не превышает лимит;
- restricted instrument блокируется раньше market logic;
- отсутствие public_source_basis блокирует event strategy;
- factor limit реально уменьшает q_max;
- opposite intents неттингуются;
- Cash Manager соблюдает reserve;
- агент не способен изменить hard policy через публичный API.

---

## Stage E5 — Realistic Paper

Результат:
- broker paper adapter;
- order state machine lite/full according to integration;
- idempotency;
- startup reconciliation;
- shadow book;
- forward test runner;
- event replay harness — прогон исторических документов через боевой конвейер в ускоренном времени;
- Telegram/reporting.

Приёмка:
- duplicate submit не создаёт вторую заявку;
- UNKNOWN блокирует повторный action по инструменту;
- research/backtest vs runner signal divergence = 0 в тестовом сценарии;
- forward test frozen before start;
- промежуточное изменение rule запрещено;
- daily report формируется;
- event replay harness: исторические события проходят полный цикл документ → событие → сигнал → paper-сделка с нулевым расхождением против research-контура при закреплённых версиях экстракции.

---

## Stage P0–P3 — Production Hardening

Результат:
- separate processes;
- Ed25519;
- nonce cache;
- full reconciliation;
- secret isolation;
- segregated account support;
- protective policy live verification;
- broker-side limits;
- dual computation;
- dead-man;
- owner absence procedure;
- chaos tests;
- Health Monitor;
- drift monitor.

Приёмка:
- определена матрица chaos scenarios;
- каждый critical scenario протестирован;
- Risk/Execution crash recovery доказан;
- dual computation mismatch переводит halted;
- исчезновение защитной заявки обнаруживается;
- owner absence procedure исполняется на стенде;
- LLM outage не останавливает trading loop;
- restore-учение выполнено: журнал восстановлен из бэкапа на чистом хосте, состояние выведено replay и сверено с брокером.

---

## Stage A1 — Live Assisted

Результат:
- реальный micro account;
- operational veto;
- live metrics;
- operator veto shadow evaluation.

Приёмка:
- per-trade chain воспроизводима;
- ноль hard limit violations;
- ноль unresolved reconciliation mismatch;
- все позиции имеют действующую ProtectivePolicy;
- manual veto классифицирован кодами;
- дискреционное вмешательство измеряется.

---

## Stage A2 — Autonomous Execution

Результат:
- per-trade confirmation disabled;
- Policy Envelope;
- fully automatic source monitoring → signal → risk → execution → protection → monitoring;
- autonomous downgrade.

Приёмка:
- A2 gate полностью пройден;
- Decision Plane outage не приводит к потере защиты;
- LLM outage не блокирует действующие стратегии;
- ambiguous event → skip;
- expired policy → A1/no_new_entries;
- hard limit breach → automatic downgrade;
- у владельца остаётся kill switch.

---

# 4. Архитектура процессов

## 4.1. Experimental Track

Один process / monolith modular:

```text
research
data
intelligence
strategy
risk
execution-paper
journal
reports
```

Запрещается преждевременное дробление на microservices.

## 4.2. Production Track

Обязательные процессы:

```text
market-data-service
document-intelligence-service
strategy-runner
risk-service
execution-service
supervisor
reconciliation-service
health-monitor
reporting-service
research-service
```

LLM доступен только:

```text
document-intelligence-service
research-service
reporting-service
```

Execution/risk LLM не вызывают.

---

# 5. Основные доменные сущности

## 5.1. EdgeThesis

```yaml
edge_thesis_id:
version:
family:
mechanism:
structural_reason: C1|C2|C3|C4
counterparty_class:
counterparty_motivation:
capacity_estimate:
falsification_condition:
expected_lifetime:
death_conditions:
approved_at:
status:
```

## 5.2. Hypothesis

```yaml
hypothesis_id:
campaign_id:
edge_thesis_id:
research_protocol: R3-A|R3-B
strategy_spec_id:
execution_spec_id:
protective_policy_id:
universe:
timeframe:
parameter_space:
planned_trials:
economic_gate:
created_by:
created_at:
```

## 5.3. PublicSource

```yaml
source_id:
source_type:
issuer_id:
url:
external_registry_id:
published_at:
first_seen_at:
content_hash:
storage_uri:
version:
legal_use_status:
```

## 5.4. StructuredEvent

```yaml
event_id:
source_id:
event_family:
schema_version:
event_time:
effective_time:
issuer_id:
facts:
extraction_model:
prompt_version:
validation_status:
confidence:
public_source_basis:
```

## 5.5. StrategySpecification

```yaml
strategy_id:
version:
edge_thesis_id:
event_family:
entry_rules:
exit_rules:
disqualifiers:
required_public_sources:
factor_profile:
capacity_policy:
execution_spec_id:
protective_policy_id:
spec_hash:
```

## 5.6. ExecutionSpecification

```yaml
execution_spec_id:
version:
entry_order_type:
limit_price_formula:
order_ttl:
min_order_lifetime:
entry_window:
partial_fill_policy:
repricing_policy:
max_reprice_attempts:
chase_price_allowed:
planned_exit_policy:
emergency_exit_policy:
slippage_model:
hash:
```

## 5.7. ProtectivePolicy

```yaml
protective_policy_id:
type:
parameters:
broker_side_required:
fallback_policy:
max_unprotected_seconds:
liquidity_window:
hash:
```

## 5.8. TradeIntent

```yaml
intent_id:
strategy_id:
event_id:
instrument:
side:
requested_quantity:
signal_price:
stop_or_protection_reference:
factor_exposures:
public_source_basis:
created_at:
```

## 5.9. RiskDecision

```yaml
decision_id:
intent_id:
approved:
max_allowed_quantity:
rejection_rule_id:
rule_set_version:
policy_envelope_version:
inputs_snapshot:
created_at:
```

## 5.10. PolicyEnvelope

```yaml
policy_version:
autonomy_level:
allowed_markets:
allowed_asset_classes:
approved_strategy_scope:
owner_capital_ceiling:
account_id:
max_leverage:
portfolio_risk_limits:
factor_limits:
capital_scaling_ladder:
cash_management:
restricted_list_version:
owner_absence_timeout_days:
valid_from:
expires_at:
emergency_contacts:
signature:
```

---

# 6. Document & Event Intelligence

## 6.1. Source Registry

Функции:
- регистрирует допустимые публичные источники;
- задаёт polling method;
- задаёт SLA;
- задаёт parser;
- задаёт юридический статус источника (`allowed | attribution_required | metadata_only | prohibited`) — ingestion исполняет его принудительно;
- связывает источник с event family.

API:

```python
register_source(source_config)
disable_source(source_id)
get_source(source_id)
list_sources(event_family=None)
```

## 6.2. Ingestion

Каждый ingestion создаёт immutable artifact.

Система обязана различать:

```text
published_at
first_seen_at
downloaded_at
effective_at
```

Для backtest используется только информация, доступная на соответствующий момент.

## 6.3. Extraction

LLM output проходит строгую Pydantic/JSON-schema validation.

Пример:

```python
class CorporateEvent(BaseModel):
    issuer_id: str
    event_type: Literal["offer","reorganization","charter_change"]
    decision_date: datetime
    effective_date: datetime | None
    material_terms: dict
    source_refs: list[str]
```

Validation failure:

```text
event.status = INVALID
trade usage = forbidden
```

## 6.4. Ambiguity

Неоднозначность определяется структурно, а не самооценкой модели:

```text
missing required field
OR conflicting sources
OR расхождение двух независимых прогонов экстракции
   (другая модель либо другой промпт)
OR событие не разрешается однозначно в инструменты (instrument master)
→ AMBIGUOUS
→ no trade
→ notification
```

`confidence` записывается в событие, но торговым гейтом не является: самооценка уверенности LLM не калибрована.

Агент не достраивает юридически существенный факт предположением.

Контроль качества: в A1 все AMBIGUOUS и случайная выборка VALID (`extraction_qc_sample_rate`, по умолчанию 10%) проходят ручную проверку. Постоянная разметка выборки — ground truth для метрики качества экстракции; без неё `extraction_invalid_rate` слепа.

## 6.5. Version pinning и золотой набор

Экстракция — часть исполняемой системы; к ней применяется тот же принцип неизменяемости, что к live-спецификациям:

- `extraction_model` и `prompt_version` замораживаются на версию стратегии; live-конвейер привязан к конкретной паре версий;
- **золотой регрессионный набор**: исторические документы с проверенными вручную эталонными экстракциями; прогоняется при любой смене модели, промпта или схемы;
- в live допускаются только версии, прошедшие золотой набор без деградации;
- deprecation модели провайдером = новая версия конвейера + полный прогон золотого набора; молчаливое обновление запрещено;
- результаты прогонов хранятся в artifact registry.

## 6.6. Изменённые и повторно опубликованные документы

Источники публикуют поправки к ранее раскрытым сообщениям. Правило:

```text
новая версия документа (document_versions)
→ повторная экстракция
→ существенное изменение фактов?
    да → structured_event_superseded
        → пересмотр позиций, открытых по событию (в рамках ProtectivePolicy)
        → notification владельцу
    нет → фиксация новой версии без действий
```

Молчаливая замена события запрещена: сделка, основанная на устаревшей редакции документа, — инцидент, а не допущение.

---

# 7. Research Engine

## 7.1. Hypothesis Registry

Любой research run требует:

```text
hypothesis_id
campaign_id
dataset_version
strategy_version
execution_version
research_protocol
```

## 7.2. Budget

Каждая кампания имеет:

```yaml
max_trials:
max_llm_cost:
max_compute_hours:
max_holdout_access:
expires_at:
```

Превышение → research stopped.

## 7.3. R3-A

Метрики:
- N_eff;
- Sharpe;
- DSR;
- PBO;
- drawdown;
- CVaR;
- walk-forward stability;
- cost stress.

## 7.4. R3-B

Метрики:
- total eligible events;
- selected events;
- control events;
- mean/median event return;
- downside;
- exact/bootstrap CI;
- permutation p-value where valid;
- concentration ratio;
- result by subperiod;
- capacity;
- holding time;
- liquidity realizability.

## 7.5. Leakage tests

Обязательные:
- look-ahead;
- shuffled outcome;
- random dates;
- placebo event selection;
- source timestamp audit.

---

# 8. Backtest

## 8.1. Требования

Не писать собственный engine в первой версии.

Adapter:

```python
run(strategy_spec, execution_spec, data_snapshot, cost_model) -> BacktestResult
```

## 8.2. Event backtest

Для event-driven стратегии движок получает:

```text
source first_seen_at
structured event
market state known at event time
```

и запрещает использование более поздней редакции документа.

## 8.3. Fill simulation

Минимально:
- next-bar/next-session;
- spread;
- slippage;
- TTL;
- partial fill approximation;
- no chase;
- volume participation cap;
- market halt;
- delisting/corporate action.

---

# 9. Risk Engine

## 9.1. API

```python
def evaluate(
    state: PortfolioState,
    intent: TradeIntent,
    rules: RuleSet,
    policy: PolicyEnvelope
) -> RiskDecision:
    ...
```

## 9.2. Проверки

Порядок фиксирован:

```text
mode
restricted list
blackout
public source basis
manipulation guard
allowed asset/market
data freshness
position known
ProtectivePolicy valid
order type
per-trade risk
capacity
instrument cluster
factor exposure
strategy budget
portfolio budget
open position count
daily/weekly/monthly loss
HWM drawdown
capital stage
martingale/averaging prohibition
min viable quantity
```

## 9.3. Dual compute

В P0+:
- stream-derived computation;
- broker-state computation.

Сравниваются:

```text
equity
daily pnl
drawdown
gross exposure
used capital
```

Mismatch → halted.

---

# 10. Portfolio Allocator

Первая версия только deterministic.

Input:

```text
approved strategies
strategy health state
strategy correlation matrix
factor exposures
portfolio risk budget
```

Output:

```text
strategy risk budgets
```

Правила:
- equal risk baseline;
- WATCH cannot increase;
- QUARANTINE = 0 new budget;
- max strategy budget;
- max family budget;
- max factor budget.

---

# 11. Cash Manager

## 11.1. Input

- cash;
- settlements;
- pending orders;
- expected commissions/tax reserve;
- opportunity reserve;
- Policy Envelope.

## 11.2. Output

```text
liquid_reserve
sweep_amount
eligible_cash_instrument
```

## 11.3. Запреты

- leverage;
- illiquid cash instruments;
- maturity beyond policy;
- forced sale to fund normal opportunity;
- use of protected reserve.

---

# 12. Compliance Gate

Input:

```text
instrument
issuer
public_source_basis
restricted list
blackout
owner policy
```

Output:

```text
PASS / REJECT
rule_id
```

Никакой LLM в gate.

---

# 13. Manipulation Guard

Минимум:
- min order lifetime;
- max reprice count;
- max cancel rate;
- max own order share;
- opposite-order prohibition;
- max daily volume participation;
- closing/fixing restrictions.

Параметры зависят от рынка и брокера и заполняются в Integration Spec.

---

# 14. Order Execution

## 14.1. Production states

```text
DRAFT
RISK_APPROVED
SUBMITTED
ACKED
PARTIALLY_FILLED
FILLED
REJECTED
CANCELLED
EXPIRED
UNKNOWN
```

## 14.2. Idempotency

```text
client_order_id = hash(intent_id + execution_attempt)
```

Повтор после timeout использует тот же broker-supported idempotency identifier, если API позволяет; иначе применяется локальный reconciliation-before-retry.

## 14.3. Protection

После fill:

```text
ProtectivePolicy activated
→ broker verification
→ position becomes PROTECTED
```

Пока позиция не `PROTECTED`:

```text
new entry = forbidden
incident timer = active
```

---

# 15. Reconciliation

Периодичность задаётся broker integration.

Сравнение:
- positions;
- average prices;
- open orders;
- protective orders;
- fills;
- cash;
- buying power.

Mismatch:

```text
halted
incident
notify
no automatic flattening
```

---

# 16. Health Monitor

## 16.1. Strategy states

```text
ACTIVE
WATCH
QUARANTINE
REALISTIC_PAPER
RETIRED
```

## 16.2. Inputs

- P&L;
- drawdown;
- trade frequency;
- holding period;
- slippage;
- fill ratio;
- factor exposures;
- input feature drift;
- source drift;
- event family frequency.

## 16.3. Drift

PSI / KS or another approved metric.

Thresholds belong to strategy health spec and are frozen before A1.

---

# 17. Autonomy Orchestrator

Orchestrator does not decide market direction.

Responsibilities:

```text
schedule cycles
check system state
start source ingestion
start signal generation
submit intents
collect risk decisions
execute approved actions
check protection
trigger reports
downgrade on incident
```

Orchestrator cannot:
- change rules;
- change strategy;
- change q_max;
- change capital ceiling.

---

# 18. Owner / Supervisor Interface

Telegram/Web UI minimum:

```text
system mode
autonomy level
capital stage
current equity / HWM
open positions
ProtectivePolicy status
risk usage
strategy states
source health
incidents
reconciliation status
policy expiry
kill switch
```

A1 дополнительно:

```text
operational approve/veto
veto reason code
```

A2 per-trade approval UI disabled.

---

# 19. Security

## 19.1. Secrets

- no secrets in LLM process;
- live keys in execution-only secret scope;
- withdrawal disabled;
- IP allowlist if possible;
- separate paper/live accounts.

## 19.2. Generated code sandbox

Mandatory:
- no network;
- temp fs only;
- no env;
- CPU/memory timeout;
- import whitelist;
- block eval/exec/subprocess/socket;
- output typed signal only.

Sandbox escape test required.

## 19.3. Backup & disaster recovery

- ежедневный бэкап вне хоста: event journal, document store, artifact registry, configuration registry;
- retention документов — согласно `legal_use_status` источника;
- restore-учение входит в приёмку P-этапа: журнал восстанавливается на чистом хосте, состояние выводится replay и сверяется с брокером;
- целевые RPO ≤ 24 ч, RTO ≤ 1 торговый день; уточняются в APPENDIX-ACCEPTANCE.

---

# 20. Event Journal

Минимальные event types:

```text
source_polled
source_document_seen
source_document_amended
document_stored
document_parsed
structured_event_created
structured_event_invalid
structured_event_superseded
signal_generated
intent_created
intents_netted
compliance_checked
manipulation_checked
risk_evaluated
approval_issued
order_submitted
order_acked
order_filled
order_cancelled
protective_policy_activated
protective_policy_failed
position_opened
position_updated
position_closed
reconciliation_performed
reconciliation_mismatch
strategy_state_changed
factor_limit_hit
cash_sweep_performed
policy_envelope_expired
autonomy_level_changed
incident_raised
```

Каждое событие:

```yaml
event_id:
event_type:
occurred_at:
recorded_at:
correlation_id:
causation_id:
actor:
payload:
artifact_refs:
schema_version:
```

Эволюция схем: записанные события никогда не переписываются. Изменение схемы = новая `schema_version` + upcaster, применяемый при replay. Replay-тест обязан включать лог со смешанными версиями схем.

---

# 21. Reporting

## 21.1. Daily

- equity;
- realized/unrealized;
- positions;
- protection status;
- risk usage;
- source health;
- events detected;
- signals;
- rejects;
- fills;
- slippage;
- strategy state;
- incidents.

## 21.2. Weekly

- strategy health;
- benchmark comparison;
- factor exposure;
- veto value;
- drift;
- autonomy metrics.

## 21.3. Annual economic report

- net after trading costs;
- net after tax;
- net after fixed costs;
- benchmark;
- time/cost of operation;
- economic continuation verdict;
- источник налоговых цифр: ручной ввод либо простой детерминированный `tax_estimator`; версия налоговых правил фиксируется в отчёте.

---

# 22. Testing Strategy

## 22.1. Unit

Все чистые функции.

## 22.2. Property-based

Risk Engine, allocator, cash manager, netting.

Примеры инвариантов:

```text
approved q <= q_max
factor exposure <= policy max
cash reserve never below minimum
QUARANTINE gets zero new risk
restricted always rejects
```

## 22.3. Integration

- market data;
- document ingestion;
- parser/extraction;
- strategy;
- risk;
- paper broker;
- golden extraction set (регрессия);
- event replay harness.

## 22.4. Replay

Исторический event log → identical state.

Обязательные сценарии: лог со смешанными `schema_version` (через upcasters); лог, восстановленный из бэкапа.

## 22.5. Chaos

- broker unavailable;
- delayed data;
- missing protective order;
- duplicate fill;
- stale document;
- LLM unavailable;
- DB restart;
- journal restore from backup;
- network partition;
- clock jump;
- owner unavailable;
- expired policy.

---

# 23. Acceptance Criteria by autonomy level

## A0

- 60 trading days paper;
- минимум `N_cycles` полных циклов документ → событие → сигнал → сделка — реальных либо через event replay harness; значение фиксируется в APPENDIX-ACCEPTANCE. Календарные дни сами по себе не являются приёмкой для редких событийных семейств;
- no duplicate orders;
- no unresolved mismatch;
- full audit chain;
- forward test frozen;
- source/document pipeline stable.

## A1

- segregated micro account;
- all protection valid;
- zero hard violation;
- operational veto only;
- owner absence drill passed.

## A2

- per-trade human confirmation disabled;
- 100% routine cycle automatic;
- no LLM dependency in live loop;
- ambiguous event skip;
- policy expiry downgrade works;
- incident downgrade works;
- protection survives process death;
- reconciliation independent;
- owner intervention rate below threshold defined in full acceptance test.

---

# 24. Performance requirements

Так как HFT не строится:

- daily/event strategies priority;
- decision latency target определяется семейством;
- для document-driven event первой версии достаточно minute-level/hour-level SLA, если R0 не требует быстрее;
- ingestion SLA указывается per source;
- trading API operations должны укладываться в broker rate limits.

Не оптимизировать latency без доказанной экономической необходимости.

---

# 25. Observability

Metrics:

```text
source_poll_success
source_lag_seconds
document_parse_failure
extraction_invalid_rate
event_ambiguity_rate
signal_count
risk_reject_count
order_error_rate
reconciliation_mismatch
protective_policy_failure
strategy_state
daily_loss
drawdown
factor_exposure
cash_reserve
llm_unavailable
```

Critical alerts:
- protective policy missing;
- reconciliation mismatch;
- risk service down;
- policy expired;
- owner absence trigger;
- factor hard breach;
- broker connection loss.

---

# 26. Database logical schemas

```text
research:
  edge_theses
  hypotheses
  campaigns
  runs
  holdout_access
  research_metrics

intelligence:
  sources
  documents
  document_versions
  extractions
  structured_events

refdata:
  issuers
  instruments
  issuer_instrument_map

trading:
  strategies
  strategy_versions
  execution_specs
  protective_policies
  intents
  risk_decisions
  orders
  fills
  positions

safety:
  rule_sets
  policy_envelopes
  restricted_list_versions
  factor_limits
  approvals
  used_nonces
  incidents

events:
  event_log

reporting:
  daily_snapshots
  benchmark_snapshots
  strategy_health
  economics
```

---

# 27. API boundaries

## Strategy

```python
generate_signal(context: StrategyContext) -> Signal | None
```

## Risk

```python
evaluate(state, intent, rules, policy) -> RiskDecision
```

## Execution

```python
submit(approved_order) -> OrderAck
cancel(order_id)
status(order_id)
```

## Document Intelligence

```python
ingest(source_id) -> list[DocumentRef]
extract(document_ref, schema_id) -> StructuredEvent
validate(event) -> ValidationResult
```

## Protective Policy

```python
activate(position, policy) -> ProtectionState
verify(position) -> ProtectionState
```

## Health

```python
evaluate_strategy(strategy_id, observations) -> HealthDecision
```

---

# 28. Configuration as code

Version-controlled:

```text
risk rules
strategy specs
execution specs
protective policies
event schemas
checklists
restricted list
factor limits
cash policy
autonomy policy
capital ladder
```

Каждая активация:

```text
version
hash
effective_from
approved_by
```

---

# 29. Definition of Done for each feature

Фича считается законченной только если:

1. есть domain model;
2. есть implementation;
3. есть unit tests;
4. есть failure test;
5. есть journal event;
6. есть metric/logging;
7. есть replay semantics;
8. есть configuration/versioning if behavior changes money;
9. документация содержит acceptance example.

---

# 30. Входные решения до кодирования интеграций

Обязательны:

1. первое семейство E-1…E-4;
2. рынок;
3. брокер;
4. account type;
5. automated trading terms;
6. public document sources;
7. historical data source;
8. corporate action source;
9. benchmark set;
10. initial capital ceiling;
11. cash reserve;
12. policy expiry;
13. protective policy types supported by broker;
14. market-specific manipulation guard values;
15. restricted sector policy;
16. tax/FX status.

---

# 31. Порядок начала работы

## Шаг 1 — ВЫПОЛНЕН

`edge_thesis_R0_v1.md` создан и заморожен (хеш в разделе 0.2).

## Шаг 2 — в работе

Собрать event inventory по семейству E-1 за 2019–2025: добровольные и
обязательные предложения, требования о выкупе при >95%, принудительные
выкупы, выкупы по ст. 75–76 (реорганизации, делистинги, крупные сделки).
Источники: центр раскрытия корпоративной информации, Банк России,
Московская биржа; котировки — ISS API (уровень расходов 0). Исходы
складываются в отдельный файл и не открываются до шага 5.

## Шаг 3 — ВЫПОЛНЕН (досрочно, что строже плана)

`event_checklist_E1_v1.md` заморожен до сбора истории (хеш в разделе 0.2).

## Шаг 4

Blind historical classification — выполняется LLM-конвейером по
замороженному чек-листу, по документам на дату события. Участие владельца
не требуется.

## Шаг 5

Outcome reveal + controls: плацебо-прогон, случайные даты, издержки и
налог с первого расчёта, сравнение с безрисковой ставкой.

## Шаг 6

Вердикт E-1.

**E0 открывает только вердикт «подтверждён».**

Вердикт «требует уточнения» разрешает один цикл переформулировки тезиса внутри той же кампании с наследованием счётчика испытаний — это продолжение E-1, а не начало E0. Вердикт «не подтверждён» закрывает семейство; следующее семейство начинает E-1 заново.

---

# 32. Приёмка ТЗ

Все пять решений владельца зафиксированы (раздел 0.2). **ТЗ утверждено и является финальным.**

Дальнейшие изменения настоящего документа допускаются только по итогам точек принятия решения либо по инцидентам — новых версий «на подумать» не существует.

Интеграционные детали брокера и источников оформляются приложениями:

```text
APPENDIX-BROKER
APPENDIX-DATA
APPENDIX-SOURCES
APPENDIX-RISK-PARAMETERS
APPENDIX-ACCEPTANCE
```

---

# 33. Итоговая архитектура

```text
PUBLIC SOURCES ─────┐
                    ├→ Document/Event Intelligence
MARKET DATA ────────┘             ↓
                           Structured Event
                                  ↓
                           Strategy Engine
                                  ↓
                             Trade Intent
                                  ↓
                      Netting / Compliance
                                  ↓
                            Risk Engine
                                  ↓
                     [0 .. max_allowed_q]
                                  ↓
                          Execution Gate
                                  ↓
                               Broker
                                  ↓
                        ProtectivePolicy
                                  ↓
                        Reconciliation
                                  ↓
                         Health Monitor
                                  ↓
                 ACTIVE / WATCH / QUARANTINE

        Safety Plane окружает весь путь и не управляется агентами.
```

**Основная производственная цель:** A2 — автономный штатный цикл внутри заранее одобренных семейств преимуществ и Policy Envelope.

**Первый следующий артефакт разработки:** `edge_thesis_R0_v1.md`, а не новая версия архитектуры.
