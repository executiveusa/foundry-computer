from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FOUNDRY_", env_file=".env")
    api_key: str = "foundry-local-dev"
    database_path: str = "/data/foundry.db"
    runtime: str = "mock"
    public_signup: bool = False
settings = Settings()
