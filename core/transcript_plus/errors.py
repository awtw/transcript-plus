class AppError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def payload(self):
        return {"code": self.code, "message": self.message}


def require(condition, code, message):
    if not condition:
        raise AppError(code, message)
