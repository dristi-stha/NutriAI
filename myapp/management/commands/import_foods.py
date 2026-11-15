import csv
import math
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from myapp.models import Food, FoodCategory

class Command(BaseCommand):
    help = 'Replace the recommendable food catalog from the labeled CSV file'

    csv_filename = 'destination_with_food_attributes.csv'
    required_columns = {
        'food_id', 'name', 'category', 'calories', 'protein', 'carbohydrates',
        'fat', 'fiber', 'sugar', 'sodium', 'serving_size_g', 'food_type',
        'meal_category', 'is_recommendable', 'is_supplement', 'is_edible_food',
        'preparation_state', 'recommendation_group',
    }

    @staticmethod
    def parse_bool(value):
        normalized = (value or '').strip().lower()
        if normalized in {'true', '1', 'yes'}:
            return True
        if normalized in {'false', '0', 'no', ''}:
            return False
        raise ValueError(f'Invalid boolean value: {value!r}')

    @staticmethod
    def parse_number(value, default=0):
        number = float(value) if (value or '').strip() else default
        if not math.isfinite(number):
            raise ValueError(f'Invalid numeric value: {value!r}')
        return number

    def handle(self, *args, **kwargs):
        csv_file = Path(settings.BASE_DIR) / 'myapp' / 'data' / self.csv_filename
        if not csv_file.exists():
            raise CommandError(f'CSV file not found: {csv_file}')

        with open(csv_file, newline='', encoding='utf-8-sig') as source:
            reader = csv.DictReader(source)
            missing_columns = self.required_columns - set(reader.fieldnames or [])
            if missing_columns:
                raise CommandError(
                    f"CSV is missing required columns: {', '.join(sorted(missing_columns))}"
                )
            rows = list(reader)

        if not rows:
            raise CommandError('CSV contains no food rows; database was not changed.')

        prepared_rows = []
        for line_number, row in enumerate(rows, start=2):
            name = (row.get('name') or '').strip()
            if not name:
                raise CommandError(f'CSV row {line_number} has no food name.')

            try:
                prepared_rows.append({
                    'row': row,
                    'name': name,
                    'food_id': (row.get('food_id') or '').strip(),
                    'numbers': {
                        field: self.parse_number(row.get(field))
                        for field in ('calories', 'protein', 'carbohydrates', 'fat', 'fiber', 'sugar', 'sodium')
                    },
                    'serving_size': self.parse_number(row.get('serving_size_g'), 100),
                    'booleans': {
                        field: self.parse_bool(row.get(field))
                        for field in ('is_vegetarian', 'is_vegan', 'is_nepali', 'is_recommendable', 'is_supplement', 'is_edible_food')
                    },
                })
            except ValueError as error:
                raise CommandError(f'Invalid value on CSV row {line_number}: {error}') from error

        with transaction.atomic():
            # Keep historical meal references intact, but exclude foods absent from this dataset.
            Food.objects.update(is_recommendable=False)

            for item in prepared_rows:
                row = item['row']
                source_key = f"destination-food:{item['food_id']}" if item['food_id'] else ''
                food = Food.objects.filter(source_key=source_key).first() if source_key else None
                if food is None:
                    food = Food.objects.filter(name=item['name']).filter(
                        Q(source_key__isnull=True) | Q(source_key='')
                    ).order_by('pk').first()

                category_name = (row.get('category') or '').strip() or 'General'
                category, _ = FoodCategory.objects.get_or_create(name=category_name)
                if food is None:
                    food = Food(name=item['name'])

                food.name = item['name']
                food.name_nepali = (row.get('name_nepali') or '').strip()
                food.category = category
                for field, value in item['numbers'].items():
                    setattr(food, field, value)
                for field, value in item['booleans'].items():
                    setattr(food, field, value)
                food.food_type = (row.get('food_type') or '').strip().lower()
                food.meal_category = (row.get('meal_category') or '').strip().lower()
                food.preparation_state = (row.get('preparation_state') or '').strip().lower()
                food.recommendation_group = (row.get('recommendation_group') or '').strip().lower()
                food.serving_size = item['serving_size'] or 100
                food.serving_unit = 'g'
                food.source_key = source_key or None
                food.source_name = (row.get('data_source') or '').strip()
                food.save()

        self.stdout.write(self.style.SUCCESS(
            f'Imported {len(prepared_rows)} foods from {self.csv_filename}; '
            'older catalog entries were retained for existing logs but excluded from recommendations.'
        ))
