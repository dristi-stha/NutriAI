import csv
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from myapp.models import Food, FoodCategory

class Command(BaseCommand):
    help = 'Import foods from CSV file into the database'

    def handle(self, *args, **kwargs):
        # csv_file = Path(settings.BASE_DIR) / 'myapp' / 'data' / 'nepali_food_data.csv'
        # csv_file = Path(settings.BASE_DIR) / 'myapp' / 'data' / 'nepali_food_data_extra.csv'
        #csv_file = Path(settings.BASE_DIR) / 'myapp' / 'data' / 'fao_food.csv'
        csv_file = Path(settings.BASE_DIR) / 'myapp' / 'data' / 'destination (1).csv'
        if not csv_file.exists():
            # Try alternate path
            csv_file = Path(settings.BASE_DIR) / 'data' / 'nepali_food_data.csv'
        
        if not csv_file.exists():
            self.stdout.write(self.style.ERROR(f"CSV file not found at {csv_file}"))
            return

        with open(csv_file, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                cat_name = row.get('category', 'General')
                category, _ = FoodCategory.objects.get_or_create(
                    name=cat_name,
                    defaults={'description': f'Category for {cat_name}'}
                )

                Food.objects.update_or_create(
                    name=row['name'],
                    defaults={
                        'name_nepali': row.get('name_nepali', ''),
                        'category': category,
                        'calories': float(row.get('calories', 0)),
                        'protein': float(row.get('protein', 0)),
                        'carbohydrates': float(row.get('carbohydrates', 0)),
                        'fat': float(row.get('fat', 0)),
                        'fiber': float(row.get('fiber', 0)),
                        'sugar': float(row.get('sugar', 0)),
                        'sodium': float(row.get('sodium', 0)),
                        'is_vegetarian': row.get('is_vegetarian', 'False').lower() == 'true',
                        'is_vegan': row.get('is_vegan', 'False').lower() == 'true',
                        'is_nepali': row.get('is_nepali', 'False').lower() == 'true',
                        'serving_size': float(row.get('serving_size_g', 100)),
                        'serving_unit': 'g',
                    }
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f"Successfully imported {count} foods into database!"))
