"""PythonAnywhere WSGI entry; isolated QA25 is explicitly opt-in."""
import os
import sys
from pathlib import Path

if os.environ.get("PD_QA25_WSGI") == "1":
    from pd_qa25_wsgi import create_application
    application = create_application()
else:
    PROJECT_DIR = '/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18'
    if PROJECT_DIR not in sys.path:
        sys.path.insert(0, PROJECT_DIR)
    from miniapp_server import application
