import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase
from django.core.management import call_command
from io import StringIO

from myapp.models import Food, MealLog, UserProfile
from myapp.services.calculations import calculate_nutrition_baseline
from myapp.services.chatbot import (
	get_chatbot_reply,
	get_personalized_food_recommendations,
	get_recent_meal_history,
	get_user_health_profile,
	get_user_food_preferences,
)


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


class ChatbotDataToolTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='chatbot-data-test')
		self.profile = UserProfile.objects.create(
			user=self.user,
			custom_allergies='Pollen; shellfish',
		)

	def test_health_profile_tool_includes_selected_and_custom_allergies(self):
		from myapp.models import Allergen

		self.profile.allergies.add(Allergen.objects.create(name='Peanuts'))
		result = json.loads(get_user_health_profile(self.user))

		self.assertEqual(result['allergies'], ['Peanuts'])
		self.assertEqual(result['custom_allergies'], ['Pollen', 'shellfish'])

	def test_meal_history_tool_returns_only_current_users_recent_logs(self):
		MealLog.objects.create(
			user=self.user, food_name='Lentil soup', meal_type='lunch',
			quantity=150, calories=225,
		)
		other_user = User.objects.create_user(username='other-meal-user')
		MealLog.objects.create(
			user=other_user, food_name='Other meal', meal_type='dinner',
			quantity=100, calories=200,
		)

		result = json.loads(get_recent_meal_history(self.user))

		self.assertEqual(len(result['meals']), 1)
		self.assertEqual(result['meals'][0]['food'], 'Lentil soup')
		self.assertEqual(result['meals'][0]['portion_grams'], 150)

	def test_recommendation_tool_uses_personalized_engine_and_excludes_allergens(self):
		from myapp.models import Allergen

		peanuts = Allergen.objects.create(name='Peanuts')
		self.profile.allergies.add(peanuts)
		safe_food = Food.objects.create(
			name='Lentil meal', calories=220, protein=18,
			is_recommendable=True, is_edible_food=True, is_supplement=False,
		)
		unsafe_food = Food.objects.create(
			name='Peanut snack', calories=250, protein=10,
			is_recommendable=True, is_edible_food=True, is_supplement=False,
		)
		unsafe_food.allergens.add(peanuts)
		custom_allergen_food = Food.objects.create(
			name='Shellfish stew', calories=210, protein=16,
			is_recommendable=True, is_edible_food=True, is_supplement=False,
		)

		result = json.loads(get_personalized_food_recommendations(self.user, limit=5))
		recommended_names = [item['name'] for item in result['recommendations']]

		self.assertIn(safe_food.name, recommended_names)
		self.assertNotIn(unsafe_food.name, recommended_names)
		self.assertNotIn(custom_allergen_food.name, recommended_names)

	def test_chatbot_can_call_multiple_tools_before_replying(self):
		def tool_call(call_id, name):
			return SimpleNamespace(
				id=call_id,
				function=SimpleNamespace(name=name, arguments='{}'),
			)

		messages = [
			SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
				tool_calls=[tool_call('profile-call', 'get_user_health_profile')],
				content=None,
			))]),
			SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
				tool_calls=[tool_call('history-call', 'get_recent_meal_history')],
				content=None,
			))]),
			SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
				tool_calls=None,
				content='Here is your summary.',
			))]),
		]

		with patch.dict('os.environ', {'GROQ_API_KEY': 'test-key'}):
			with patch('myapp.services.chatbot.OpenAI') as openai_class:
				client = openai_class.return_value
				client.chat.completions.create.side_effect = messages

				reply = get_chatbot_reply(
					[{'role': 'user', 'content': 'What have I eaten and what should I try?'}],
					self.user,
				)

		self.assertEqual(reply, 'Here is your summary.')
		self.assertEqual(client.chat.completions.create.call_count, 3)

	def test_food_preferences_tool_returns_only_current_users_likes_and_dislikes(self):
		from recommendations.models import RecommendationHistory

		liked_food = Food.objects.create(name='Lentil bowl', calories=220)
		disliked_food = Food.objects.create(name='Sweet pastry', calories=350)
		RecommendationHistory.objects.create(
			user=self.user, food=liked_food, feedback='liked',
		)
		RecommendationHistory.objects.create(
			user=self.user, food=disliked_food, feedback='disliked',
		)
		other_user = User.objects.create_user(username='other-preference-user')
		other_food = Food.objects.create(name='Other user food', calories=100)
		RecommendationHistory.objects.create(
			user=other_user, food=other_food, feedback='liked',
		)

		result = json.loads(get_user_food_preferences(self.user))

		self.assertEqual([item['name'] for item in result['liked']], ['Lentil bowl'])
		self.assertEqual([item['name'] for item in result['disliked']], ['Sweet pastry'])
