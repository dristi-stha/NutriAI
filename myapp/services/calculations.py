from datetime import date


def calculate_age(date_of_birth):
    if not date_of_birth:
        return None

    today = date.today()

    age = today.year - date_of_birth.year

    if (today.month, today.day) < (
        date_of_birth.month,
        date_of_birth.day
    ):
        age -= 1

    return age


def calculate_bmr(
    weight,
    height,
    age,
    gender
):
    if not weight or not height or not age:
        return None

    gender = (gender or "").strip().lower()

    if gender == "male":

        bmr = (
            10 * weight
            + 6.25 * height
            - 5 * age
            + 5
        )

    elif gender == "female":

        bmr = (
            10 * weight
            + 6.25 * height
            - 5 * age
            - 161
        )

    else:
        bmr = (
            10 * weight
            + 6.25 * height
            - 5 * age
            - 78
        )

    return round(bmr)


def calculate_tdee(
    bmr,
    activity_level
):
    if not bmr or not activity_level:
        return None

    activity_level = (activity_level or "").strip().lower()
    activity_level = {
        "lightly active": "light",
        "moderately active": "moderate",
        "very active": "very",
        "active": "very",
    }.get(activity_level, activity_level)

    activity_multipliers = {

        "sedentary": 1.2,

        "light": 1.375,

        "moderate": 1.55,

        "very": 1.725,
    }

    multiplier = activity_multipliers.get(
        activity_level
    )

    if not multiplier:
        return None

    tdee = bmr * multiplier

    return round(tdee)


def calculate_calorie_target(profile, tdee):
    manual_target = profile.daily_calorie_target
    if manual_target and manual_target > 0:
        return round(manual_target)
    if not tdee:
        return 2000

    goal = (profile.goal or "maintain").strip().lower()
    goal = {
        "lose weight": "lose",
        "maintain weight": "maintain",
        "gain weight": "gain",
    }.get(goal, goal)
    goal_multipliers = {
        "lose": 0.85,
        "maintain": 1.0,
        "gain": 1.10,
    }
    return round(tdee * goal_multipliers.get(goal, 1.0))


def calculate_macro_targets(profile, calorie_target):
    weight = profile.weight or 0
    protein = round(weight * 1.2, 1) if weight > 0 else round(calorie_target * 0.20 / 4, 1)
    fat = round(calorie_target * 0.30 / 9, 1)
    carbohydrates = round(max(0, (calorie_target - protein * 4 - fat * 9) / 4), 1)
    return {
        "protein": protein,
        "carbohydrates": carbohydrates,
        "fat": fat,
    }


def calculate_nutrition_baseline(profile):
    """
    Calculate the user's basic nutrition metrics.

    This function does NOT decide the user's final
    calorie or macro goals. Those will be handled
    later by the AI recommendation engine.
    """

    age = calculate_age(
        profile.date_of_birth
    )

    bmr = calculate_bmr(
        weight=profile.weight,
        height=profile.height,
        age=age,
        gender=profile.gender
    )

    tdee = calculate_tdee(
        bmr=bmr,
        activity_level=profile.activity_level
    )

    calorie_target = calculate_calorie_target(profile, tdee)
    macro_targets = calculate_macro_targets(profile, calorie_target)

    return {
        "age": age,
        "bmr": bmr,
        "tdee": tdee,
        "calorie_target": calorie_target,
        "macro_targets": macro_targets,
    }