#!/usr/bin/env python3
"""Install the bounded controller bridge into this host's existing CAD gateway."""
from pathlib import Path
import shutil
import time

root = Path(__file__).resolve().parents[1]
target = Path('/home/user/projects/cad-mcp-stack/server.py')
source = target.read_text()
marker = '# Harness2 bounded controller bridge'
if marker in source:
    print('Bridge already installed; no files changed')
else:
    main = 'if __name__=="__main__":'
    if main not in source:
        raise SystemExit('Unsupported gateway layout; no files changed')
    snippet = ('\n' + marker + '\n' +
               'sys.path.insert(0, ' + repr(str(root / 'integrations')) + ')\n' +
               'from cad_gateway_harness2 import register_tools as register_harness2_tools\n' +
               'register_harness2_tools(mcp)\n\n')
    updated = source.replace(main, snippet + main, 1)
    compile(updated, str(target), 'exec')
    backup = target.with_name('server.py.pre-harness2-' + time.strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(target, backup)
    target.write_text(updated)
    print('Installed; backup:', backup)
