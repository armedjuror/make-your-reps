import threading
from typing import Any

from django.core.cache import cache

from main.models import Config


class ConfigManager:
    """
    A class that fetches configuration data from the Config table
    and stores it as properties for easy access using Django's cache.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """Singleton pattern to ensure only one instance exists."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, cache_timeout: int = 300):
        """
        Initialize the ConfigManager.
        Uses Django's configured cache backend with lazy loading.

        Args:
            cache_timeout (int): Cache timeout in seconds (default: 5 minutes)
        """
        # Prevent re-initialization of singleton
        if self._initialized:
            return

        self.cache_timeout = cache_timeout
        self._config_data = {}
        self._cache_key = 'config_manager_data'
        self._initialized = True

        # Don't load config during initialization to avoid DB access warnings
        print("ConfigManager initialized (lazy loading enabled)")

    def _load_config(self):
        """Load configuration data from cache or database with automatic TTL handling."""
        # Try to get from cache first
        cached_data = cache.get(self._cache_key)
        if cached_data is not None:
            self._config_data = cached_data
            self._set_properties()
            return

        # If not in cache (expired or first load), fetch from database
        self._fetch_from_database()

    def _fetch_from_database(self):
        """Fetch configuration data from database and cache it."""
        try:
            # Check if the table exists first
            if not self._table_exists():
                print("ConfigManager: Config table doesn't exist yet")
                self._config_data = {}
                return

            config_items = Config.objects.all()
            self._config_data = {item.key: item.value for item in config_items}

            # Cache the data with TTL - it will auto-reload when TTL expires
            cache.set(self._cache_key, self._config_data, self.cache_timeout)

            self._set_properties()
            print(f"ConfigManager: Loaded {len(self._config_data)} config items from database")

        except Exception as e:
            print(f"Error loading config from database: {e}")
            self._config_data = {}

    def _table_exists(self):
        """Check if the Config table exists"""
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                table_name = Config._meta.db_table
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_name = %s
                """, [table_name])
                return cursor.fetchone()[0] > 0
        except Exception:
            return False

    def _set_properties(self):
        """Set configuration values as properties of this instance."""
        for key, value in self._config_data.items():
            # Convert key to valid Python attribute name
            attr_name = self._sanitize_key(key)
            # Use object.__setattr__ to avoid triggering __getattr__
            object.__setattr__(self, attr_name, self._convert_value(value))

    def _sanitize_key(self, key: str) -> str:
        """
        Convert database key to valid Python attribute name.
        Replace spaces, hyphens, and other invalid characters with underscores.
        """
        import re
        # Replace invalid characters with underscores
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', key)
        # Ensure it doesn't start with a number
        if sanitized and sanitized[0].isdigit():
            sanitized = f"_{sanitized}"
        return sanitized.lower()

    def _convert_value(self, value: str) -> Any:
        """
        Attempt to convert string values to appropriate Python types.
        """
        if not isinstance(value, str):
            return value

        # Try to convert to boolean
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'

        # Try to convert to int
        try:
            return int(value)
        except ValueError:
            pass

        # Try to convert to float
        try:
            return float(value)
        except ValueError:
            pass

        # Return as string if no conversion possible
        return value

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value by key with automatic reload if cache expired.

        Args:
            key (str): The configuration key
            default (Any): Default value if key doesn't exist

        Returns:
            Any: The configuration value or default
        """
        # Load config on first access (lazy loading)
        if not self._config_data:
            self._load_config()
        else:
            # Check if cache expired by trying to reload
            self._load_config()
        return self._config_data.get(key, default)

    def reload(self):
        """Force reload configuration data from the database."""
        cache.delete(self._cache_key)
        self._fetch_from_database()

    def get_all(self) -> dict:
        """Return all configuration data as a dictionary."""
        if not self._config_data:
            self._load_config()
        return self._config_data.copy()

    def __getattr__(self, name: str) -> Any:
        """
        Fallback for accessing config values with automatic reload if cache expired.
        """
        # Prevent infinite recursion by checking if we're accessing internal attributes
        if name.startswith('_') or name in ['cache_timeout', 'initialized']:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

        # Load config on first access (lazy loading)
        if not self._config_data:
            self._load_config()
        else:
            self._load_config()  # Check for cache expiry

        # Look for the original key that matches this sanitized name
        for key, value in self._config_data.items():
            if self._sanitize_key(key) == name:
                return self._convert_value(value)

        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    @classmethod
    def get_instance(cls, cache_timeout: int = 300) -> 'ConfigManager':
        """Get the singleton instance of ConfigManager."""
        return cls(cache_timeout)


# Global singleton instance
config = None


def get_config(cache_timeout: int = 300) -> ConfigManager:
    """
    Get the config instance with lazy initialization.
    Safe to call during migrations and avoids DB access during app startup.

    Args:
        cache_timeout (int): Cache timeout in seconds

    Returns:
        ConfigManager: The singleton instance
    """
    global config
    if config is None:
        config = ConfigManager(cache_timeout)
    return config