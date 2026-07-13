"""Interactive collection of a UserProfile from the terminal.

The parsing helpers are pure functions (easy to unit test). `collect_profile`
takes injectable input/output callables so the interactive flow can be tested
without real stdin.
"""

from __future__ import annotations

from typing import Callable

from .profile import ActivityLevel, Goal, Sex, UserProfile

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]

# Ordered option lists — index shown to the user is 1-based.
_SEX_OPTIONS: list[Sex] = ["male", "female"]
_ACTIVITY_OPTIONS: list[ActivityLevel] = [
    "sedentary",
    "light",
    "moderate",
    "active",
    "very_active",
]
_GOAL_OPTIONS: list[Goal] = ["lose_weight", "gain_muscle", "maintain"]

_ACTIVITY_HELP = {
    "sedentary": "little or no exercise",
    "light": "1-3 days/week",
    "moderate": "3-5 days/week",
    "active": "6-7 days/week",
    "very_active": "hard exercise or physical job",
}


class IntakeError(ValueError):
    """Raised when a raw answer can't be parsed into a valid value."""


def _clean(raw: str) -> str:
    """Strip whitespace plus invisible junk that survives str.strip().

    A leading BOM (U+FEFF) or zero-width space (U+200B) can ride in via piped
    input or copy-paste; str.strip() leaves them, which then breaks int()/float().
    """
    return raw.strip().strip("\ufeff\u200b").strip()


def parse_int_in_range(raw: str, lo: int, hi: int) -> int:
    """Parse an integer and require lo <= value <= hi."""
    text = _clean(raw)
    try:
        value = int(text)
    except ValueError as exc:
        raise IntakeError(f"'{text}' is not a whole number") from exc
    if not lo <= value <= hi:
        raise IntakeError(f"value must be between {lo} and {hi}")
    return value


def parse_positive_float(raw: str) -> float:
    """Parse a float and require it to be > 0."""
    text = _clean(raw)
    try:
        value = float(text.replace(",", "."))
    except ValueError as exc:
        raise IntakeError(f"'{text}' is not a number") from exc
    if value <= 0:
        raise IntakeError("value must be greater than 0")
    return value


def parse_choice(raw: str, options: list[str]) -> str:
    """Resolve a 1-based index or an exact option name to an option value."""
    text = _clean(raw).lower()
    # Numeric selection
    if text.isdigit():
        idx = int(text)
        if 1 <= idx <= len(options):
            return options[idx - 1]
        raise IntakeError(f"choose a number between 1 and {len(options)}")
    # Name selection
    if text in options:
        return text
    raise IntakeError(f"'{raw.strip()}' is not one of the choices")


def parse_list(raw: str) -> list[str]:
    """Parse a comma-separated list; blank input yields an empty list."""
    return [item.strip() for item in raw.split(",") if item.strip()]


def _prompt_until_valid(
    label: str,
    parser: Callable[[str], object],
    input_fn: InputFn,
    output_fn: OutputFn,
) -> object:
    """Repeatedly prompt until the parser accepts the input."""
    while True:
        raw = input_fn(f"{label}: ")
        try:
            return parser(raw)
        except IntakeError as exc:
            output_fn(f"  ! {exc}. Please try again.")


def _render_choices(options: list[str], help_map: dict[str, str] | None = None) -> str:
    lines = []
    for i, opt in enumerate(options, start=1):
        suffix = f" ({help_map[opt]})" if help_map and opt in help_map else ""
        lines.append(f"    {i}) {opt}{suffix}")
    return "\n".join(lines)


def collect_profile(
    input_fn: InputFn = input,
    output_fn: OutputFn = print,
) -> UserProfile:
    """Interactively build a UserProfile. I/O is injectable for testing."""
    output_fn("Let's build your profile. Answer each prompt.\n")

    age = _prompt_until_valid(
        "Age (years)", lambda r: parse_int_in_range(r, 13, 120), input_fn, output_fn
    )

    output_fn("Sex:\n" + _render_choices(_SEX_OPTIONS))
    sex = _prompt_until_valid(
        "Choose sex (number or name)",
        lambda r: parse_choice(r, _SEX_OPTIONS),
        input_fn,
        output_fn,
    )

    height_cm = _prompt_until_valid(
        "Height (cm)", parse_positive_float, input_fn, output_fn
    )
    weight_kg = _prompt_until_valid(
        "Weight (kg)", parse_positive_float, input_fn, output_fn
    )

    output_fn("Activity level:\n" + _render_choices(_ACTIVITY_OPTIONS, _ACTIVITY_HELP))
    activity = _prompt_until_valid(
        "Choose activity level (number or name)",
        lambda r: parse_choice(r, _ACTIVITY_OPTIONS),
        input_fn,
        output_fn,
    )

    output_fn("Goal:\n" + _render_choices(_GOAL_OPTIONS))
    goal = _prompt_until_valid(
        "Choose goal (number or name)",
        lambda r: parse_choice(r, _GOAL_OPTIONS),
        input_fn,
        output_fn,
    )

    restrictions = parse_list(
        input_fn("Dietary restrictions (comma-separated, blank for none): ")
    )
    allergies = parse_list(
        input_fn("Allergies (comma-separated, blank for none): ")
    )

    return UserProfile(
        age=age,
        sex=sex,  # type: ignore[arg-type]
        height_cm=height_cm,
        weight_kg=weight_kg,
        activity_level=activity,  # type: ignore[arg-type]
        goal=goal,  # type: ignore[arg-type]
        dietary_restrictions=restrictions,
        allergies=allergies,
    )
