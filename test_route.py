import sys
import traceback
try:
    from backend.app import create_app
    app = create_app()
    client = app.test_client()
    response = client.get('/recuperar-senha')
    print("GET Status:", response.status_code)
    if response.status_code != 200:
        print("GET Data:", response.data.decode('utf-8')[:500])
except Exception as e:
    traceback.print_exc()
