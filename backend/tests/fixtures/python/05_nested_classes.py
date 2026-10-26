"""A class containing a nested class."""


class Outer:
    class Config:
        debug = True

    def get_config(self):
        return Outer.Config()
