"""
Navigator package for AUV module in ONR project.
"""

from .autonomous_navigator import AutonomousNavigator
from .static_navigator import CompanionNavigator, ScoutNavigator
from .navigator import Navigator

__version__ = "1.0.0"
__all__ = ["AutonomousNavigator", "CompanionNavigator", "ScoutNavigator", "Navigator"]