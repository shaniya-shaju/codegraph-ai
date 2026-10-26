"""Assorted decorators, including a parametrized one that isn't a route."""


def retry(times):
    def decorator(func):
        return func

    return decorator


class Widget:
    @staticmethod
    def build():
        pass

    @classmethod
    def from_config(cls, config):
        return cls()

    @property
    def label(self):
        return "widget"

    @retry(times=3)
    def flaky(self):
        pass
