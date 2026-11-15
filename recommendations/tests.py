from django.test import TestCase
from django.contrib.auth.models import User
from myapp.models import Food
from rest_framework.test import APIRequestFactory, force_authenticate
from recommendations.views import GetRecommendationsView, get_user_recommendations


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
