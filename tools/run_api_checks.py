import os
import json

# Ensure background agents are disabled
os.environ['DRY_RUN'] = 'True'
os.environ['INTRADAY_PATTERN_AGENT_ENABLED'] = 'False'
os.environ['GROK_DASHBOARD_AGENT_ENABLED'] = 'False'
os.environ['OLLAMA_AGENT_ENABLED'] = 'False'
os.environ['TERMINAL_UPDATER_ENABLED'] = 'False'

import importlib.util
import pathlib

dashboard_path = pathlib.Path(__file__).resolve().parents[1] / 'dashboard' / 'app.py'
spec = importlib.util.spec_from_file_location('dashboard_app', str(dashboard_path))
dashboard_app_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard_app_mod)

# Ensure Flask app knows the correct absolute templates/static folders (import-by-path can confuse root paths)
base_dir = pathlib.Path(dashboard_path).parents[0]
dashboard_app_mod.app.template_folder = str(base_dir / 'templates')
dashboard_app_mod.app.static_folder = str(base_dir / 'static')

client = dashboard_app_mod.app.test_client()

endpoints = [
    '/',
    '/api/health',
    '/api/picks',
    '/api/results',
    '/api/history',
    '/api/past-session',
    '/api/paper',
    '/api/accuracy',
    '/api/command-strip',
]

print('Running API checks against dashboard (Flask test client)')
for ep in endpoints:
    try:
        resp = client.get(ep)
        status = resp.status_code
        print(f"\nEndpoint: {ep} -> status {status}")
        content_type = resp.headers.get('Content-Type','')
        if 'application/json' in content_type:
            try:
                payload = resp.get_json()
                print('JSON:', json.dumps(payload, indent=2, default=str)[:2000])
            except Exception as e:
                print('JSON parse error:', e)
        else:
            text = resp.get_data(as_text=True)
            print('Text length:', len(text))
    except Exception as e:
        print(f"Error calling {ep}: {e}")
