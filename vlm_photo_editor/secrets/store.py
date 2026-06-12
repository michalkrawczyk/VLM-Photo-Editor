from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_KEYRING_SERVICE = "vlm_photo_editor"


class SecretStore:
    @classmethod
    def get(cls, provider: str) -> str:
        env_key = f"{provider.upper()}_API_KEY"

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
            from dotenv import find_dotenv, dotenv_values

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
    def set_in_keyring(cls, provider: str, key: str) -> None:
        import keyring

        env_key = f"{provider.upper()}_API_KEY"
        keyring.set_password(_KEYRING_SERVICE, env_key, key)

    @classmethod
    def mask(cls, key: str) -> str:
        if len(key) <= 4:
            return "****"
        return f"{'*' * (len(key) - 4)}{key[-4:]}"
