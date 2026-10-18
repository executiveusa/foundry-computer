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

    @model_validator(mode="after")
    def _fail_closed_on_weak_key(self):
        weak = self.api_key in {_DEFAULT_KEY, _PLACEHOLDER_KEY} or len(self.api_key) < 16
        if weak and not self.dev_mode:
            raise ValueError(
                "FOUNDRY_API_KEY is the public default or too short; set a real key "
                "(>=16 chars) or explicitly opt into FOUNDRY_DEV_MODE=true for local dev"
            )
        return self


settings = Settings()
