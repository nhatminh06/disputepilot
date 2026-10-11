import os
from urllib.parse import quote

import uvicorn


def main() -> None:
    password = os.environ.get('COMPOSE_POSTGRES_PASSWORD')
    if os.environ.get('DISPUTEPILOT_COMPOSE') != 'true' or not password:
        raise SystemExit('Compose database configuration is required.')
    os.environ['DATABASE_URL'] = (
        f'postgresql://disputepilot:{quote(password, safe="")}@postgres:5432/disputepilot'
    )
    from backend import database
    from backend.main import app, paypal_base_url

    paypal_base_url()
    if (not os.getenv('DEV_MERCHANT_ID')
            or len(os.getenv('DEV_MERCHANT_TOKEN', '')) < 32):
        raise SystemExit('Configure the server-side development merchant credentials.')
    database.initialize()
    uvicorn.run(app, host='0.0.0.0', port=8000)


if __name__ == '__main__':
    main()
