from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    splitwise_dashboard, GroupViewSet, ExpenseViewSet,
    SettlementViewSet, ExpenseCategoryViewSet, FriendViewSet,
    DashboardViewSet
)

# API Router
api_router = DefaultRouter()
api_router.register(r'groups', GroupViewSet, basename='groups')
api_router.register(r'expenses', ExpenseViewSet, basename='expenses')
api_router.register(r'settlements', SettlementViewSet, basename='settlements')
api_router.register(r'categories', ExpenseCategoryViewSet, basename='categories')
api_router.register(r'friends', FriendViewSet, basename='friends')
api_router.register(r'dashboard', DashboardViewSet, basename='dashboard')

urlpatterns = [
    # Main dashboard
    path('', splitwise_dashboard, name='splitwise_dashboard'),

    # API endpoints
    path('api/', include(api_router.urls)),
]