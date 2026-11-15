from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import datetime

# Create your models here

class UserProfile(models.Model):
    GENDER_CHOICES = [
        ('female', 'Female'),
        ('male', 'Male'),
        ('other', 'Other'),
        ('prefer_not_to_say', 'Prefer not to say'),
    ]

    ACTIVITY_CHOICES = [
        ('sedentary', 'Sedentary'),
        ('light', 'Lightly Active'),
        ('moderate', 'Moderately Active'),
        ('very', 'Very Active'),
    ]

    GOAL_CHOICES = [
        ('lose', 'Lose Weight'),
        ('maintain', 'Maintain Weight'),
        ('gain', 'Gain Weight'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="userprofile")

    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True)
    height = models.FloatField(null=True, blank=True)
    weight = models.FloatField(null=True, blank=True)
    activity_level = models.CharField(max_length=30, choices=ACTIVITY_CHOICES, blank=True, default='sedentary')
    goal = models.CharField(max_length=30, choices=GOAL_CHOICES, blank=True, default='maintain')
    daily_calorie_target = models.FloatField(null=True, blank=True)

    allergies = models.ManyToManyField(
        "Allergen",
        blank=True,
        related_name="users"
    )

    dietary_tags = models.ManyToManyField(
        "DietaryTag",
        blank=True,
        related_name="users"
    )

    custom_allergies = models.TextField(
        blank=True,
        default=""
    )

    custom_dietary_tags = models.TextField(
        blank=True,
        default=""
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def calorie_target(self):
        if self.daily_calorie_target:
            return self.daily_calorie_target
        return 2000.0

    def __str__(self):
        return self.user.username


class FoodCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class DietaryTag(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Allergen(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Food(models.Model):
    name = models.CharField(max_length=150)
    name_nepali = models.CharField(max_length=150, blank=True, default="")

    category = models.ForeignKey(
        FoodCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="foods"
    )

    dietary_tags = models.ManyToManyField(
        DietaryTag,
        blank=True,
        related_name="foods"
    )

    allergens = models.ManyToManyField(
        Allergen,
        blank=True,
        related_name="foods"
    )

    calories = models.FloatField()
    protein = models.FloatField(default=0)
    carbohydrates = models.FloatField(default=0)
    fat = models.FloatField(default=0)
    fiber = models.FloatField(default=0)
    sugar = models.FloatField(default=0)
    sodium = models.FloatField(default=0)

    is_vegetarian = models.BooleanField(default=False)
    is_vegan = models.BooleanField(default=False)
    is_nepali = models.BooleanField(default=False)

    food_type = models.CharField(max_length=30, blank=True, default="")
    meal_category = models.CharField(max_length=80, blank=True, default="")
    is_recommendable = models.BooleanField(default=False, db_index=True)
    is_supplement = models.BooleanField(default=False)
    is_edible_food = models.BooleanField(default=True)
    preparation_state = models.CharField(max_length=30, blank=True, default="")
    recommendation_group = models.CharField(max_length=80, blank=True, default="")

    source_key = models.CharField(max_length=120, blank=True, null=True, unique=True)
    source_name = models.CharField(max_length=150, blank=True)
    source_url = models.URLField(blank=True)

    serving_size = models.FloatField(default=100)
    serving_unit = models.CharField(max_length=30, default="g")

    def __str__(self):
        return self.name


class FoodVariant(models.Model):
    food = models.ForeignKey(
        Food,
        on_delete=models.CASCADE,
        related_name="variants"
    )

    name = models.CharField(max_length=100)

    calories = models.FloatField()
    protein = models.FloatField(default=0)
    carbohydrates = models.FloatField(default=0)
    fat = models.FloatField(default=0)
    fiber = models.FloatField(default=0)

    serving_size = models.FloatField(default=100)
    serving_unit = models.CharField(max_length=30, default="g")

    def __str__(self):
        return f"{self.food.name} - {self.name}"


class FoodPreference(models.Model):
    PREFERENCE_CHOICES = [
        ('like', 'Like'),
        ('dislike', 'Dislike'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='food_preferences',
    )
    food = models.ForeignKey(
        Food,
        on_delete=models.CASCADE,
        related_name='preferences',
    )
    preference = models.CharField(max_length=10, choices=PREFERENCE_CHOICES)
    shown_rank = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('user', 'food'),
                name='unique_user_food_preference',
            ),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.food.name} ({self.preference})"


class MealLog(models.Model):
    MEAL_TYPES = [
        ("breakfast", "Breakfast"),
        ("lunch", "Lunch"),
        ("dinner", "Dinner"),
        ("snack", "Snack"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="meal_logs"
    )

    food = models.ForeignKey(
        Food,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meal_logs"
    )

    food_name = models.CharField(max_length=200)

    meal_type = models.CharField(
        max_length=20,
        choices=MEAL_TYPES
    )

    quantity = models.FloatField(default=1)

    calories = models.FloatField(default=0)
    protein = models.FloatField(default=0)
    carbohydrates = models.FloatField(default=0)
    fat = models.FloatField(default=0)
    fiber = models.FloatField(default=0)

    consumed_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.food_name}"


class WaterLog(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="water_logs"
    )

    amount_ml = models.FloatField()
    consumed_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.user.username} - {self.amount_ml} ml"


class WeightLog(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="weight_logs"
    )

    weight = models.FloatField()
    recorded_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.weight} kg"
