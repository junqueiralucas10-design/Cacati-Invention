"""Generate social-media promo copy for the app, grounded in real app output.

`campaign_facts()` runs the rule-based diet builder on a real profile and pulls
the numbers the app actually produces — calorie/macro targets, an actual meal,
the R$ grocery estimate. Those numbers go into the prompt, so a post can't claim
something the app doesn't do.

Uses the Anthropic Messages API with structured outputs (validated JSON) and
streaming, the same shape as src/diet_planner.py. Copy is written in Brazilian
Portuguese, since the app targets Brazil.

Generated posts are verified after generation (`verify_posts`): anything over a
platform's character limit gets flagged rather than silently shipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import anthropic

from . import MODEL, brand
from .diet_builder import build_personalized_plan
from .pricing import estimate_plan_cost, format_brl
from .profile import UserProfile


@dataclass(frozen=True)
class Platform:
    """A target network and how copy for it should read."""

    key: str
    name: str
    max_chars: int  # applies to the rendered text (caption + hashtags)
    guidance: str


PLATFORMS: tuple[Platform, ...] = (
    Platform(
        "instagram",
        "Instagram",
        2200,
        "Legenda de carrossel. Primeira linha é o gancho e precisa parar o scroll. "
        "Corpo em 3-4 linhas curtas, tom próximo e direto, pode usar emoji com moderação. "
        "8 a 12 hashtags, misturando alcance amplo e nicho brasileiro.",
    ),
    Platform(
        "tiktok",
        "TikTok",
        2200,
        "A legenda deve funcionar como roteiro falado de ~20 segundos, em 3 blocos: "
        "gancho nos primeiros 3 segundos, demonstração com um número concreto, e o convite final. "
        "Linguagem falada, sem jargão. 3 a 5 hashtags.",
    ),
    Platform(
        "x",
        "X",
        280,
        "Um único post curto. Sem emoji, sem thread. Um número concreto e o link. "
        "No máximo 2 hashtags — o limite de 280 caracteres inclui as hashtags.",
    ),
    Platform(
        "linkedin",
        "LinkedIn",
        3000,
        "Tom profissional, primeira pessoa, foco na decisão técnica: planner por regras que roda "
        "sem API key, base de alimentos brasileiros, custo estimado em R$. Sem emoji. "
        "3 a 5 hashtags no final.",
    ),
)

PLATFORMS_BY_KEY: dict[str, Platform] = {p.key: p for p in PLATFORMS}

# What the app actually does today, per README.md. The model may only draw on
# this list — it is the guard against copy that invents features.
FEATURES: tuple[str, ...] = (
    "Monta um plano alimentar personalizado a partir de idade, sexo, altura, peso, "
    "nível de atividade e objetivo (ganhar massa, perder peso ou manter).",
    "Calcula meta de calorias e macros com Mifflin-St Jeor + TDEE.",
    "Base de alimentos comuns no Brasil: arroz, feijão, frango, ovos, tapioca, mandioca, frutas.",
    "Restrições e alergias funcionam em português e inglês: vegano, sem lactose, sem glúten.",
    "Funciona sem chave de API — o planner por regras roda offline; com chave, usa Claude "
    "para planos mais variados.",
    "Gera lista de compras consolidada, somando os ingredientes de todas as refeições.",
    "Estima o custo do mercado em R$ com preços de referência do Carrefour Brasil, editáveis.",
    "Plano de 1 a 7 dias, com refeições variadas ao longo da semana.",
    "Confere as calorias declaradas contra os macros (4/4/9 kcal) e sinaliza inconsistências.",
)

_SYSTEM = (
    "Você é redator publicitário brasileiro, especialista em conteúdo para redes sociais de "
    "produtos de tecnologia. Escreve em português do Brasil, natural e direto, sem sotaque de "
    "tradução e sem clichê de marketing genérico.\n\n"
    + brand.VOICE
    + "\n\nRegras inegociáveis:\n"
    "- Use SOMENTE os fatos e números fornecidos. Nunca invente funcionalidade, preço, "
    "métrica, depoimento ou número que não esteja no material.\n"
    "- Nunca prometa resultado de saúde, perda de peso, ganho de massa ou prazo. O app monta "
    "um plano; ele não garante resultado.\n"
    "- Não faça afirmação médica nem sugira substituir profissional de saúde.\n"
    "- O produto está em desenvolvimento inicial. Pode soar promissor, não pode soar consolidado: "
    "nada de 'milhares de usuários', 'o app que mudou a vida de', 'aprovado por'.\n"
    "- Respeite o limite de caracteres de cada plataforma. O limite conta a legenda mais as "
    "hashtags juntas."
)

_POST_SCHEMA = {
    "type": "object",
    "properties": {
        "platform": {"type": "string"},
        "hook": {"type": "string"},  # a primeira linha, isolada para teste A/B
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "cta": {"type": "string"},
        "alt_text": {"type": "string"},  # descrição da imagem, acessibilidade
    },
    "required": ["platform", "hook", "caption", "hashtags", "cta", "alt_text"],
    "additionalProperties": False,
}

_CAMPAIGN_SCHEMA = {
    "type": "object",
    "properties": {"posts": {"type": "array", "items": _POST_SCHEMA}},
    "required": ["posts"],
    "additionalProperties": False,
}


def campaign_facts(profile: UserProfile, app_url: str) -> dict:
    """Real numbers the app produces for `profile`, as raw material for the copy.

    Runs the rule-based builder (no API key needed) so every figure in a post
    traces back to something the app actually computed.
    """
    plan = build_personalized_plan(profile)
    cost = estimate_plan_cost(plan)
    macros = profile.target_macros()
    meals = plan["meals"]

    return {
        "app_url": app_url,
        "goal": profile.goal,
        "profile": (
            f"{profile.age} anos, {profile.sex}, {profile.height_cm:.0f} cm, "
            f"{profile.weight_kg:.0f} kg, atividade {profile.activity_level}"
        ),
        "target_calories": profile.target_calories(),
        "protein_g": macros["protein_g"],
        "fat_g": macros["fat_g"],
        "carbs_g": macros["carbs_g"],
        "meal_count": len(meals),
        "sample_meals": [f"{m['name']}: {m['description']} ({m['calories']} kcal)" for m in meals],
        "daily_cost_brl": format_brl(cost["total_brl"]),
        "features": list(FEATURES),
    }


def _build_prompt(facts: dict, platforms: tuple[Platform, ...]) -> str:
    specs = "\n".join(
        f"- {p.key} ({p.name}): máximo {p.max_chars} caracteres. {p.guidance}" for p in platforms
    )
    inspiration = "\n".join(f'    "{q.text}" — {q.attribution}' for q in brand.QUOTES)
    return (
        f"Escreva um post de divulgação para cada plataforma abaixo, para o {brand.NAME}, "
        "um app que monta dietas personalizadas com foco no Brasil.\n\n"
        f"Frase de posicionamento, que deve estar no espírito de todo post: "
        f"\"{brand.POSITIONING}\"\n\n"
        "Manifesto da marca:\n"
        + "\n".join(f"- {line}" for line in brand.MANIFESTO)
        + "\n\nExemplos do tom desejado ao falar de esforço e constância. São textos "
        "originais da marca sobre arquétipos do esporte, NÃO citações de atletas reais — "
        "use como referência de tom, nunca atribua fala a atleta real nem cite nome de "
        "atleta, time ou competição:\n" + inspiration + "\n\n"
        "O que o app faz hoje (não use nada além disto):\n"
        + "\n".join(f"- {f}" for f in facts["features"])
        + "\n\nExemplo real gerado pelo app, use estes números:\n"
        f"- Perfil de exemplo: {facts['profile']}, objetivo {facts['goal']}\n"
        f"- Meta diária: {facts['target_calories']} kcal, {facts['protein_g']} g de proteína, "
        f"{facts['fat_g']} g de gordura, {facts['carbs_g']} g de carboidrato\n"
        f"- Plano do dia ({facts['meal_count']} refeições):\n"
        + "\n".join(f"    • {m}" for m in facts["sample_meals"])
        + f"\n- Custo estimado do mercado para esse dia: {facts['daily_cost_brl']}\n"
        f"- Link: {facts['app_url']}\n\n"
        "Plataformas:\n" + specs + "\n\n"
        "Para cada plataforma devolva: o gancho (primeira linha, isolado), a legenda completa "
        "(já incluindo o gancho), as hashtags sem o símbolo #, a chamada para ação e um texto "
        "alternativo descrevendo a imagem que acompanharia o post. "
        "O campo platform deve ser exatamente a chave listada acima."
    )


def generate_posts(
    facts: dict,
    platforms: tuple[Platform, ...] = PLATFORMS,
    client: anthropic.Anthropic | None = None,
) -> list[dict]:
    """Generate one post per platform. Returns the list of post dicts."""
    client = client or anthropic.Anthropic()

    with client.messages.stream(
        model=MODEL,
        max_tokens=8000,
        system=_SYSTEM,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": _CAMPAIGN_SCHEMA},
        },
        messages=[{"role": "user", "content": _build_prompt(facts, platforms)}],
    ) as stream:
        message = stream.get_final_message()

    text = next(b.text for b in message.content if b.type == "text")
    return json.loads(text)["posts"]


def render_text(post: dict) -> str:
    """The exact text that gets published: caption plus hashtags."""
    tags = " ".join(f"#{t.lstrip('#')}" for t in post.get("hashtags", []) if t.strip())
    caption = post.get("caption", "").strip()
    return f"{caption}\n\n{tags}".strip() if tags else caption


def verify_posts(posts: list[dict]) -> list[str]:
    """Flag posts that can't actually be published as written.

    Returns a list of human-readable problems — empty means everything fits.
    """
    problems: list[str] = []
    for post in posts:
        key = post.get("platform", "")
        platform = PLATFORMS_BY_KEY.get(key)
        if platform is None:
            problems.append(f"plataforma desconhecida: {key!r}")
            continue
        length = len(render_text(post))
        if length > platform.max_chars:
            problems.append(
                f"{platform.name}: {length} caracteres, {platform.max_chars} permitidos "
                f"({length - platform.max_chars} a mais)"
            )
    return problems
