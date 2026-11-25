# dell-T3500: синхронізація Harness² 25.11.2026

Код оновлено fast-forward ccfa485 ->252f109 без локальних конфліктів. Python 3.12.14, пакет Harness² 0.1.0. Перенесено bounded supervisor, metadata preflight, профіль локального Ollama.

Створено llama3.2-harness:3b з наявних локальних ваг за docs/local/Modelfile.harness. Тестовий запит повернув OK за 19.6 с включно із завантаженням. /api/ps підтвердив context_length=16384; preflight підтвердив configured_num_ctx=16384 і loaded_context_length=16384. Cloud-моделі не викликались.

JobBench check з явно заданим локальним профілем: Ready jb/oc, 65 tasks. Dry-run: одна задача data_entry_keyers/task1. Наявний .env не змінювався: фіксований профіль задає scripts/run_bounded_local.py.

Запуск із кореня репозиторію:
```bash
.venv/bin/python scripts/check_local_model.py
.venv/bin/python scripts/run_bounded_local.py --seconds 180 --runs-dir runs/dell-next-trial
```
Другий рядок запускає модельний benchmark. У цьому кроці виконано лише короткий model probe; повний цикл refinement/judge на dell-T3500 ще не кваліфікований. Поточна data_entry задача містить скани, для яких потрібен окремий OCR/vision workflow.

Локальні докази: runs/dell-context-check-20261125/probe.json і preflight.json. Відкат коду — до ccfa485 після перевірки git status; alias видаляється окремо через ollama rm llama3.2-harness:3b, вихідна llama3.2:3b зберігається.

Повний набір після синхронізації: 88/88 tests OK за 45.115 с. git diff --check OK.
