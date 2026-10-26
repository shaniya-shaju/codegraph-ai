"""Classes with single and multiple inheritance."""


class Animal:
    """Base animal."""

    def speak(self):
        return "..."


class Dog(Animal):
    def speak(self):
        return "Woof"


class ServiceMixin:
    pass


class Cat(Animal, ServiceMixin):
    def speak(self):
        return "Meow"
