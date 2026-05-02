import os
import importlib
import traceback

os.environ['DISCORD_TOKEN'] = 'TEST_TOKEN'

try:
    importlib.import_module('bot_yt')
    print('MODULE_IMPORTED_OK')
except Exception:
    traceback.print_exc()
