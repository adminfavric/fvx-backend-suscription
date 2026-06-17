"""
API models package.

`base` contains the project template models. Implementers may add new modules
in this package and import them here so Django loads them.
"""

from .base import *  # noqa: F401,F403
from .social import *  # noqa: F401,F403
from .user import User  # noqa: F401
