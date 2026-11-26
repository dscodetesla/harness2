# Harness² Control — приватний плагін ChatGPT

Дата: 26.11.2026. Host: dell-T3500.

## Розгорнуто
П'ять команд Harness² додано до чинного Engineering CAD Suite gateway через SDK-independent JSON subprocess bridge. Existing11 tools збережені; combined tools/list=16. Той самий OpenAI Secure MCP Tunnel cad-cae-dell-t3500 використовується для приватного outbound доступу. Нові inbound firewall/public ports не відкривались. Секрети tunnel не змінювались і не включені в пакет.

Створено private personal plugin Harness² Control v0.1.0:
https://chatgpt.com/plugins/plugins_6b079aff80f8819180d357b313bde00e
ID plugins_6b079aff80f8819180d357b313bde00e, release pluginrel_6b079b009fbc8191b382d4dbf4c0578f.
Пакет у plugin/harness2-control: plugin.json, mcp.json з verified tunnelId, skill harness2-control. Пакет збережено та перечитано через Plugin Creator. Плагін використовує спільний gateway, який також оголошує CAD/camera tools; скіл керує лише harness2 tools для задач Harness².

## Перевірки
- 104/104 unittest PASS,51.777s, .venv-mcp.
- HTTP bearer transport: missing/wrong token401, authenticated MCP lifecycle PASS. Optional loopback HTTP implementation tested, але не запущений як production service; первинний маршрут використовує secure tunnel + stdio.
- Combined SDK1.30 gateway protocol: initialize/list16, status, start_demo -> succeeded done2 failed0, results, cancel active -> cancelled. Доказ docs/local/web-gateway-protocol.json.
- Tunnel doctor з ephemeral health listener PASS; live readyz=ready, successful control-plane poll timestamp nonzero. User service active, linger=yes.
- Після restart із цього ChatGPT успішно викликано existing cad_list_artifacts через той самий tunnel; це підтверджує маршрут і збереження CAD-команд.
- У поточному turn нові harness2 tool names ще не з'явились у ChatGPT tool registry. Прямий ChatGPT-виклик нової Harness² команди НЕ підтверджено. Створення plugin не прирівнюється до його вибору/підключення в чаті. Кінцевий користувацький крок: відкрити plugin link, підключити/додати до чату, запитати 'Перевір стан Harness²', потім 'Запусти demo k=1'.

## Доступні операції
harness2_status, harness2_start_demo, harness2_run_status, harness2_results, harness2_cancel. Лише bounded deterministic demo, один active run, k1/2,seconds1..120; model_refinement_qualified=false. Модельні RF-кандидати раніше failed, їх не рекламуємо успішним повним циклом.

## Deployment та відкат
Live gateway: /home/user/projects/cad-mcp-stack/server.py; backup server.py.pre-harness2-20261126-043403. Ідемпотентна установка: .venv-mcp/bin/python scripts/install_cad_bridge.py. User service cad-cae-tunnel restarted після successful combined protocol.
Rollback: відновити зазначений backup gateway і restart cad-cae-tunnel; це прибере Harness² із gateway, зберігаючи попередній набір. Плагін після rollback не матиме Harness² tools. Запущені demo завершити перед відкатом.

## Залишилось
Вибір/підключення plugin у ChatGPT та перший прямий Harness² tool call. Окремо залишається кваліфікація надійного model-backed Harness² workflow; вона не блокує користування demo/status/cancel.
