def configparser_safe_url(database_url: str) -> str:
    """Escape percent characters before writing a URL into Alembic's INI config."""
    return database_url.replace("%", "%%")
