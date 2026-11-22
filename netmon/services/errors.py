class ValidationError(ValueError):
    def __init__(self, field_errors: dict):
        self.field_errors = field_errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in field_errors.items()))


class AuthError(ValueError):
    def __init__(self, kind="invalid", locked_seconds=0):
        self.kind = kind
        self.locked_seconds = locked_seconds
        super().__init__("Tài khoản bị khóa" if kind == "locked" else "Sai thông tin đăng nhập")
