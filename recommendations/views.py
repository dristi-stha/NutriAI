"""
NutriAI — Recommendation Scoring Engine & Meal Planner
Hybrid formula: 50% XGBoost quality + 30% budget fit + 20% preference history
"""
import math
import joblib
import numpy as np
import datetime
from pathlib import Path
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone
from django.http import JsonResponse
from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from myapp.models import Food, MealLog, UserProfile
from myapp.services.calculations import calculate_nutrition_baseline
from .models import RecommendationHistory
from .serializers import RecommendationHistorySerializer

# ── Model paths ──────────────────────────────────────────────────────────────
XGB_PATH = Path(__file__).resolve().parent / 'ml' / 'model.pkl'
RF_PATH  = Path(__file__).resolve().parent / 'ml' / 'rf_model.pkl'

def _load(path):
    try:
        return joblib.load(path)
    except Exception:
        return None

# Module-level cache — reloaded if None
XGB_MODEL = _load(XGB_PATH)
RF_MODEL  = _load(RF_PATH)


# ── Budget helper ─────────────────────────────────────────────────────────────
def _get_budget(user):
    """
    Returns:
        (calorie_target, prot_target, carb_target, fat_target,
         consumed_cal, consumed_prot, consumed_carb, consumed_fat,
         rem_cal, rem_prot, rem_carb, rem_fat, over_budget)
    """
    calorie_target = 2000.0
    prot_target = calorie_target * 0.20 / 4
    carb_target = calorie_target * 0.50 / 4
    fat_target = calorie_target * 0.30 / 9
    try:
        profile = getattr(user, 'userprofile', None) or getattr(user, 'profile', None)
        if profile:
            baseline = calculate_nutrition_baseline(profile)
            calorie_target = float(baseline['calorie_target'])
            prot_target = float(baseline['macro_targets']['protein'])
            carb_target = float(baseline['macro_targets']['carbohydrates'])
            fat_target = float(baseline['macro_targets']['fat'])
    except Exception:
        pass

    today = timezone.localdate() if hasattr(timezone, 'localdate') else datetime.date.today()
    logs = MealLog.objects.filter(user=user, consumed_at__date=today)

    def safe(v):
        return float(v) if v else 0.0

    consumed_cal = 0.0
    consumed_prot = 0.0
    consumed_carb = 0.0
    consumed_fat = 0.0

    for l in logs:
        if l.calories:
            consumed_cal += safe(l.calories)
            consumed_prot += safe(l.protein)
            consumed_carb += safe(l.carbohydrates)
            consumed_fat += safe(l.fat)
        elif l.food:
            serv = max(safe(l.food.serving_size), 1.0)
            qty = safe(l.quantity)
            consumed_cal += safe(l.food.calories) * qty / serv
            consumed_prot += safe(l.food.protein) * qty / serv
            consumed_carb += safe(l.food.carbohydrates) * qty / serv
            consumed_fat += safe(l.food.fat) * qty / serv

    rem_cal  = calorie_target - consumed_cal
    rem_prot = prot_target - consumed_prot
    rem_carb = carb_target - consumed_carb
    rem_fat  = fat_target - consumed_fat

    over_budget = rem_cal < 0
    rem_cal_clamped  = max(0.0, rem_cal)
    rem_prot_clamped = max(0.0, rem_prot)
    rem_carb_clamped = max(0.0, rem_carb)
    rem_fat_clamped  = max(0.0, rem_fat)

    return (calorie_target, prot_target, carb_target, fat_target,
            consumed_cal, consumed_prot, consumed_carb, consumed_fat,
            rem_cal_clamped, rem_prot_clamped, rem_carb_clamped, rem_fat_clamped, over_budget)


def _cosine(a, b):
    """Cosine similarity, range [0, 1]."""
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm < 1e-9:
        return 0.0
    return float(np.clip(np.dot(a, b) / norm, 0.0, 1.0))


def _budget_fit(food, rem_cal, rem_prot, rem_carb, rem_fat,
                calorie_target, prot_target, carb_target, fat_target, over_budget):
    cal  = float(food.calories      or 0)
    prot = float(food.protein       or 0)
    carb = float(food.carbohydrates or 0)
    fat  = float(food.fat           or 0)

    if over_budget:
        return float(np.clip(1.0 - cal / 300.0, 0.0, 1.0))

    meals = 3.0
    ref_cal  = max(calorie_target / meals, 1.0)
    ref_prot = max(prot_target / meals, 1.0)
    ref_carb = max(carb_target / meals, 1.0)
    ref_fat  = max(fat_target / meals, 1.0)

    budget_vec = np.array([rem_cal / ref_cal,
                           rem_prot / ref_prot,
                           rem_carb / ref_carb,
                           rem_fat  / ref_fat])
    food_vec   = np.array([cal / ref_cal,
                           prot / ref_prot,
                           carb / ref_carb,
                           fat  / ref_fat])
    return _cosine(budget_vec, food_vec)


def _preference_score(food_id, liked_ids, disliked_ids):
    if food_id in liked_ids:
        return 1.0
    if food_id in disliked_ids:
        return 0.0
    return 0.5


def _generate_reasons(food):
    """Build bullet highlights like 'high protein density (31g/100g); low sugar (0g/100g); low sodium (74mg/100g).'"""
    cal  = float(food.calories      or 0)
    prot = float(food.protein       or 0)
    carb = float(food.carbohydrates or 0)
    fat  = float(food.fat           or 0)
    fib  = float(getattr(food, 'fiber', 0) or 0)
    sug  = float(getattr(food, 'sugar', 0) or 0)
    sod  = float(getattr(food, 'sodium', 0) or 0)

    phrases = []
    
    # Protein density check
    if prot >= 15 or (cal > 0 and (prot * 4 / cal) >= 0.25):
        phrases.append(f"high protein density ({round(prot)}g/100g)")
    elif prot >= 8:
        phrases.append(f"good source of protein ({round(prot)}g/100g)")

    # Fiber check
    if fib >= 5:
        phrases.append(f"rich in fiber ({round(fib)}g/100g)")
    elif fib >= 2.5:
        phrases.append(f"contains fiber ({round(fib)}g/100g)")

    # Sugar check
    if sug <= 2:
        phrases.append(f"low sugar ({round(sug)}g/100g)")

    # Sodium check
    if sod <= 150:
        phrases.append(f"low sodium ({round(sod)}mg/100g)")
    elif sod <= 300:
        phrases.append(f"moderate sodium ({round(sod)}mg/100g)")

    # Fat check
    if fat <= 3 and cal > 0:
        phrases.append(f"low fat ({round(fat, 1)}g/100g)")

    if not phrases:
        phrases = ["balanced nutritional profile", "fits daily wellness goal"]

    return "; ".join(phrases) + "."


def get_user_recommendations(user, filters=None, meal=None):
    """Core function to calculate ranked recommendations for a user."""
    global XGB_MODEL, RF_MODEL
    if XGB_MODEL is None:
        XGB_MODEL = _load(XGB_PATH)
    if RF_MODEL is None:
        RF_MODEL = _load(RF_PATH)

    # 1. User profile
    profile = getattr(user, 'userprofile', None) or getattr(user, 'profile', None)
    dietary_pref = 'none'
    health_cond = ''
    allergies_list = []
    
    if profile:
        if hasattr(profile, 'dietary_preference'):
            dietary_pref = profile.dietary_preference or 'none'
        elif hasattr(profile, 'dietary_tags'):
            tag_names = [t.name.lower() for t in profile.dietary_tags.all()]
            if 'vegan' in tag_names:
                dietary_pref = 'vegan'
            elif 'vegetarian' in tag_names:
                dietary_pref = 'vegetarian'

        if hasattr(profile, 'health_conditions'):
            health_cond = (profile.health_conditions or '').lower()

        if hasattr(profile, 'allergies'):
            if hasattr(profile.allergies, 'all'):
                allergies_list = [a.name.lower() for a in profile.allergies.all()]
            elif isinstance(profile.allergies, str):
                allergies_list = [a.strip().lower() for a in profile.allergies.split(',') if a.strip()]
        if getattr(profile, 'custom_allergies', ''):
            allergies_list.extend(
                item.strip().lower()
                for item in profile.custom_allergies.replace(';', ',').split(',')
                if item.strip()
            )

    # 2. Daily budget
    (calorie_target, prot_target, carb_target, fat_target,
     consumed_cal, consumed_prot, consumed_carb, consumed_fat,
     rem_cal, rem_prot, rem_carb, rem_fat,
     over_budget) = _get_budget(user)

    # 3. Behavioral history
    liked_ids = set(RecommendationHistory.objects.filter(
        user=user, feedback='liked').values_list('food_id', flat=True))
    disliked_ids = set(RecommendationHistory.objects.filter(
        user=user, feedback='disliked').values_list('food_id', flat=True))

    # Apply requested filters before scoring and limiting the results.
    active_filters = set(filters or ()) & {'nepali', 'veg', 'protein', 'preferred'}
    foods = Food.objects.filter(
        is_recommendable=True,
        is_edible_food=True,
        is_supplement=False,
    )
    if 'nepali' in active_filters:
        foods = foods.filter(is_nepali=True)
    if 'veg' in active_filters:
        foods = foods.filter(is_vegetarian=True)
    if 'protein' in active_filters:
        foods = foods.filter(protein__gte=15)
    if 'preferred' in active_filters:
        foods = foods.filter(id__in=liked_ids)

    if dietary_pref == 'vegetarian':
        foods = foods.filter(is_vegetarian=True)
    elif dietary_pref == 'vegan':
        foods = foods.filter(is_vegan=True)

    if 'diabetes' in health_cond:
        foods = foods.filter(sugar__lt=15)
    if 'hypertension' in health_cond:
        foods = foods.filter(sodium__lt=300)

    # Exclude allergens if model has allergen tags
    if allergies_list:
        for allergen in allergies_list:
            foods = foods.exclude(allergens__name__iexact=allergen).exclude(
                name__icontains=allergen
            )

    foods = list(foods)
    meal = (meal or '').strip().lower()
    if meal in {'breakfast', 'lunch', 'dinner', 'snack'}:
        foods = [
            food for food in foods
            if {'anytime', meal}.intersection(
                category.strip()
                for category in food.meal_category.split(',')
            )
        ]
    if not foods:
        return []

    # 5. Score each food
    results = []
    for food in foods:
        cal  = float(food.calories      or 0)
        prot = float(food.protein       or 0)
        carb = float(food.carbohydrates or 0)
        fat  = float(food.fat           or 0)
        fib  = float(getattr(food, 'fiber',  0) or 0)
        sug  = float(getattr(food, 'sugar',  0) or 0)
        sod  = float(getattr(food, 'sodium', 0) or 0)

        feat = np.array([[cal, prot, carb, fat, fib, sug, sod]])

        # XGBoost nutritional quality score (0-1)
        xgb_score = float(np.clip(
            XGB_MODEL.predict(feat)[0] if XGB_MODEL else 0.5, 0.0, 1.0))

        # Random Forest score for comparison (0-1)
        rf_score = float(np.clip(
            RF_MODEL.predict(feat)[0] if RF_MODEL else xgb_score, 0.0, 1.0))

        # Budget fit via cosine similarity (handles over-budget case)
        budget_fit = _budget_fit(food, rem_cal, rem_prot, rem_carb, rem_fat,
                                 calorie_target, prot_target, carb_target, fat_target,
                                 over_budget)

        # Behavioral preference
        pref = _preference_score(food.id, liked_ids, disliked_ids)

        # Hybrid formula: 50% XGBoost + 30% budget fit + 20% preference
        hybrid = 0.50 * xgb_score + 0.30 * budget_fit + 0.20 * pref
        hybrid = float(np.clip(hybrid, 0.0, 1.0))

        results.append({
            'id':            food.id,
            'name':          food.name,
            'name_nepali':   getattr(food, 'name_nepali', '') or '',
            'category':      str(food.category) if food.category else '',
            'calories':      round(cal),
            'protein':       round(prot, 1),
            'carbohydrates': round(carb, 1),
            'fat':           round(fat, 1),
            'fiber':         round(fib, 1),
            'sugar':         round(sug, 1),
            'sodium':        round(sod),
            'is_vegetarian': getattr(food, 'is_vegetarian', False),
            'is_vegan':      getattr(food, 'is_vegan', False),
            'is_nepali':     getattr(food, 'is_nepali', False),
            'food_type':     food.food_type,
            'meal_category': food.meal_category,
            'preparation_state': food.preparation_state,
            'recommendation_group': food.recommendation_group,
            'serving_size':  getattr(food, 'serving_size', 100),
            'serving_unit':  getattr(food, 'serving_unit', 'g'),
            # Scores
            'score':         round(hybrid, 4),
            'match_percent': round(hybrid * 100, 1),
            'xgb_score':     round(xgb_score * 100, 1),
            'rf_score':      round(rf_score * 100, 1),
            'budget_fit':    round(budget_fit * 100),
            # Detailed reason highlight
            'reason':        _generate_reasons(food),
            # Behavioral tags
            'liked':         food.id in liked_ids,
            'disliked':      food.id in disliked_ids,
        })

    # Sort descending by hybrid score
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:24]


# ── Web Template View: /meal-planner/ ─────────────────────────────────────────
@login_required
@ensure_csrf_cookie
def meal_planner_view(request):
    """Renders the Meal Planner / Recommendations page."""
    budget_info = _get_budget(request.user)
    context = {
        'calorie_target': round(budget_info[0]),
        'prot_target':    round(budget_info[1], 1),
        'carb_target':    round(budget_info[2], 1),
        'fat_target':     round(budget_info[3], 1),
        'consumed_cal':   round(budget_info[4]),
        'consumed_prot':  round(budget_info[5], 1),
        'consumed_carb':  round(budget_info[6], 1),
        'consumed_fat':   round(budget_info[7], 1),
        'rem_cal':        round(budget_info[8]),
        'rem_prot':       round(budget_info[9], 1),
        'rem_carb':       round(budget_info[10], 1),
        'rem_fat':        round(budget_info[11], 1),
        'over_budget':    budget_info[12],
    }
    return render(request, 'meal_planner.html', context)


# ── API Views ─────────────────────────────────────────────────────────────────
class GetRecommendationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        results = get_user_recommendations(
            request.user,
            filters=request.query_params.getlist('filter'),
            meal=request.query_params.get('meal'),
        )
        return Response(results)


class RecommendationFeedbackView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, food_id):
        action = request.data.get('feedback', 'liked') # 'liked', 'disliked', or 'neutral'
        try:
            food = Food.objects.get(id=food_id)
            existing = RecommendationHistory.objects.filter(user=request.user, food=food).first()

            if existing and existing.feedback == action:
                # Clicking the same button again toggles it off (unlike/undislike)
                existing.feedback = 'neutral'
                existing.save()
                new_state = 'neutral'
            else:
                RecommendationHistory.objects.update_or_create(
                    user=request.user, food=food,
                    defaults={'feedback': action}
                )
                new_state = action

            return Response({
                'status': 'saved',
                'food_id': food_id,
                'feedback': new_state,
                'liked': new_state == 'liked',
                'disliked': new_state == 'disliked'
            })
        except Food.DoesNotExist:
            return Response({'error': 'Food not found'}, status=404)


class QuickLogMealView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        food_id = request.data.get('food_id')
        meal_type = request.data.get('meal_type', 'lunch')
        try:
            quantity_grams = float(request.data.get('quantity_grams', 100))
        except (TypeError, ValueError):
            return Response({'error': 'Portion size must be a number of grams.'}, status=400)

        if not math.isfinite(quantity_grams) or quantity_grams <= 0:
            return Response({'error': 'Portion size must be greater than zero grams.'}, status=400)

        try:
            food = Food.objects.get(id=food_id)
            portion_factor = quantity_grams / 100

            cal = float(food.calories or 0) * portion_factor
            prot = float(food.protein or 0) * portion_factor
            carb = float(food.carbohydrates or 0) * portion_factor
            fat = float(food.fat or 0) * portion_factor
            fib = float(getattr(food, 'fiber', 0) or 0) * portion_factor

            MealLog.objects.create(
                user=request.user,
                food=food,
                food_name=food.name,
                meal_type=meal_type,
                quantity=quantity_grams,
                calories=round(cal, 1),
                protein=round(prot, 1),
                carbohydrates=round(carb, 1),
                fat=round(fat, 1),
                fiber=round(fib, 1),
                consumed_at=timezone.now(),
            )

            # Mark in recommendation history if exists
            RecommendationHistory.objects.filter(user=request.user, food=food).update(is_eaten=True)

            budget_info = _get_budget(request.user)
            budget = {
                'calorie_target': round(budget_info[0]),
                'prot_target': round(budget_info[1], 1),
                'carb_target': round(budget_info[2], 1),
                'fat_target': round(budget_info[3], 1),
                'consumed_cal': round(budget_info[4]),
                'consumed_prot': round(budget_info[5], 1),
                'consumed_carb': round(budget_info[6], 1),
                'consumed_fat': round(budget_info[7], 1),
                'rem_cal': round(budget_info[8]),
                'rem_prot': round(budget_info[9], 1),
                'rem_carb': round(budget_info[10], 1),
                'rem_fat': round(budget_info[11], 1),
                'over_budget': budget_info[12],
            }

            return Response({
                'status': 'logged',
                'message': f"{food.name} added to your {meal_type} log!",
                'budget': budget,
            })
        except Food.DoesNotExist:
            return Response({'error': 'Food not found'}, status=404)
