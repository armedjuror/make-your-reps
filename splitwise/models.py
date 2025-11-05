from django.contrib.auth.models import User
from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
import uuid


class Group(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_groups')
    members = models.ManyToManyField(User, through='GroupMembership', related_name='splitwise_groups')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def total_expenses(self):
        return sum(expense.amount for expense in self.expenses.filter(is_deleted=False))

    @property
    def member_count(self):
        return self.members.count()


class GroupMembership(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('group', 'user')

    def __str__(self):
        return f"{self.user.username} in {self.group.name}"


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=50)
    icon = models.CharField(max_length=50, default='fas fa-receipt')
    color = models.CharField(max_length=7, default='#6c757d')  # Hex color
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Expense Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class SplitType(models.TextChoices):
    EQUAL = 'equal', 'Equal Split'
    EXACT = 'exact', 'Exact Amount'
    PERCENTAGE = 'percentage', 'Percentage'
    SHARES = 'shares', 'Shares'


class Expense(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    paid_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='paid_expenses')
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='expenses', null=True, blank=True)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True)
    split_type = models.CharField(max_length=20, choices=SplitType.choices, default=SplitType.EQUAL)
    expense_date = models.DateField()
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_expenses')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-expense_date', '-created_at']

    def __str__(self):
        return f"{self.description} - ${self.amount}"

    @property
    def is_group_expense(self):
        return self.group is not None

    @property
    def total_splits(self):
        return self.splits.filter(is_deleted=False).count()

    @property
    def involved_users(self):
        return User.objects.filter(
            id__in=self.splits.filter(is_deleted=False).values_list('user_id', flat=True)
        ).distinct()


class ExpenseSplit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='splits')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expense_splits')
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0.00'))])
    shares = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        unique_together = ('expense', 'user')
        ordering = ['user__username']

    def __str__(self):
        return f"{self.user.username} owes ${self.amount} for {self.expense.description}"


class Settlement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments_made')
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments_received')
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='settlements', null=True, blank=True)
    settlement_date = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_settlements')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ['-settlement_date', '-created_at']

    def __str__(self):
        return f"{self.from_user.username} paid ${self.amount} to {self.to_user.username}"


class Friend(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friendships')
    friend = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friend_of')
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('user', 'friend')
        ordering = ['friend__username']

    def __str__(self):
        return f"{self.user.username} is friends with {self.friend.username}"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='splitwise_profile')
    phone_number = models.CharField(max_length=20, blank=True)
    preferred_currency = models.CharField(max_length=3, default='INR')
    whatsapp_number = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user.username}"