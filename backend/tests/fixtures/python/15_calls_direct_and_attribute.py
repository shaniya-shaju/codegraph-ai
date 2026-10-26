"""Direct calls, attribute calls, constructor-shaped calls, and a
call-on-a-call that can't be resolved statically."""


class AuthService:
    def login(self):
        validate_credentials()
        auth.perform_login()
        self.audit()
        session = SessionFactory()
        handler = get_handler()
        handler()
        return session
