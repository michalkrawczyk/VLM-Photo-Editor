from __future__ import annotations

import os

_KEYRING_SERVICE = "vlm_photo_editor"

# Providers whose env var deviates from the {PROVIDER}_API_KEY convention.
_PROVIDER_ENV_KEY: dict[str, str] = {
    "replicate": "REPLICATE_API_TOKEN",
}


def _env_key(provider: str) -> str:
    return _PROVIDER_ENV_KEY.get(provider, f"{provider.upper()}_API_KEY")


class SecretStore:
    @classmethod
    def get(cls, provider: str) -> str:
        env_key = _env_key(provider)

        # 1. Process environment — highest priority
        value = os.environ.get(env_key)
        if value:
            return value

        # 2. OS keyring
        try:
            import keyring

            value = keyring.get_password(_KEYRING_SERVICE, env_key)
            if value:
                return value
        except Exception:
            pass

        # 3. .env file — lowest priority
        try:
            from dotenv import dotenv_values, find_dotenv

            env_file = find_dotenv(usecwd=True)
            if env_file:
                env_values = dotenv_values(env_file)
                value = env_values.get(env_key)
                if value:
                    return value
        except Exception:
            pass

        raise KeyError(
            f"No API key for provider '{provider}'. "
            f"Set {env_key} in environment, OS keyring, or .env file."
        )

    @classmethod
    def has(cls, provider: str) -> bool:
        try:
            cls.get(provider)
            return True
        except KeyError:
            return False

    @classmethod
    def set_in_keyring(cls, provider: str, key: str) -> None:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, _env_key(provider), key)

    @classmethod
    def mask(cls, key: str) -> str:
        if len(key) <= 8:
            return "****"
        return f"{'*' * (len(key) - 4)}{key[-4:]}"
