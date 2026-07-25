import requests


def download(url: str) -> bytes:
    response = requests.get(url)
    response.raise_for_status()
    return response.content
