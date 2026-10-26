"""A function containing nested functions, one of them calling the other."""


def outer():
    def inner_one():
        return 1

    def inner_two():
        return inner_one() + 1

    return inner_two()
