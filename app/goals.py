"""Цели и пороги: особые числа, на которых оверлей празднует, и цель для отсчёта «осталось N».

Цель тоже считается особым числом: когда счёт до неё дошёл, оверлей празднует.
"""

DEFAULT_MILESTONES = [10, 50, 100]
MAX_MILESTONES = 20
MAX_VALUE = 1_000_000


class GoalsError(ValueError):
    pass


def clean_milestones(values: list[int]) -> list[int]:
    """Особые числа по возрастанию, без повторов; ошибка — если число вне 1…MAX_VALUE."""
    result = sorted(set(values))
    if any(not 1 <= value <= MAX_VALUE for value in result):
        raise GoalsError(f"Особые числа — от 1 до {MAX_VALUE}")
    if len(result) > MAX_MILESTONES:
        raise GoalsError(f"Не больше {MAX_MILESTONES} особых чисел")
    return result


def clean_goal(goal: int) -> int:
    """0 — цели нет."""
    if not 0 <= goal <= MAX_VALUE:
        raise GoalsError(f"Цель — от 1 до {MAX_VALUE}, 0 — без цели")
    return goal


def reached(milestones: list[int], goal: int, before: int, after: int) -> int | None:
    """Наибольшее особое число (или цель), которое счёт перешёл при росте before → after."""
    passed = [value for value in [*milestones, goal] if value and before < value <= after]
    return max(passed, default=None)
