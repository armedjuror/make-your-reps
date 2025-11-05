from django.contrib import admin
from .models import (
    Group, GroupMembership, Expense, ExpenseSplit,
    Settlement, ExpenseCategory, Friend, UserProfile
)


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon', 'color', 'created_at')
    search_fields = ('name',)
    list_filter = ('created_at',)


class GroupMembershipInline(admin.TabularInline):
    model = GroupMembership
    extra = 0
    readonly_fields = ('joined_at',)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_by', 'member_count', 'total_expenses', 'created_at', 'is_active')
    search_fields = ('name', 'description', 'created_by__username')
    list_filter = ('is_active', 'created_at')
    readonly_fields = ('id', 'created_at', 'updated_at', 'total_expenses', 'member_count')
    inlines = [GroupMembershipInline]

    def member_count(self, obj):
        return obj.member_count
    member_count.short_description = 'Members'


class ExpenseSplitInline(admin.TabularInline):
    model = ExpenseSplit
    extra = 0
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('description', 'amount', 'paid_by', 'group', 'split_type', 'expense_date', 'created_by', 'is_deleted')
    search_fields = ('description', 'paid_by__username', 'created_by__username')
    list_filter = ('split_type', 'expense_date', 'is_deleted', 'created_at', 'category')
    readonly_fields = ('id', 'created_at', 'updated_at', 'total_splits', 'involved_users')
    inlines = [ExpenseSplitInline]
    date_hierarchy = 'expense_date'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('paid_by', 'created_by', 'group', 'category')


@admin.register(ExpenseSplit)
class ExpenseSplitAdmin(admin.ModelAdmin):
    list_display = ('expense', 'user', 'amount', 'percentage', 'shares', 'created_at', 'is_deleted')
    search_fields = ('expense__description', 'user__username')
    list_filter = ('is_deleted', 'created_at')
    readonly_fields = ('id', 'created_at', 'updated_at')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('expense', 'user')


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ('from_user', 'to_user', 'amount', 'group', 'settlement_date', 'created_by', 'is_deleted')
    search_fields = ('from_user__username', 'to_user__username', 'created_by__username')
    list_filter = ('settlement_date', 'is_deleted', 'created_at')
    readonly_fields = ('id', 'created_at', 'updated_at')
    date_hierarchy = 'settlement_date'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('from_user', 'to_user', 'group', 'created_by')


@admin.register(Friend)
class FriendAdmin(admin.ModelAdmin):
    list_display = ('user', 'friend', 'created_at', 'is_active')
    search_fields = ('user__username', 'friend__username')
    list_filter = ('is_active', 'created_at')
    readonly_fields = ('created_at',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'friend')


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone_number', 'whatsapp_number', 'preferred_currency', 'created_at')
    search_fields = ('user__username', 'user__email', 'phone_number', 'whatsapp_number')
    list_filter = ('preferred_currency', 'created_at')
    readonly_fields = ('created_at', 'updated_at')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')