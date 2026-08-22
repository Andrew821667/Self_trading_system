# Self Trading System

Автономная агентная торговая система — реализация технического задания
`docs/tz/TZ_v2.0_FINAL.md` (версия 2.0 FINAL, утверждено). Наблюдает публичные
источники и рыночные данные, превращает документы в структурированные
события, применяет замороженные спецификации стратегий, проверяет
намерения детерминированным Risk Engine и Safety Plane и исполняет
допустимые действия — с целевой автономностью **A2** (раздел 1.3 ТЗ):
штатный цикл источник → сигнал → риск → исполнение → защита → мониторинг
без подтверждения каждой сделки человеком.

Экономическая цель и границы допуска в production описаны в разделе 1.2 ТЗ:
без подтверждённого преимущества (E-1) система не переходит в боевой контур.

## Статус

Проект находится на стадии **E-1 (Edge Thesis Validation)**, шаг 2 из 6
(раздел 31 ТЗ). Текущий гейт-статус и что уже сделано — в
[`ROADMAP.md`](ROADMAP.md). Ничего в этом репозитории не торгует и не
подключено к брокеру.

## Структура репозитория

```text
docs/tz/            — ТЗ v2.0 FINAL (источник истины)
docs/artifacts/      — учёт замороженных артефактов E-1 (edge thesis, checklist)
ROADMAP.md           — статус стадий/гейтов относительно раздела 3 и 31 ТЗ
config/              — config-as-code (раздел 28 ТЗ): risk rules, strategy
                        specs, execution specs, protective policies,
                        event schemas, checklists, restricted list,
                        factor limits, cash policy, autonomy policy,
                        capital ladder
src/trading_system/
  domain/            — доменные модели раздела 5 ТЗ (EdgeThesis, Hypothesis,
                        PublicSource, StructuredEvent, StrategySpecification,
                        ExecutionSpecification, ProtectivePolicy,
                        TradeIntent, RiskDecision, PolicyEnvelope)
  journal/           — словарь типов событий и конверт события (раздел 20)
  research/          — Stage E3, ещё не начат (см. README в каталоге)
  intelligence/      — Stage E1 Document/Event Intelligence, ещё не начат
  refdata/           — instrument master, ещё не начат
  strategy/          — Strategy Engine, ещё не начат
  risk/              — Risk Engine / Safety Core, ещё не начат
  execution/         — Order Execution, ещё не начат
  safety/            — Compliance Gate, Cash Manager, allocator, ещё не начат
  reporting/         — daily/weekly/annual отчётность, ещё не начат
tests/               — тесты, структура зеркалит src/
```

Каждый ещё не начатый пакет содержит `README.md` с точной ссылкой на разделы
ТЗ и условие открытия гейта — см. также `ROADMAP.md`.

## Governance (кратко, полностью — разделы 0.3, 2.5 ТЗ)

- Решения владельца ограничены пятью пунктами раздела 0.3: подпись вердиктов
  точек принятия решения №0–4, вето на замороженные артефакты, снятие
  `halted`, подпись Policy Envelope, пополнение счёта, чтение отчётов.
- Safety Plane имеет приоритет (раздел 2.5): ни агент, ни оркестратор не
  может отменить отказ, поднять `q_max`, расширить universe, снять
  restricted-статус, изменить потолок капитала или leverage.
- Live-спецификации иммутабельны (раздел 2.4): изменение — это новая версия
  с прохождением гейтов, а не правка на месте.

## Разработка

Требуется Python ≥3.11 и [uv](https://docs.astral.sh/uv/).

```sh
uv sync              # установить зависимости
uv run pytest        # прогнать тесты
uv run ruff check .  # линт
```
