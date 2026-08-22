# Stage E-1 — event inventory & blind classification (TZ 31, шаг 2 и 4)

Директория названа с дефисом (`stage-E-1`), чтобы не путать с Stage E1
(`src/trading_system/intelligence/`) — это два разных этапа ТЗ.

Слепой протокол реализуется git-тегами, а не отдельным окружением: до тега
`e1-classified-frozen` исходы процедур (завершилась ли, по какой цене
фактически, доходность) нигде в этой директории не появляются — ни в
данных, ни в документах. Схема `InventoryEvent` (см.
`scripts/validate_e1_inventory.py`) физически не содержит полей исхода и
использует `extra="forbid"`: попытка добавить, например, `final_outcome`
через ручной JSON отклоняется валидацией, а не оставляется на дисциплину
исполнителя.

## Фаза A — инвентарь (сейчас)

1. Искать события 2019–2025 четырёх типов (см. `E1EventType` в
   `scripts/validate_e1_inventory.py`):
   `voluntary_or_mandatory_offer`, `squeeze_out_request_95`,
   `forced_buyback`, `buyback_art_75_76`.
2. На каждое найденное событие:
   - сохранить исходные документы **как есть** в
     `documents/<event_id>/<doc_id>.<ext>` + `documents/<event_id>/<doc_id>.meta.json`
     (схема `DocumentRecord`: `url`, `source_type`, `published_at`,
     `retrieved_at`, `sha256`, `legal_use_status`, `local_filename`);
   - добавить строку в `inventory/events.jsonl` (один JSON-объект на
     строку, схема `InventoryEvent`): `event_id`, `event_type`, `issuer`,
     `isin`, `announcement_date` / `submission_date` / `window_start` /
     `window_end`, `procedure_price`, `price_basis`, `guarantor_bank`,
     `acquirer`, `source_document_refs`.
3. `announcement_date` — это «дата события» для правила отсечки при
   классификации ниже; для добровольного/обязательного предложения это
   дата первого раскрытия о направлении предложения, для остальных типов —
   дата первого раскрытия о процедуре.
4. Прогонять `uv run python scripts/validate_e1_inventory.py` по ходу
   сбора — считает покрытие по типам/годам и падает на дубликатах
   `event_id` или событиях без источника.
5. Когда инвентарь считается достаточным (с учётом честного отчёта о
   покрытии, см. ниже) — закоммитить и поставить тег:
   ```sh
   git tag -a e1-inventory-frozen -m "Stage E-1 phase A inventory frozen"
   git push origin e1-inventory-frozen
   ```
   После тега `inventory/events.jsonl` и уже сохранённые документы не
   редактируются задним числом; ошибка — это новая запись/исправление с
   объяснением в коммите, а не переписывание истории.

## Отчёт о покрытии (обязателен, не молчаливый)

`coverage_report()` в `scripts/validate_e1_inventory.py` даёт таблицу
`event_type,year,count`. Если по какому-то типу фактическое покрытие
существенно ниже ожидаемого (владелец ориентировался на ~70% как порог
тревоги), это фиксируется текстом в `coverage_report.md` в этой же
директории — с указанием, какой источник оказался недоступен и почему
(антибот, глубина архива, отсутствие структурированного реестра и т.д.), а
не тихо оставляется как есть.

## Классификация (после `e1-inventory-frozen`)

Для каждого события в `inventory/events.jsonl`:

1. Применить `docs/artifacts/event_checklist_E1_v1.md` **только** по
   документам, у которых `published_at <= announcement_date` этого
   события. Более поздние документы по этому эмитенту в этот момент не
   открываются вообще — включая случайное чтение ленты раскрытия дальше
   даты события.
2. Записать результат в `classification/<event_id>.json` (схема
   `ClassificationRecord`): по каждому признаку П-1…П-9 —
   `satisfied` + `grounds` + `source_doc_refs`; по каждому дисквалификатору
   Д-1…Д-10 — `triggered` + `grounds` + `source_doc_refs`; плюс `a0_satisfied`,
   `verdict`, `verdict_grounds`.
3. `verdict` не принимается на веру: валидатор пересчитывает его по правилу
   D чек-листа (A-0 ∧ ни один Д не сработал ∧ ≥7 из 9 П) и отклоняет запись
   при несовпадении.
4. `uv run python scripts/validate_e1_inventory.py` также проверяет
   утечку: если классификация ссылается на документ с `published_at` позже
   `announcement_date` события — это ошибка, требующая остановки и
   исправления, а не публикации.
5. Когда классифицированы все события инвентаря — тег:
   ```sh
   git tag -a e1-classified-frozen -m "Stage E-1 blind classification frozen"
   git push origin e1-classified-frozen
   ```

## Фаза B (только после тега `e1-classified-frozen`)

Сбор исходов и котировок после событий, затем контрольные прогоны раздела
31 шаг 5 (плацебо, случайные даты, издержки и налог с первого расчёта,
сравнение с безрисковой ставкой) — отдельной сессией/веткой, не смешивая с
файлами этой директории до тега классификации.
