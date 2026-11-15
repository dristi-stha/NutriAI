from django.test import TestCase
from django.core.management import call_command
from myapp.models import Food
from io import StringIO


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
