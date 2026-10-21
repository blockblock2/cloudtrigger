"""cloudtrigger — react to Scratch cloud variable changes by setting cloud variables."""
from .cloud import Change, CloudWatcher
from .encoding import decode, encode
from .session import LoginError, login

__all__ = ["CloudWatcher", "Change", "encode", "decode", "login", "LoginError"]
__version__ = "0.2.0"
