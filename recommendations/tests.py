import json
import tempfile
from datetime import date
from django.contrib.auth.models import User
from django.test import Client, TestCase
import numpy as np
from myapp.models import Food, MealLog, UserProfile
from rest_framework.test import APIRequestFactory, force_authenticate
from recommendations.views import GetRecommendationsView, _get_budget, get_user_recommendations
from recommendations.ml.train import generate_training_plots


class RecommendationEligibilityTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='recommendation-test')

	def test_only_csv_approved_edible_non_supplements_are_recommended(self):
		Food.objects.create(
			name='Eligible meal', calories=250, is_recommendable=True,
			is_edible_food=True, is_supplement=False, food_type='meal',
		)
		Food.objects.create(
			name='Eligible dessert', calories=200, is_recommendable=True,
			is_edible_food=True, is_supplement=False, food_type='food',
			recommendation_group='sweet_dessert',
		)
		Food.objects.create(
			name='Raw ingredient', calories=40, is_recommendable=False,
			is_edible_food=True, is_supplement=False, food_type='ingredient',
		)
		Food.objects.create(
			name='Supplement', calories=20, is_recommendable=True,
			is_edible_food=True, is_supplement=True, food_type='supplement',
		)
		Food.objects.create(
			name='Not edible', calories=20, is_recommendable=True,
			is_edible_food=False, is_supplement=False,
		)

		recommendations = get_user_recommendations(self.user)
		names = {item['name'] for item in recommendations}

		self.assertEqual(names, {'Eligible meal', 'Eligible dessert'})

	def test_multiple_filters_and_meal_are_applied_together(self):
		Food.objects.create(
			name='Target lunch', calories=250, protein=20,
			is_recommendable=True, is_edible_food=True, is_supplement=False,
			is_nepali=True, is_vegetarian=True, meal_category='breakfast,lunch',
		)
		Food.objects.create(
			name='Not Nepali', calories=250, protein=20,
			is_recommendable=True, is_edible_food=True, is_supplement=False,
			is_nepali=False, is_vegetarian=True, meal_category='lunch',
		)
		Food.objects.create(
			name='Not Vegetarian', calories=250, protein=20,
			is_recommendable=True, is_edible_food=True, is_supplement=False,
			is_nepali=True, is_vegetarian=False, meal_category='lunch',
		)
		Food.objects.create(
			name='Wrong meal', calories=250, protein=20,
			is_recommendable=True, is_edible_food=True, is_supplement=False,
			is_nepali=True, is_vegetarian=True, meal_category='dinner',
		)

		recommendations = get_user_recommendations(
			self.user, filters=['nepali', 'veg', 'protein'], meal='lunch',
		)

		self.assertEqual([item['name'] for item in recommendations], ['Target lunch'])

	def test_api_accepts_repeated_filters_and_one_meal_choice(self):
		Food.objects.create(
			name='API target', calories=250, protein=20,
			is_recommendable=True, is_edible_food=True, is_supplement=False,
			is_nepali=True, is_vegetarian=True, meal_category='lunch,dinner',
		)
		Food.objects.create(
			name='API mismatch', calories=250, protein=20,
			is_recommendable=True, is_edible_food=True, is_supplement=False,
			is_nepali=False, is_vegetarian=True, meal_category='lunch',
		)
		request = APIRequestFactory().get(
			'/api/recommendations/',
			{'filter': ['nepali', 'veg'], 'meal': 'lunch'},
		)
		force_authenticate(request, user=self.user)

		response = GetRecommendationsView.as_view()(request)

		self.assertEqual([item['name'] for item in response.data], ['API target'])

	def test_meal_planner_quick_log_has_csrf_and_updates_budget(self):
		UserProfile.objects.create(
			user=self.user,
			date_of_birth=date(1990, 1, 1),
			gender='female',
			height=165,
			weight=65,
			activity_level='moderate',
			goal='lose',
		)
		food = Food.objects.create(
			name='Quick-log soup', calories=150, protein=12,
			carbohydrates=18, fat=4, fiber=3,
			is_recommendable=True, is_edible_food=True, is_supplement=False,
		)
		client = Client(enforce_csrf_checks=True)
		client.force_login(self.user)

		page = client.get('/meal-planner/')
		csrf_cookie = page.cookies.get('csrftoken')
		self.assertIsNotNone(csrf_cookie)

		response = client.post(
			'/api/recommendations/quick-log/',
			data=json.dumps({'food_id': food.id, 'meal_type': 'lunch', 'quantity_grams': 150}),
			content_type='application/json',
			HTTP_X_CSRFTOKEN=csrf_cookie.value,
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(MealLog.objects.filter(user=self.user).count(), 1)
		meal = MealLog.objects.get(user=self.user)
		self.assertEqual(meal.quantity, 150)
		self.assertEqual(meal.calories, 225)
		self.assertEqual(meal.protein, 18)
		self.assertEqual(meal.carbohydrates, 27)
		self.assertEqual(meal.fat, 6)
		self.assertEqual(meal.fiber, 4.5)
		self.assertEqual(_get_budget(self.user)[4], 225)
		self.assertEqual(response.json()['budget']['consumed_cal'], 225)
		self.assertContains(client.get('/meal-planner/'), 'Eaten: 225 kcal')

	def test_budget_uses_goal_calories_and_personalized_macros(self):
		UserProfile.objects.create(
			user=self.user,
			date_of_birth=date(1990, 1, 1),
			gender='female',
			height=165,
			weight=65,
			activity_level='moderate',
			goal='lose',
		)

		budget = _get_budget(self.user)

		self.assertLess(budget[0], 2000)
		self.assertEqual(budget[1], 78)


class TrainingPlotTests(TestCase):
	def test_training_plots_are_saved_for_both_models(self):
		metrics = {
			name: {
				'mae': 0.1, 'rmse': 0.2, 'r2': 0.8,
				'accuracy': 0.9, 'precision': 0.8, 'recall': 0.7, 'f1': 0.75,
			}
			for name in ('XGBoost', 'Random Forest')
		}
		predictions = {
			'XGBoost': np.array([0.2, 0.7, 0.8]),
			'Random Forest': np.array([0.3, 0.6, 0.75]),
		}
		feature_importances = {
			'XGBoost': np.array([0.2, 0.2, 0.2, 0.1, 0.1, 0.1, 0.1]),
			'Random Forest': np.array([0.15, 0.2, 0.15, 0.1, 0.1, 0.1, 0.2]),
		}

		with tempfile.TemporaryDirectory() as output_dir:
			paths = generate_training_plots(
				y_test=np.array([0.25, 0.65, 0.85]),
				predictions=predictions,
				metrics=metrics,
				feature_importances=feature_importances,
				output_dir=output_dir,
			)

			self.assertEqual(set(paths), {
				'regression_metrics', 'classification_metrics',
				'actual_vs_predicted', 'feature_importance',
			})
			self.assertTrue(all(path.is_file() and path.stat().st_size > 0 for path in paths.values()))
