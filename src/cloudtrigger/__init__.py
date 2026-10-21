"""cloudtrigger — react to Scratch cloud variable changes by setting cloud variables."""
from .cloud import Change, CloudWatcher
from .encoding import decode, encode
from .session import VERSION as __version__, LoginError, login

__all__ = ["CloudWatcher", "Change", "encode", "decode", "login", "LoginError"]
