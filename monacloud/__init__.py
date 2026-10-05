"""Official zero-dependency MONA Cloud SDK."""

from .client import DEFAULT_BASE_URL, MonaCloud, MonaCloudError

__all__ = ["DEFAULT_BASE_URL", "MonaCloud", "MonaCloudError"]
__version__ = "0.1.1"
