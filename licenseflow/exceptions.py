class LicenseFlowError(Exception):
    """Base class for all LicenseFlow exceptions."""
    def __init__(self, message, code=None, status=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status

class NetworkError(LicenseFlowError):
    """Raised when a network-level error occurs."""
    def __init__(self, message):
        super().__init__(message, code="NETWORK_ERROR")

class RateLimitError(LicenseFlowError):
    """Raised when the API rate limit is exceeded."""
    def __init__(self, message):
        super().__init__(message, code="RATE_LIMIT_EXCEEDED", status=429)

class InvalidLicenseError(LicenseFlowError):
    """Raised when the provided license is invalid or not found."""
    def __init__(self, message):
        super().__init__(message, code="INVALID_LICENSE", status=400)
