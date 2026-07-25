import hashlib


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
