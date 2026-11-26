# Harness² Control v0.1.1 — виправлення пакування

Користувач надав screenshot Android: plugin v0.1.0 показує лише skill і кнопку Недоступно. Account source підтвердив: plugin містив portable mcp.json/.mcp.json із tunnelId, але не містив .app.json чи apps declaration. Це відрізнялось від чинного робочого CAD CAE dell-T3500 plugin, який прив'язаний до App asdk_app_6add780305e08191807b14e472712da3.

У тому самому private personal plugin plugins_6b079aff80f8819180d357b313bde00e опубліковано v0.1.1: додано verified App binding в root і compatibility manifests, .app.json з AppID робочого gateway; видалено дубльовані standalone MCP declaration files. Сервер/hosting/tunnel/skill/audience збережені. Release pluginrel_6b079f1d85388191b2d95a43847b6a58. Source readback підтвердив чотири файли та правильний binding; mcp.json/.mcp.json відсутні.

Existing ChatGPT tool cad_list_artifacts через цей App/tunnel успішний після update. Це перевіряє доступність App, але ще не доводить зміну кнопки в Android. У cloud browser аккаунт не авторизований; сторінка користувача недоступна для перевірки. Після оновлення сторінки потрібна версія0.1.1; Android UI і прямий новий harness2 tool call ще не підтверджені. Не видавати source save за доказ UI success.

URL того самого plugin: https://chatgpt.com/plugins/plugins_6b079aff80f8819180d357b313bde00e
Rollback можливий поверненням source попереднього release через guarded update; старий v0.1.0 мав зафіксовану проблему доступності. Новий plugin не створювався; server не перезапускався.
