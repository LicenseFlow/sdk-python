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

class ApprovalRequiredError(LicenseFlowError):
    """Raised when an MCP tool or capability requires human approval before execution."""
    def __init__(self, approval_request_id, message="Action requires human approval before execution"):
        super().__init__(message, code="APPROVAL_REQUIRED", status=202)
        self.approval_request_id = approval_request_id

class PolicyDeniedError(LicenseFlowError):
    """Raised when a runtime policy or emergency kill switch denies tool execution."""
    def __init__(self, message, reason=None, code="POLICY_DENIED"):
        super().__init__(message, code=code, status=403)
        self.reason = reason or message
