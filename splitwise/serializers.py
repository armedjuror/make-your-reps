from rest_framework import serializers
from django.contrib.auth.models import User
from django.db import transaction
from decimal import Decimal
from .models import (
    Group, GroupMembership, Expense, ExpenseSplit,
    Settlement, ExpenseCategory, Friend, UserProfile
)


class UserSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    whatsapp_number = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'display_name', 'whatsapp_number']

    def get_display_name(self, obj):
        if obj.first_name and obj.last_name:
            return f"{obj.first_name} {obj.last_name}"
        return obj.username

    def get_whatsapp_number(self, obj):
        try:
            return obj.splitwise_profile.whatsapp_number
        except UserProfile.DoesNotExist:
            return ""


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = '__all__'


class GroupMembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = GroupMembership
        fields = ['user', 'joined_at', 'is_active']


class GroupSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    members = UserSerializer(many=True, read_only=True)
    member_emails = serializers.ListField(
        child=serializers.EmailField(),
        write_only=True,
        required=False
    )
    total_expenses = serializers.ReadOnlyField()
    member_count = serializers.ReadOnlyField()

    class Meta:
        model = Group
        fields = [
            'id', 'name', 'description', 'created_by', 'members',
            'member_emails', 'created_at', 'total_expenses', 'member_count'
        ]
        read_only_fields = ['id', 'created_by', 'created_at']

    def create(self, validated_data):
        member_emails = validated_data.pop('member_emails', [])
        user = self.context['request'].user

        with transaction.atomic():
            group = Group.objects.create(created_by=user, **validated_data)

            # Add creator as member
            GroupMembership.objects.create(group=group, user=user)

            # Add other members by email
            for email in member_emails:
                try:
                    member = User.objects.get(email=email)
                    GroupMembership.objects.get_or_create(group=group, user=member)
                except User.DoesNotExist:
                    pass  # Skip invalid emails

        return group


class ExpenseSplitSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = ExpenseSplit
        fields = [
            'id', 'user', 'user_id', 'amount', 'percentage',
            'shares', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ExpenseSerializer(serializers.ModelSerializer):
    paid_by = UserSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    category = ExpenseCategorySerializer(read_only=True)
    splits = ExpenseSplitSerializer(many=True, read_only=True)
    split_data = serializers.ListField(write_only=True, required=False)
    category_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    paid_by_id = serializers.IntegerField(write_only=True, required=False)
    group_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    involved_users = UserSerializer(many=True, read_only=True)

    class Meta:
        model = Expense
        fields = [
            'id', 'description', 'amount', 'paid_by', 'paid_by_id',
            'group', 'group_id', 'category', 'category_id', 'split_type',
            'expense_date', 'created_by', 'created_at', 'notes',
            'splits', 'split_data', 'involved_users', 'is_group_expense'
        ]
        read_only_fields = ['id', 'created_by', 'created_at']

    def create(self, validated_data):
        split_data = validated_data.pop('split_data', [])
        user = self.context['request'].user

        # Set paid_by to current user if not specified
        if 'paid_by_id' not in validated_data:
            validated_data['paid_by_id'] = user.id

        # Set category if provided
        category_id = validated_data.pop('category_id', None)
        if category_id:
            validated_data['category_id'] = category_id

        # Set group if provided
        group_id = validated_data.pop('group_id', None)
        if group_id:
            validated_data['group_id'] = group_id

        with transaction.atomic():
            expense = Expense.objects.create(created_by=user, **validated_data)

            # Create splits
            if split_data:
                self._create_splits(expense, split_data)
            else:
                # Default: equal split between paid_by and current user if different
                if expense.paid_by != user:
                    amount_per_person = expense.amount / 2
                    ExpenseSplit.objects.create(expense=expense, user=expense.paid_by, amount=amount_per_person)
                    ExpenseSplit.objects.create(expense=expense, user=user, amount=amount_per_person)
                else:
                    ExpenseSplit.objects.create(expense=expense, user=user, amount=expense.amount)

        return expense

    def update(self, instance, validated_data):
        split_data = validated_data.pop('split_data', None)
        category_id = validated_data.pop('category_id', None)
        group_id = validated_data.pop('group_id', None)

        if category_id is not None:
            validated_data['category_id'] = category_id
        if group_id is not None:
            validated_data['group_id'] = group_id

        with transaction.atomic():
            # Update expense
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            # Update splits if provided
            if split_data is not None:
                instance.splits.all().delete()
                self._create_splits(instance, split_data)

        return instance

    def _create_splits(self, expense, split_data):
        """Create expense splits based on split type and data"""
        total_amount = expense.amount

        if expense.split_type == 'equal':
            amount_per_person = total_amount / len(split_data)
            for split in split_data:
                ExpenseSplit.objects.create(
                    expense=expense,
                    user_id=split['user_id'],
                    amount=amount_per_person
                )

        elif expense.split_type == 'exact':
            for split in split_data:
                ExpenseSplit.objects.create(
                    expense=expense,
                    user_id=split['user_id'],
                    amount=Decimal(str(split['amount']))
                )

        elif expense.split_type == 'percentage':
            for split in split_data:
                percentage = Decimal(str(split['percentage']))
                amount = (total_amount * percentage) / 100
                ExpenseSplit.objects.create(
                    expense=expense,
                    user_id=split['user_id'],
                    amount=amount,
                    percentage=percentage
                )

        elif expense.split_type == 'shares':
            total_shares = sum(int(split['shares']) for split in split_data)
            for split in split_data:
                shares = int(split['shares'])
                amount = (total_amount * shares) / total_shares
                ExpenseSplit.objects.create(
                    expense=expense,
                    user_id=split['user_id'],
                    amount=amount,
                    shares=shares
                )


class SettlementSerializer(serializers.ModelSerializer):
    from_user = UserSerializer(read_only=True)
    to_user = UserSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    from_user_id = serializers.IntegerField(write_only=True)
    to_user_id = serializers.IntegerField(write_only=True)
    group_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Settlement
        fields = [
            'id', 'from_user', 'to_user', 'from_user_id', 'to_user_id',
            'amount', 'group', 'group_id', 'settlement_date', 'notes',
            'created_by', 'created_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at']

    def create(self, validated_data):
        user = self.context['request'].user
        group_id = validated_data.pop('group_id', None)

        if group_id:
            validated_data['group_id'] = group_id

        return Settlement.objects.create(created_by=user, **validated_data)


class FriendSerializer(serializers.ModelSerializer):
    friend = UserSerializer(read_only=True)
    friend_email = serializers.EmailField(write_only=True)

    class Meta:
        model = Friend
        fields = ['id', 'friend', 'friend_email', 'created_at', 'is_active']
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        friend_email = validated_data.pop('friend_email')
        user = self.context['request'].user

        try:
            friend = User.objects.get(email=friend_email)
            if friend == user:
                raise serializers.ValidationError("You cannot add yourself as a friend.")

            friendship, created = Friend.objects.get_or_create(
                user=user,
                friend=friend,
                defaults={'is_active': True}
            )

            # Create reverse friendship
            Friend.objects.get_or_create(
                user=friend,
                friend=user,
                defaults={'is_active': True}
            )

            return friendship
        except User.DoesNotExist:
            raise serializers.ValidationError("User with this email does not exist.")


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['phone_number', 'preferred_currency', 'whatsapp_number']

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance