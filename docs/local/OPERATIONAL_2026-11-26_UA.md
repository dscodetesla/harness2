# Harness² — робочі операції замість demo-only

## Виправлення обсягу
Попередній MCP був звужений до demo; це не виконувало запит повної робочої версії. Додано реальні операції без підміни їх демонстрацією. Demo залишено лише для діагностики.

## Функції MCP (10)
status; plan_run; start_run (реальний JobBench refinement); start_judge (той самий profile/namespace, optional bases); report (cached grading report, без inference); start_rf_run (реальний core RF workflow); run_status; results; cancel; start_demo.
Іменовані profiles ollama_local і ollama_glm_cloud. План визначає точні встановлені tasks, k/mode/workers/time. Команди не приймають довільний shell. Cloud запускається лише при allow_cloud=true; повідомляється передавання task inputs/harnesses/trajectories/deliverables. Time cap не є monetary cap.

## Справжній модельний цикл через MCP — PASS
RunID107f99662b4843a2a2a80da78ca4a421: SDK MCP client -> typed CAD bridge -> JSON controller -> worker -> core.schedule.run_domain -> Propose/Probe/Compose -> selection/reflection/library -> results. Model glm-5.3-flash:cloud, synthetic RF task, k1/parallel. При k1 upstream selection тривіальний (єдиний final), окремого selector model call немає.
Фінал: succeeded, exit0, done1/failed0, core errors[], 4 actual executor rollouts, 5 cloud API calls (включно validation retry та reflection). Незалежна перевірка baseline0.5 -> final1.0, всі чотири поля PASS: FSPL108.71dB, Prx-72.21dBm, margin47.79dB, link_viable true. Враховано раніше пропущені2.5dB system loss. EXPERIENCE.md збережено. INV branch безпечно fallback після відхилених imports; execution gate не послаблено до довільного коду.
Цей PASS кваліфікує конкретний synthetic RF workflow, а не всі довільні R&D-задачі чи модель загалом. JobBench plan та маршрути run/judge/report перевірені; реальне модельне оцінювання JobBench на цьому кроці не виконувалось. Локальна3B лишається некваліфікованою.

## Дебаг
Виправлено несумісну назву prompt surface customRF; cloud thinking/output contract; неправильне трактування відхиленої правки як transportfailure. Залишені raw audits невдалих спроб. Немає ручної підстановки правильної правки: приймається лише model-authored solver, AST перевіряє pure numerical code, trusted I/O wrapper незмінний, CPU/RAM/time limits.
До остаточного MCP запуску було16 cloud requests, фінальний мав5. Провайдер не повідомляє USD, тому cost unknown; ledger0 не є доказом безкоштовності.
Results обмежено120KB budget, є manifest/truncation та handling незавершеного JSON. Status повертає scoped qualified_workflows із фактичних terminal job evidence; загальна готовність не виводиться з одного pass.

## Web ChatGPT: виправлений plugin і залишковий host-side UI крок
Той самий private plugin Harness² Control оновлено до0.2.1: https://chatgpt.com/plugins/plugins_6b079aff80f8819180d357b313bde00e. Опис/defaultPrompt/skill тепер про робочі workflow. Збережено AppID asdk_app_6add780305e08191807b14e472712da3 та існуючий secure tunnel, privacy не змінювалась.
Скриншот довів: App у ChatGPT кешує старі6 CAD tools, хоча сервер мав16, тепер21. Перезапуск сервера та зміна plugin zip не оновлює cached App inventory автоматично. Потрібен Refresh самого custom MCP connection у ChatGPT Plugins, далі новий чат. Офіційний порядок: https://developers.openai.com/plugins/deploy/connect-chatgpt#refresh-metadata . У поточному cloud browser аккаунт не авторизований; refresh у користувацькому UI автоматично не виконано. Прямий виклик нової Harness² команди саме з ChatGPT і UI inventory ще потребують підтвердження.
Крок: веб ChatGPT -> Plugins -> підключення CAD CAE dell-T3500 -> Refresh -> перевірити нові harness2_* tools -> новий чат @Harness² Control. Це одноразове оновлення tool metadata, не зміна політики доступу.

## Відтворення та артефакти
Докази docs/local/operational-evidence/, workflow controller harness2/mcp_workflow.py, run script scripts/run_rf_workflow.py. CLI: .venv-mcp/bin/python scripts/run_rf_workflow.py --output runs/new-rf-workflow --seconds 200. Викликає Ollama Cloud із synthetic context. Щоб користуватись MCP — follow tool schemas/plan, зберігати run_id.
Операції працюють на dell-T3500. Source синхронізується в GitHub/X99MG; на X99MG SDK environment слід установити окремо перед запуском MCP. LAB/WorkBuddy залежності цим кроком не встановлювались.

Фінальні перевірки: 118/118 unittest PASS52.137s; combined gateway list21/status/plan PASS; tunnel restarted active. Plugin source0.2.1 saved/readback, release pluginrel_6b07a2ea4b38819186889697a664a90b. ChatGPT metadata Refresh user-side pending; нового прямого harness2 tool call у поточному чаті не заявляємо.
