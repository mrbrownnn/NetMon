"""Fernet encryption at persistence boundary (NFR-03)."""
from cryptography.fernet import Fernet


class Crypto:
    def __init__(self, key: str | bytes):
        self.fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self.fernet.decrypt(value.encode()).decode()
