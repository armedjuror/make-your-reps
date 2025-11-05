from django.apps import AppConfig


class SplitwiseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'splitwise'
    verbose_name = 'Split Your Expenses'

    def ready(self):
        # Import and create default expense categories
        self.create_default_categories()

    def create_default_categories(self):
        """Create default expense categories"""
        try:
            from .models import ExpenseCategory

            default_categories = [
                {'name': 'Food & Dining', 'icon': 'fas fa-utensils', 'color': '#ff6b6b'},
                {'name': 'Transportation', 'icon': 'fas fa-car', 'color': '#4ecdc4'},
                {'name': 'Shopping', 'icon': 'fas fa-shopping-bag', 'color': '#45b7d1'},
                {'name': 'Entertainment', 'icon': 'fas fa-film', 'color': '#96ceb4'},
                {'name': 'Bills & Utilities', 'icon': 'fas fa-file-invoice-dollar', 'color': '#feca57'},
                {'name': 'Travel', 'icon': 'fas fa-plane', 'color': '#ff9ff3'},
                {'name': 'Healthcare', 'icon': 'fas fa-heartbeat', 'color': '#fd79a8'},
                {'name': 'Education', 'icon': 'fas fa-graduation-cap', 'color': '#6c5ce7'},
                {'name': 'Gifts', 'icon': 'fas fa-gift', 'color': '#a29bfe'},
                {'name': 'Other', 'icon': 'fas fa-receipt', 'color': '#636e72'},
            ]

            for category_data in default_categories:
                ExpenseCategory.objects.get_or_create(
                    name=category_data['name'],
                    defaults={
                        'icon': category_data['icon'],
                        'color': category_data['color']
                    }
                )
        except Exception:
            # Ignore errors during app startup (like during migrations)
            pass
