from abc import ABC, abstractmethod

class BaseParser(ABC):
    @abstractmethod
    def parse(self, html: str):
        raise NotImplementedError
