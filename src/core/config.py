from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SkillPath AI"
    app_env: str = "development"
    debug: bool = True

    database_url: str = "sqlite:///./skillpath.db"

    random_seed: int = 20261022
    dataset_profile: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()