"""Groq-backed chatbot service.

Keep model and tool orchestration here so views stay independent of the AI provider.
"""

import json
import os
from datetime import date, timedelta

from openai import APIError, OpenAI
from django.utils import timezone

from myapp.models import MealLog, UserProfile
from recommendations.models import RecommendationHistory


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-20b"
SYSTEM_PROMPT = (
    "You are NutriAI, a helpful nutrition assistant. Give clear, practical general "
    "nutrition guidance. Do not diagnose medical conditions; recommend a qualified "
    "professional for medical concerns. Stay within nutrition and health topics. Use "
    "get_user_health_profile before personalized food advice so you can account for "
    "the user's saved allergens. Use get_recent_meal_history when asked about meals "
    "they have eaten. Use get_personalized_food_recommendations when they ask for "
    "meal ideas; these are current suggestions from the app's recommender, not a log "
    "of every recommendation previously displayed. Use get_user_food_preferences "
    "when asked what foods they have liked, disliked, or preferred. Never suggest "
    "foods that match the user's listed allergens, and say when allergen information "
    "is unavailable."
)


def _age_in_years(date_of_birth):
    """Return the user's age without exposing their exact birth date."""
    if not date_of_birth:
        return None

    today = date.today()
    return today.year - date_of_birth.year - (
        (today.month, today.day) < (date_of_birth.month, date_of_birth.day)
    )


def get_user_health_profile(user):
    """Return the authenticated user's non-identifying nutrition profile as JSON."""
    profile = UserProfile.objects.filter(user=user).first()

    if not profile:
        return json.dumps({"profile_available": False, "allergies": [], "custom_allergies": []})

    custom_allergies = [
        item.strip()
        for item in profile.custom_allergies.replace(';', ',').split(',')
        if item.strip()
    ]

    return json.dumps(
        {
            "profile_available": True,
            "age_years": _age_in_years(profile.date_of_birth),
            "gender": profile.get_gender_display() or None,
            "height_cm": profile.height,
            "profile_weight_kg": profile.weight,
            "activity_level": profile.get_activity_level_display() or None,
            "goal": profile.get_goal_display() or None,
            "daily_calorie_target": profile.daily_calorie_target,
            "allergies": list(profile.allergies.order_by('name').values_list('name', flat=True)),
            "custom_allergies": custom_allergies,
        }
    )


def get_recent_meal_history(user, days=7, limit=10):
    """Return the user's recent logged meals without exposing other users' data."""
    days = max(1, min(int(days), 30))
    limit = max(1, min(int(limit), 20))
    start_date = timezone.localdate() - timedelta(days=days - 1)
    meals = MealLog.objects.filter(
        user=user,
        consumed_at__date__gte=start_date,
        consumed_at__date__lte=timezone.localdate(),
    ).order_by('-consumed_at')[:limit]

    return json.dumps(
        {
            "days": days,
            "meals": [
                {
                    "food": meal.food_name,
                    "meal_type": meal.get_meal_type_display(),
                    "consumed_at": meal.consumed_at.isoformat(),
                    "portion_grams": meal.quantity,
                    "calories": meal.calories,
                    "protein_g": meal.protein,
                    "carbohydrates_g": meal.carbohydrates,
                    "fat_g": meal.fat,
                    "fiber_g": meal.fiber,
                }
                for meal in meals
            ],
        }
    )


def get_personalized_food_recommendations(user, limit=5):
    """Return a small set of current recommendations from the meal planner engine."""
    limit = max(1, min(int(limit), 8))

    from recommendations.views import get_user_recommendations

    recommendations = get_user_recommendations(user)[:limit]
    return json.dumps(
        {
            "recommendations": [
                {
                    "name": item["name"],
                    "meal_category": item["meal_category"],
                    "recommendation_group": item["recommendation_group"],
                    "calories_per_100g": item["calories"],
                    "protein_g_per_100g": item["protein"],
                    "carbohydrates_g_per_100g": item["carbohydrates"],
                    "fat_g_per_100g": item["fat"],
                    "reason": item["reason"],
                }
                for item in recommendations
            ]
        }
    )


def get_user_food_preferences(user, limit=20):
    """Return this user's recent liked and disliked foods from the meal planner."""
    limit = max(1, min(int(limit), 30))
    history = RecommendationHistory.objects.filter(
        user=user,
        feedback__in=('liked', 'disliked'),
    ).select_related('food').order_by('-recommended_at')[:limit]

    preferences = {"liked": [], "disliked": []}
    for entry in history:
        preferences[entry.feedback].append(
            {
                "name": entry.food.name,
                "category": str(entry.food.category) if entry.food.category else None,
                "recommendation_group": entry.food.recommendation_group,
                "calories_per_100g": entry.food.calories,
                "recorded_at": entry.recommended_at.isoformat(),
            }
        )

    return json.dumps(preferences)


tools = [
    {
        "type": "function",
        "function": {
            "name": "get_user_health_profile",
            "description": (
                "Get the current authenticated user's saved nutrition profile, including "
                "their age, height, weight, activity level, goal, calorie target, and "
                "both selected and custom-listed food allergies."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_meal_history",
            "description": (
                "Get the current authenticated user's recently logged meals, portions, "
                "times, and nutrition totals. Use when asked what they have eaten."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "minimum": 1, "maximum": 30},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_personalized_food_recommendations",
            "description": (
                "Get current food ideas ranked by the app's personalized meal planner. "
                "Results account for the user's diet, allergies, and remaining daily budget."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_food_preferences",
            "description": (
                "Get the current authenticated user's recent foods marked liked/preferred "
                "or disliked in the meal planner. Use when asked about their food preferences."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30},
                },
                "additionalProperties": False,
            },
        },
    },
]


# Map the model's function name to the server-side implementation.
available_functions = {
    "get_user_health_profile": get_user_health_profile,
    "get_recent_meal_history": get_recent_meal_history,
    "get_personalized_food_recommendations": get_personalized_food_recommendations,
    "get_user_food_preferences": get_user_food_preferences,
}


class ChatbotError(Exception):
    """The chatbot provider could not complete a request."""


class ChatbotConfigurationError(ChatbotError):
    """The server is missing its Groq API key."""


def get_chatbot_reply(conversation, user):
    """Return one assistant reply for a browser-safe conversation history.

    The authenticated user is passed only to server-side tool functions, never to the model.
    """
    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key:
        raise ChatbotConfigurationError

    client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *conversation]

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=500,
            tools=tools,
            tool_choice="auto",
        )
    except APIError as error:
        raise ChatbotError from error

    assistant_message = response.choices[0].message

    for _ in range(3):
        if not assistant_message.tool_calls:
            break

        messages.append(assistant_message)

        for tool_call in assistant_message.tool_calls:
            function = available_functions.get(tool_call.function.name)

            if not function:
                tool_result = json.dumps({"error": "Requested tool is unavailable."})
            else:
                try:
                    arguments = json.loads(tool_call.function.arguments or "{}")
                    tool_result = function(user=user, **arguments)
                except (TypeError, ValueError) as error:
                    tool_result = json.dumps({"error": f"Tool could not run: {error}"})

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                }
            )

        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=0.4,
                max_tokens=500,
                tools=tools,
                tool_choice="auto",
            )
        except APIError as error:
            raise ChatbotError from error

        assistant_message = response.choices[0].message

    if assistant_message.tool_calls:
        raise ChatbotError

    reply = assistant_message.content
    if not reply:
        raise ChatbotError

    return reply
