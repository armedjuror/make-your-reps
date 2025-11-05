import os

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q, Sum, Case, When, DecimalField, F
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from decimal import Decimal
import json
from collections import defaultdict

from board.models import UserDetail
from board.serializers import UserDetailSerializer
from main.utils import AuthenticatedModelViewSet, NoDestroyViewSet
from main.config_manager import get_config
from .models import (
    Group, Expense, ExpenseSplit, Settlement,
    ExpenseCategory, Friend, UserProfile
)
from .serializers import (
    GroupSerializer, ExpenseSerializer, SettlementSerializer,
    ExpenseCategorySerializer, FriendSerializer, UserSerializer,
    UserProfileSerializer
)


@login_required
def splitwise_dashboard(request):
    """Main splitwise dashboard view"""
    configs = get_config().get_all()
    user_detail, _ = UserDetail.objects.get_or_create(user=request.user)
    context = {
        'user_detail': UserDetailSerializer(user_detail).data,
        'host': os.environ.get("HOST", "http://127.0.0.1:8000/"),
    }
    context.update(configs)
    # Get or create user profile
    profile, created = UserProfile.objects.get_or_create(user=request.user)

    context.update({
        'user_profile': profile,
    })
    context.update(configs)

    return render(request, 'splitwise/dashboard.html', context)


class GroupViewSet(AuthenticatedModelViewSet):
    serializer_class = GroupSerializer

    def get_queryset(self):
        return Group.objects.filter(
            members=self.request.user,
            is_active=True
        ).distinct()

    @action(detail=True, methods=['post'])
    def add_member(self, request, pk=None):
        """Add a member to the group"""
        group = self.get_object()
        email = request.data.get('email')

        if not email:
            return Response(
                {'error': 'Email is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(email=email)
            membership, created = group.groupmembership_set.get_or_create(
                user=user,
                defaults={'is_active': True}
            )

            if not created and not membership.is_active:
                membership.is_active = True
                membership.save()

            return Response({
                'status': 'success',
                'message': f'{user.username} added to group successfully'
            })
        except User.DoesNotExist:
            return Response(
                {'error': 'User with this email does not exist'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['delete'])
    def remove_member(self, request, pk=None):
        """Remove a member from the group"""
        group = self.get_object()
        user_id = request.data.get('user_id')

        try:
            membership = group.groupmembership_set.get(user_id=user_id)
            membership.is_active = False
            membership.save()

            return Response({
                'status': 'success',
                'message': 'Member removed from group successfully'
            })
        except:
            return Response(
                {'error': 'Member not found in group'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['get'])
    def balances(self, request):
        """Get balance summary for all groups"""
        user = request.user
        balances = self._calculate_group_balances(user)

        return Response({
            'status': 'success',
            'data': balances
        })

    def _calculate_group_balances(self, user):
        """Calculate balances for each group the user is part of"""
        groups = self.get_queryset()
        balances = []

        for group in groups:
            balance_info = self._calculate_group_balance(group, user)
            balances.append({
                'group': GroupSerializer(group).data,
                'balance': balance_info
            })

        return balances

    def _calculate_group_balance(self, group, user):
        """Calculate balance for a specific group and user"""
        # Calculate total paid by user
        total_paid = Expense.objects.filter(
            group=group,
            paid_by=user,
            is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Calculate total owed by user
        total_owed = ExpenseSplit.objects.filter(
            expense__group=group,
            user=user,
            is_deleted=False,
            expense__is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Calculate settlements
        settlements_paid = Settlement.objects.filter(
            group=group,
            from_user=user,
            is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        settlements_received = Settlement.objects.filter(
            group=group,
            to_user=user,
            is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        net_balance = total_paid - total_owed + settlements_received - settlements_paid

        return {
            'total_paid': float(total_paid),
            'total_owed': float(total_owed),
            'settlements_paid': float(settlements_paid),
            'settlements_received': float(settlements_received),
            'net_balance': float(net_balance),
            'owes_money': net_balance < 0,
            'owed_money': net_balance > 0
        }


class ExpenseViewSet(AuthenticatedModelViewSet):
    serializer_class = ExpenseSerializer

    def get_queryset(self):
        user = self.request.user
        return Expense.objects.filter(
            Q(created_by=user) | Q(paid_by=user) | Q(splits__user=user),
            is_deleted=False
        ).distinct().order_by('-expense_date', '-created_at')

    @action(detail=False, methods=['get'])
    def recent(self, request):
        """Get recent expenses"""
        limit = int(request.query_params.get('limit', 10))
        expenses = self.get_queryset()[:limit]
        serializer = self.get_serializer(expenses, many=True)

        return Response({
            'status': 'success',
            'data': serializer.data
        })

    @action(detail=False, methods=['get'])
    def by_group(self, request):
        """Get expenses filtered by group"""
        group_id = request.query_params.get('group_id')

        queryset = self.get_queryset()
        if group_id:
            queryset = queryset.filter(group_id=group_id)
        else:
            queryset = queryset.filter(group__isnull=True)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'status': 'success',
            'data': serializer.data
        })

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get expense summary"""
        user = request.user

        # Total expenses created by user
        total_created = Expense.objects.filter(
            created_by=user,
            is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Total amount user paid
        total_paid = Expense.objects.filter(
            paid_by=user,
            is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Total amount user owes
        total_owed = ExpenseSplit.objects.filter(
            user=user,
            is_deleted=False,
            expense__is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        return Response({
            'status': 'success',
            'data': {
                'total_created': float(total_created),
                'total_paid': float(total_paid),
                'total_owed': float(total_owed),
                'net_balance': float(total_paid - total_owed)
            }
        })


class SettlementViewSet(AuthenticatedModelViewSet):
    serializer_class = SettlementSerializer

    def get_queryset(self):
        user = self.request.user
        return Settlement.objects.filter(
            Q(from_user=user) | Q(to_user=user),
            is_deleted=False
        ).order_by('-settlement_date', '-created_at')

    @action(detail=False, methods=['get'])
    def suggestions(self, request):
        """Get settlement suggestions to simplify debts"""
        user = request.user
        group_id = request.query_params.get('group_id')

        suggestions = self._calculate_settlement_suggestions(user, group_id)

        return Response({
            'status': 'success',
            'data': suggestions
        })

    def _calculate_settlement_suggestions(self, user, group_id=None):
        """Calculate optimal settlements to simplify debts"""
        # Get all users involved in transactions with the current user
        if group_id:
            involved_users = User.objects.filter(
                Q(paid_expenses__group_id=group_id, paid_expenses__splits__user=user) |
                Q(expense_splits__expense__group_id=group_id, expense_splits__expense__paid_by=user)
            ).distinct()
        else:
            involved_users = User.objects.filter(
                Q(paid_expenses__splits__user=user) |
                Q(expense_splits__expense__paid_by=user)
            ).distinct()

        balances = {}

        for other_user in involved_users:
            if other_user == user:
                continue

            balance = self._calculate_balance_between_users(user, other_user, group_id)
            if balance != 0:
                balances[other_user.id] = {
                    'user': UserSerializer(other_user).data,
                    'balance': float(balance)
                }

        # Convert to settlement suggestions
        suggestions = []
        for user_id, data in balances.items():
            if data['balance'] < 0:  # User owes money
                suggestions.append({
                    'from_user': UserSerializer(user).data,
                    'to_user': data['user'],
                    'amount': abs(data['balance']),
                    'group_id': group_id
                })
            elif data['balance'] > 0:  # User is owed money
                suggestions.append({
                    'from_user': data['user'],
                    'to_user': UserSerializer(user).data,
                    'amount': data['balance'],
                    'group_id': group_id
                })

        return suggestions

    def _calculate_balance_between_users(self, user1, user2, group_id=None):
        """Calculate net balance between two users"""
        # Amount user1 paid for user2
        if group_id:
            user1_paid_for_user2 = ExpenseSplit.objects.filter(
                expense__paid_by=user1,
                user=user2,
                expense__group_id=group_id,
                is_deleted=False,
                expense__is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            user2_paid_for_user1 = ExpenseSplit.objects.filter(
                expense__paid_by=user2,
                user=user1,
                expense__group_id=group_id,
                is_deleted=False,
                expense__is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            # Settlements
            settlements_1_to_2 = Settlement.objects.filter(
                from_user=user1,
                to_user=user2,
                group_id=group_id,
                is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            settlements_2_to_1 = Settlement.objects.filter(
                from_user=user2,
                to_user=user1,
                group_id=group_id,
                is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        else:
            user1_paid_for_user2 = ExpenseSplit.objects.filter(
                expense__paid_by=user1,
                user=user2,
                expense__group__isnull=True,
                is_deleted=False,
                expense__is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            user2_paid_for_user1 = ExpenseSplit.objects.filter(
                expense__paid_by=user2,
                user=user1,
                expense__group__isnull=True,
                is_deleted=False,
                expense__is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            settlements_1_to_2 = Settlement.objects.filter(
                from_user=user1,
                to_user=user2,
                group__isnull=True,
                is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            settlements_2_to_1 = Settlement.objects.filter(
                from_user=user2,
                to_user=user1,
                group__isnull=True,
                is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Net balance: positive means user1 is owed money, negative means user1 owes money
        net_balance = (user1_paid_for_user2 - user2_paid_for_user1 +
                       settlements_2_to_1 - settlements_1_to_2)

        return net_balance


class ExpenseCategoryViewSet(NoDestroyViewSet):
    serializer_class = ExpenseCategorySerializer
    queryset = ExpenseCategory.objects.all()


class FriendViewSet(AuthenticatedModelViewSet):
    serializer_class = FriendSerializer

    def get_queryset(self):
        return Friend.objects.filter(user=self.request.user, is_active=True)

    @action(detail=False, methods=['get'])
    def search(self, request):
        """Search for users to add as friends"""
        query = request.query_params.get('q', '').strip()

        if len(query) < 2:
            return Response({
                'status': 'success',
                'data': []
            })

        users = User.objects.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        ).exclude(id=request.user.id)[:10]

        # Exclude already added friends
        friend_ids = self.get_queryset().values_list('friend_id', flat=True)
        users = users.exclude(id__in=friend_ids)

        serializer = UserSerializer(users, many=True)
        return Response({
            'status': 'success',
            'data': serializer.data
        })


class DashboardViewSet(NoDestroyViewSet):
    """Dashboard API endpoints"""

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get dashboard summary"""
        user = request.user

        # Recent expenses
        recent_expenses = Expense.objects.filter(
            Q(created_by=user) | Q(paid_by=user) | Q(splits__user=user),
            is_deleted=False
        ).distinct().order_by('-expense_date', '-created_at')[:5]

        # Groups
        groups = Group.objects.filter(
            members=user,
            is_active=True
        ).distinct()[:5]

        # Friends
        friends = Friend.objects.filter(user=user, is_active=True)[:5]

        # Overall balance
        total_paid = Expense.objects.filter(
            paid_by=user,
            is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        total_owed = ExpenseSplit.objects.filter(
            user=user,
            is_deleted=False,
            expense__is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        settlements_paid = Settlement.objects.filter(
            from_user=user,
            is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        settlements_received = Settlement.objects.filter(
            to_user=user,
            is_deleted=False
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        net_balance = total_paid - total_owed + settlements_received - settlements_paid

        return Response({
            'status': 'success',
            'data': {
                'recent_expenses': ExpenseSerializer(recent_expenses, many=True).data,
                'groups': GroupSerializer(groups, many=True).data,
                'friends': FriendSerializer(friends, many=True).data,
                'balance': {
                    'total_paid': float(total_paid),
                    'total_owed': float(total_owed),
                    'settlements_paid': float(settlements_paid),
                    'settlements_received': float(settlements_received),
                    'net_balance': float(net_balance),
                    'owes_money': net_balance < 0,
                    'owed_money': net_balance > 0
                }
            }
        })

    @action(detail=False, methods=['get'])
    def balances(self, request):
        """Get detailed balances with all users"""
        user = request.user
        balances = []

        # Get all users who have financial interactions with current user
        involved_users = User.objects.filter(
            Q(paid_expenses__splits__user=user) |
            Q(expense_splits__expense__paid_by=user) |
            Q(payments_made__to_user=user) |
            Q(payments_received__from_user=user)
        ).exclude(id=user.id).distinct()

        for other_user in involved_users:
            # Calculate balance for each context (groups + non-group)
            contexts = [None]  # Start with non-group transactions

            # Add group contexts
            shared_groups = Group.objects.filter(
                members__in=[user, other_user]
            ).distinct()
            contexts.extend(shared_groups)

            total_balance = Decimal('0')
            context_balances = []

            for context in contexts:
                group_id = context.id if context else None
                balance = self._calculate_balance_between_users_detailed(user, other_user, group_id)

                if balance != 0:
                    context_balances.append({
                        'context': GroupSerializer(context).data if context else {'name': 'Personal', 'id': None},
                        'balance': float(balance)
                    })
                    total_balance += balance

            if total_balance != 0:
                balances.append({
                    'user': UserSerializer(other_user).data,
                    'total_balance': float(total_balance),
                    'context_balances': context_balances
                })

        return Response({
            'status': 'success',
            'data': balances
        })

    def _calculate_balance_between_users_detailed(self, user1, user2, group_id=None):
        """Calculate detailed balance between two users for a specific context"""
        if group_id:
            # Group expenses
            user1_paid_for_user2 = ExpenseSplit.objects.filter(
                expense__paid_by=user1,
                user=user2,
                expense__group_id=group_id,
                is_deleted=False,
                expense__is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            user2_paid_for_user1 = ExpenseSplit.objects.filter(
                expense__paid_by=user2,
                user=user1,
                expense__group_id=group_id,
                is_deleted=False,
                expense__is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            # Group settlements
            settlements_1_to_2 = Settlement.objects.filter(
                from_user=user1,
                to_user=user2,
                group_id=group_id,
                is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            settlements_2_to_1 = Settlement.objects.filter(
                from_user=user2,
                to_user=user1,
                group_id=group_id,
                is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        else:
            # Personal expenses (no group)
            user1_paid_for_user2 = ExpenseSplit.objects.filter(
                expense__paid_by=user1,
                user=user2,
                expense__group__isnull=True,
                is_deleted=False,
                expense__is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            user2_paid_for_user1 = ExpenseSplit.objects.filter(
                expense__paid_by=user2,
                user=user1,
                expense__group__isnull=True,
                is_deleted=False,
                expense__is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            # Personal settlements
            settlements_1_to_2 = Settlement.objects.filter(
                from_user=user1,
                to_user=user2,
                group__isnull=True,
                is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            settlements_2_to_1 = Settlement.objects.filter(
                from_user=user2,
                to_user=user1,
                group__isnull=True,
                is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        net_balance = (user1_paid_for_user2 - user2_paid_for_user1 +
                       settlements_2_to_1 - settlements_1_to_2)

        return net_balance

    @action(detail=False, methods=['post'])
    def whatsapp_notify(self, request):
        """Generate WhatsApp message for expense/settlement notification"""
        message_type = request.data.get('type')  # 'expense' or 'settlement'
        expense_id = request.data.get('expense_id')
        settlement_id = request.data.get('settlement_id')
        phone_number = request.data.get('phone_number')

        if not phone_number:
            return Response({
                'error': 'Phone number is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        message = ""

        if message_type == 'expense' and expense_id:
            try:
                expense = Expense.objects.get(id=expense_id)
                splits = expense.splits.filter(is_deleted=False)

                message = f"💰 New Expense Added: {expense.description}\n"
                message += f"Amount: ${expense.amount}\n"
                message += f"Paid by: {expense.paid_by.get_full_name() or expense.paid_by.username}\n"
                message += f"Date: {expense.expense_date}\n\n"
                message += "Split details:\n"

                for split in splits:
                    message += f"• {split.user.get_full_name() or split.user.username}: ${split.amount}\n"

                if expense.notes:
                    message += f"\nNote: {expense.notes}"

            except Expense.DoesNotExist:
                return Response({
                    'error': 'Expense not found'
                }, status=status.HTTP_404_NOT_FOUND)

        elif message_type == 'settlement' and settlement_id:
            try:
                settlement = Settlement.objects.get(id=settlement_id)
                message = f"✅ Settlement Recorded\n"
                message += f"{settlement.from_user.get_full_name() or settlement.from_user.username} paid "
                message += f"${settlement.amount} to "
                message += f"{settlement.to_user.get_full_name() or settlement.to_user.username}\n"
                message += f"Date: {settlement.settlement_date}\n"

                if settlement.notes:
                    message += f"\nNote: {settlement.notes}"

            except Settlement.DoesNotExist:
                return Response({
                    'error': 'Settlement not found'
                }, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({
                'error': 'Invalid message type or missing ID'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Clean phone number (remove non-digits)
        clean_phone = ''.join(filter(str.isdigit, phone_number))

        whatsapp_url = f"https://wa.me/{clean_phone}?text={message}"

        return Response({
            'status': 'success',
            'data': {
                'whatsapp_url': whatsapp_url,
                'message': message
            }
        })