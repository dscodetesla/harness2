# Виправлення контексту Ollama — 25.11.2026

Журнал ollama підтвердив: попередні prompts 17027/17024/10304 токенів обрізались до 2050 при runtime context 4096. Попередня негативна оцінка можливостей моделі за цими запусками була передчасною.

Створено локальний alias llama3.2-harness:3b з існуючих ваг: num_ctx=16384, num_predict=1024, temperature=0. Modelfile збережено у docs/local/Modelfile.harness. Системну службу Ollama та вихідну модель не змінено. Wrapper і конфігурація OpenCode використовують alias/context16384. API /api/ps і журнал підтвердили реальний context16384; у журналі нового запуску truncating input не виявлено.

Додано check_local_model.py: перед запуском відхиляє відсутню/remote/cloud модель, відсутність completion/tools, недостатній явний num_ctx і недостатній runtime context вже завантаженої моделі. Перевірка не генерує текст і не використовує зовнішні endpoints. Wrapper записує evidence у model-preflight.json.

Результат повторної проби: після виправлення з’явився tool_use (читання умови). Два attempts все ще не створили deliverable; sweep завершився base-failed/exit2. Логи runs/context-fixed-20261125. Задача data_entry_keyers/task1 включає рукописні PNG замовлення і таблиці; поточна модель має completion/tools, але не vision. Відсутність vision не доведена як єдина причина невиконання. Повний цикл Propose–Probe–Compose не досягнутий.

Відтворення: ollama create llama3.2-harness:3b -f docs/local/Modelfile.harness; .venv/bin/python scripts/check_local_model.py; .venv/bin/python scripts/run_bounded_local.py --seconds 180 --runs-dir runs/new-context-trial.

Відкат: повернути попередній commit wrapper/config; alias можна окремо видалити ollama rm llama3.2-harness:3b. Базові ваги llama3.2:3b зберігаються.

Наступна кваліфікація має використовувати текстову задачу з однозначно перевірюваним артефактом, або забезпечити OCR/vision для поточної задачі. MCP/plugin не створено; негативний результат benchmark не приховано.

Validation: 88/88 tests OK (40.080 s); git diff --check OK.
