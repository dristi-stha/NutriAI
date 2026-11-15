from datetime import date
from django.contrib.auth.models import User
from django.test import TestCase
from django.core.management import call_command
from io import StringIO

from myapp.models import Food, MealLog, UserProfile
from myapp.services.calculations import calculate_nutrition_baseline


class ImportFoodsCommandTests(TestCase):
	def test_import_saves_labels_and_disables_old_catalog_items(self):
		old_food = Food.objects.create(
			name='Old catalog food', calories=100, is_recommendable=True,
		)

		call_command('import_foods', stdout=StringIO())

		imported_food = Food.objects.get(source_key='destination-food:1')
		old_food.refresh_from_db()

		self.assertTrue(imported_food.is_recommendable)
		self.assertTrue(imported_food.is_edible_food)
		self.assertFalse(imported_food.is_supplement)
		self.assertEqual(imported_food.recommendation_group, 'beverage')
		self.assertFalse(old_food.is_recommendable)
		self.assertEqual(Food.objects.filter(name__iexact='Walnut').count(), 2)


class DashboardMealLoggingTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='dashboard-meal-test')
		UserProfile.objects.create(
			user=self.user,
			date_of_birth=date(1990, 1, 1),
			gender='female',
			height=165,
			weight=65,
			activity_level='moderate',
			goal='maintain',
		)
		self.client.force_login(self.user)

	def test_dashboard_logs_catalog_food_without_variants(self):
		Food.objects.create(
			name='Plain rice', calories=130, protein=2.7,
			carbohydrates=28, fat=0.3, fiber=0.4,
		)

		response = self.client.post('/dashboard/', {
			'food_name': 'Plain rice',
			'meal_type': 'lunch',
			'portion_grams': '150',
			'meal_submit': '1',
		})

		self.assertEqual(response.status_code, 302)
		meal = MealLog.objects.get(user=self.user)
		self.assertEqual(meal.food_name, 'Plain rice')
		self.assertEqual(meal.quantity, 150)
		self.assertEqual(meal.calories, 195)
		self.assertEqual(meal.protein, 4.1)
		self.assertAlmostEqual(meal.carbohydrates, 42)
		self.assertContains(self.client.get('/dashboard/'), '195 kcal')


class NutritionBaselineTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='nutrition-target-test')

	def make_profile(self, goal):
		return UserProfile(
			user=self.user,
			date_of_birth=date(1990, 1, 1),
			gender='female',
			height=165,
			weight=65,
			activity_level='moderate',
			goal=goal,
		)

	def test_goal_targets_are_relative_to_personal_tdee(self):
		lose = calculate_nutrition_baseline(self.make_profile('lose'))
		maintain = calculate_nutrition_baseline(self.make_profile('maintain'))
		gain = calculate_nutrition_baseline(self.make_profile('gain'))

		self.assertLess(lose['calorie_target'], lose['tdee'])
		self.assertEqual(maintain['calorie_target'], maintain['tdee'])
		self.assertGreater(gain['calorie_target'], gain['tdee'])

	def test_macro_targets_use_profile_weight_and_calorie_target(self):
		baseline = calculate_nutrition_baseline(self.make_profile('maintain'))

		self.assertEqual(baseline['macro_targets']['protein'], 78)
		self.assertGreater(baseline['macro_targets']['carbohydrates'], 0)
		self.assertGreater(baseline['macro_targets']['fat'], 0)
