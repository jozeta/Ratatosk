"""The single source of truth for Ratatosk's version.

Follows semantic versioning (https://semver.org): bump MAJOR for changes that
break compatibility (file format, API, configuration), MINOR for new
features, PATCH for fixes. Record every release in CHANGELOG.md. The CLI
(cli/ratatosk.py) carries the same number; a test keeps them in sync.
"""
__version__ = "2.2.0"
