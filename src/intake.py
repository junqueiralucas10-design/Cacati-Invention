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
    "sedentary": "pouco ou nenhum exercício",
    "light": "1 a 3 dias/semana",
    "moderate": "3 a 5 dias/semana",
    "active": "6 a 7 dias/semana",
    "very_active": "exercício pesado ou trabalho físico",
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
        raise IntakeError(f"'{text}' não é um número inteiro") from exc
    if not lo <= value <= hi:
        raise IntakeError(f"o valor precisa estar entre {lo} e {hi}")
    return value


def parse_positive_float(raw: str) -> float:
    """Parse a float and require it to be > 0."""
    text = _clean(raw)
    try:
        value = float(text.replace(",", "."))
    except ValueError as exc:
        raise IntakeError(f"'{text}' não é um número") from exc
    if value <= 0:
        raise IntakeError("o valor precisa ser maior que 0")
    return value


def parse_choice(raw: str, options: list[str]) -> str:
    """Resolve a 1-based index or an exact option name to an option value."""
    text = _clean(raw).lower()
    # Numeric selection
    if text.isdigit():
        idx = int(text)
        if 1 <= idx <= len(options):
            return options[idx - 1]
        raise IntakeError(f"escolha um número entre 1 e {len(options)}")
    # Name selection
    if text in options:
        return text
    raise IntakeError(f"'{raw.strip()}' não é uma das opções")


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
            output_fn(f"  ! {exc}. Tente de novo.")


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
    output_fn("Vamos montar seu perfil. Responda cada pergunta.\n")

    age = _prompt_until_valid(
        "Idade (anos)", lambda r: parse_int_in_range(r, 13, 120), input_fn, output_fn
    )

    output_fn("Sexo:\n" + _render_choices(_SEX_OPTIONS))
    sex = _prompt_until_valid(
        "Escolha o sexo (número ou nome)",
        lambda r: parse_choice(r, _SEX_OPTIONS),
        input_fn,
        output_fn,
    )

    height_cm = _prompt_until_valid(
        "Altura (cm)", parse_positive_float, input_fn, output_fn
    )
    weight_kg = _prompt_until_valid(
        "Peso (kg)", parse_positive_float, input_fn, output_fn
    )

    output_fn("Nível de atividade:\n" + _render_choices(_ACTIVITY_OPTIONS, _ACTIVITY_HELP))
    activity = _prompt_until_valid(
        "Escolha o nível de atividade (número ou nome)",
        lambda r: parse_choice(r, _ACTIVITY_OPTIONS),
        input_fn,
        output_fn,
    )

    output_fn("Objetivo:\n" + _render_choices(_GOAL_OPTIONS))
    goal = _prompt_until_valid(
        "Escolha o objetivo (número ou nome)",
        lambda r: parse_choice(r, _GOAL_OPTIONS),
        input_fn,
        output_fn,
    )

    restrictions = parse_list(
        input_fn("Restrições alimentares (separadas por vírgula, vazio para nenhuma): ")
    )
    allergies = parse_list(
        input_fn("Alergias (separadas por vírgula, vazio para nenhuma): ")
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
