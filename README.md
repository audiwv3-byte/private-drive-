# PRIVATE DRIVE / Euro Baltic Transfer

Source snapshot of the application running on PythonAnywhere, exported 2026-10-28.

## Install and verify

Use Python 3.13 in a new virtual environment:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-runtime.lock.txt
python test_release_validation.py
```

The release checks create temporary databases and use test credentials and mocked providers. They do not send Telegram messages or charge cards. GitHub Actions runs the same checks.

## Configure and run

Copy `.env.example` to `.env` privately. Set BOT_TOKEN and ADMIN_IDS. Bank recipient and account numbers are supplied through PD_BANK_RECIPIENT, PD_PAYSERA_IBAN and PD_SWEDBANK_IBAN; production values are excluded from this repository. The production administrator ID is also excluded and must be configured in ADMIN_IDS.

Run the Telegram bot with `python Euro_Baltic_Transfer.py`. The WSGI entry point is `miniapp_server:application`; adjust the project path in `wsgi.py` for the deployment directory. Only one polling process may run per bot token.

This snapshot contains source and static assets. It contains no customer databases, driver documents, issued invoices or secret environment file. Back up those separately through the hosting account. Database schemas initialize through the application.

## Launch status

- Existing deployment: https://wilsonpark.pythonanywhere.com/
- Driver entry: `?start=driver_taxi_lt`.
- Tips button is placed in normal document flow above contacts.
- Always-on Telegram task was Running at verification.
- Full isolated release checks passed on PythonAnywhere on 2026-10-28.
- Real card payments are not enabled in the application: live key and verified live webhooks are still required.
- Seller address, tax regime and cancellation policy approval require confirmation before activation.
- A real passenger journey inside Telegram is still required; automated tests do not establish that result.

Pushing to GitHub does not deploy or restart the current PythonAnywhere application.
