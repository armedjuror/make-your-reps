from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.db import models


# Create your models here.
class Theme(models.TextChoices):
   DARK = 'dark'
   LIGHT = 'light'

class UserDetail(models.Model):
   user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
   workday_routine = models.TextField(default='')
   holiday_routine = models.TextField(default='')
   default_theme = models.CharField(
      max_length=16,
      choices=Theme.choices,
      default=Theme.LIGHT
   )
   updated_at = models.DateTimeField(auto_now=True)
   created_at = models.DateTimeField(auto_now_add=True)

class Friend(models.Model):
   user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='user')
   friend = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friend')
   is_active = models.BooleanField(default=True)
   created_at = models.DateTimeField(auto_now_add=True)
   updated_at = models.DateTimeField(auto_now=True)

   class Meta:
      ordering = ['-created_at']
      unique_together = ('user', 'friend')


class Task(models.Model):
   id = models.AutoField(primary_key=True)
   user = models.ForeignKey(User, on_delete=models.CASCADE)
   task_name = models.TextField()
   is_done = models.BooleanField(default=False)
   is_deleted = models.BooleanField(default=False)
   created_at = models.DateTimeField(auto_now_add=True)
   updated_at = models.DateTimeField(auto_now=True)

   def __str__(self):
      return f'{self.user} - {self.task_name}'

   class Meta:
      ordering = ['-created_at']


class DailyData(models.Model):
   id = models.AutoField(primary_key=True)
   user = models.ForeignKey(User, on_delete=models.CASCADE)
   date = models.DateField()
   journal = models.TextField(null=True, blank=True, default='')
   sleep_hours = models.DecimalField(max_digits=5, decimal_places=2, default=None, null=True)

   class Meta:
      ordering = ['date']
      unique_together = ('user', 'date')



class HabitStatus(models.TextChoices):
   ACTIVE = 'active'
   DELETED = 'deleted'
   COMPLETED = 'completed'


class Habit(models.Model):
   id = models.AutoField(primary_key=True)
   habit = models.CharField(max_length=255)
   user = models.ForeignKey(User, on_delete=models.CASCADE)
   detail = models.TextField(blank=True)
   identity = models.CharField(max_length=255)
   created_at = models.DateTimeField(auto_now_add=True)
   frequency = ArrayField(models.IntegerField(), size=7, default=list)
   notify_at = models.TimeField(null=True, blank=True, default=None)
   status = models.CharField(
       max_length=10,
       choices=HabitStatus.choices,
       default=HabitStatus.ACTIVE.value
   )


class LogStatus(models.TextChoices):
   DONE = 'done'
   PENDING = 'pending'


class HabitLog(models.Model):
   id = models.AutoField(primary_key=True)
   habit = models.ForeignKey(Habit, on_delete=models.CASCADE)
   date = models.DateField()
   is_done = models.BooleanField(default=False)
   created_at = models.DateTimeField(auto_now_add=True)
   updated_at = models.DateTimeField(auto_now=True)

   class Meta:
      ordering = ['-created_at']
      unique_together = ('habit', 'date')


class AccountabilityPartner(models.Model):
   habit = models.ForeignKey(Habit, on_delete=models.CASCADE)
   partner = models.ForeignKey(User, on_delete=models.CASCADE)
   is_active = models.BooleanField(default=True)
   created_at = models.DateTimeField(auto_now_add=True)
   updated_at = models.DateTimeField(auto_now=True)

   class Meta:
       unique_together = ['habit', 'partner']