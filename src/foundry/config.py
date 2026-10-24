from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_KEY = "foundry-local-dev"
_PLACEHOLDER_KEY = "replace-with-a-long-random-key"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FOUNDRY_", env_file=".env")
    api_key: str = _DEFAULT_KEY
    database_path: str = "/data/foundry.db"
    runtime: str = "mock"
    public_signup: bool = False
    preview_user: str = "client"
    preview_password: str = ""
    dev_mode: bool = False
    mock_allow_bash: bool = False
    runtime_backend: str = "mock"  # mock | bash | opensandbox

    # OpenSandbox backend (runtime_backend="opensandbox"). The OpenSandbox
    # server must run with server.api_key set; Foundry refuses to point at an
    # unauthenticated sandbox server outside dev_mode.
    opensandbox_domain: str = ""  # host:port of the OpenSandbox server
    opensandbox_protocol: str = "http"  # http on the VPS LAN, https behind a TLS proxy
    opensandbox_api_key: str = ""
    opensandbox_default_image: str = "opensandbox/desktop:latest"
    opensandbox_timeout_minutes: int = 60
    opensandbox_egress_allowlist: str = ""  # comma-separated domains; empty = deny-all egress

    @model_validator(mode="after")
    def _fail_closed_on_weak_key(self):
        weak = self.api_key in {_DEFAULT_KEY, _PLACEHOLDER_KEY} or len(self.api_key) < 16
        if weak and not self.dev_mode:
            raise ValueError(
                "FOUNDRY_API_KEY is the public default or too short; set a real key "
                "(>=16 chars) or explicitly opt into FOUNDRY_DEV_MODE=true for local dev"
            )
        return self

    @model_validator(mode="after")
    def _opensandbox_requires_endpoint_and_key(self):
        if self.runtime_backend == "opensandbox":
            if not self.opensandbox_domain:
                raise ValueError(
                    "FOUNDRY_OPENSANDBOX_DOMAIN is required when "
                    "FOUNDRY_RUNTIME_BACKEND=opensandbox"
                )
            if not self.opensandbox_api_key and not self.dev_mode:
                raise ValueError(
                    "FOUNDRY_OPENSANDBOX_API_KEY is required outside dev mode: "
                    "an unauthenticated sandbox server is a remote-code-execution endpoint"
                )
        return self


settings = Settings()
