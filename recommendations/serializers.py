from rest_framework import serializers
from .models import RecommendationHistory
from myapp.models import Food

class FoodSerializer(serializers.ModelSerializer):
    class Meta:
        model = Food
        fields = '__all__'

class RecommendationHistorySerializer(serializers.ModelSerializer):
    food_name = serializers.ReadOnlyField(source='food.name')

    class Meta:
        model = RecommendationHistory
        fields = ['id', 'user', 'food', 'food_name', 'recommended_at', 'score', 'user_rating', 'is_eaten', 'feedback']
        read_only_fields = ['user', 'recommended_at']
