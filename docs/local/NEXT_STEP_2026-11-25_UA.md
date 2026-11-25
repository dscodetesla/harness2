# Harness² — RF qualification та локальний MCP

## Виконано на dell-T3500
Попередній commit d35afba передано Git bundle на X99MG, перевірено git bundle verify, інтегровано fast-forward і опубліковано у dscodetesla/harness2, гілка local/x99mg-integration. Прямий HTTPS push із dell зависає (timeout20 exit124); це не виправлено на рівні транспорту. Надалі коміти цього кроку передаються тим самим перевіреним шляхом.

## RF model qualification
Два локальні inference-виклики llama3.2-harness:3b з context16384; cloud не використовувався. Модель отримала формули та згенерувала чисельну Python-функцію. AST gate обмежує синтаксис і виклики; trusted wrapper виконується з CPU2s, memory256MiB та timeout5s.
Baseline: score0.50 (пропущені втрати). Candidate1: score0.75, числа правильні, Boolean помилково integer1. Один retry: score0.50, Boolean правильний, знак FSPL помилковий. Обидва passed=false. Джерела та summary у runs/rf-local-qualification/ і retry-1/.
Це кваліфікація одного чисельного кандидата, не повний Propose–Probe–Compose. Модель не кваліфікована надійним RF solver.

## Виправлено verifier
RFFPGAAdapter.score тепер вимагає JSON object, точні Boolean та скінченні native int/float. Числові рядки, bool замість числа, NaN/Infinity відхиляються. Попередня bool(value) могла помилково поставити PASS для integer1 або непорожнього рядка. Додані регресії tests/test_rf_schema.py.

## MCP
Додано stdio adapter harness2.mcp_server із п'ятьма командами: status/start_demo/run_status/results/cancel. Лише детермінований demo; максимум один active run, обмеження k/часу, UUID run_id, перевірка PID identity, персистентний job status, bounded log tail, bounded supervisor і cancellation. MCP SDK2.3.0 у окремій .venv-mcp, optional extra [mcp] зафіксований у pyproject.toml. Налаштування: MCP_LOCAL_SETUP.md.
Локальний stdio не є доступним HTTPS endpoint для web ChatGPT. Публічний transport/auth і account plugin/skill ще не встановлені. Model refinement через MCP не рекламується як працездатний.

## Верифікація
Повний unittest набір: 95/95 PASS, 46.763 с. Остаточна protocol/lifecycle перевірка MCP записується нижче.

## Що залишилось
Потрібна модель або workflow, який стабільно створює коректний артефакт; потім повний Harness² цикл. Для web ChatGPT потрібні authenticated HTTPS transport та реальне підключення аккаунта. Локальний MCP можна використовувати вже після protocol PASS за інструкцією MCP_LOCAL_SETUP.md. X99MG отримає код через bundle; окрему .venv-mcp там потрібно встановити перед використанням MCP.

MCP protocol PASS через SDK client: initialize, tools/list=5, structured_content=true, demo succeeded done2 failed0, cancel cancelled. Останні lifecycle-тести 4/4 PASS (3.417 с). Доказ у docs/local/mcp-protocol-evidence.json. Поточний інтегрований прогін із .venv-mcp виконується окремо.

Остаточний інтегрований набір у .venv-mcp: 96/96 tests PASS, 48.885 с. Чисельні кандидати та строгі summary збережені в docs/local/rf-qualification/. git diff --check PASS.
