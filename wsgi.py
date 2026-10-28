"""PythonAnywhere WSGI: set path below to your uploaded release folder."""
import sys
PROJECT_DIR = '/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18'
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
from miniapp_server import application
