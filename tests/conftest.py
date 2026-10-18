import os
import tempfile

os.environ["FOUNDRY_DEV_MODE"] = "true"
os.environ.setdefault("FOUNDRY_DATABASE_PATH", tempfile.mktemp())
