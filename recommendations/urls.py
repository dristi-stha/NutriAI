from django.urls import path
from . import views

urlpatterns = [
    path('meal-planner/', views.meal_planner_view, name='meal_planner'),
    path('api/recommendations/', views.GetRecommendationsView.as_view(), name='api_recommendations'),
    path('api/recommendations/feedback/<int:food_id>/', views.RecommendationFeedbackView.as_view(), name='api_recommendation_feedback'),
    path('api/recommendations/quick-log/', views.QuickLogMealView.as_view(), name='api_recommendations_quick_log'),
]
