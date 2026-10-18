import os
import tempfile

os.environ["FOUNDRY_DEV_MODE"] = "true"
os.environ.setdefault("FOUNDRY_DATABASE_PATH", tempfile.mktemp())
# suite env lives here ONLY: settings is a process-wide singleton read once,
# so any test-module-level os.environ writes lose to import order
os.environ.setdefault("FOUNDRY_PREVIEW_USER", "client")
os.environ.setdefault("FOUNDRY_PREVIEW_PASSWORD", "test-preview-only")
os.environ.setdefault("FOUNDRY_MOCK_ALLOW_BASH", "1")
