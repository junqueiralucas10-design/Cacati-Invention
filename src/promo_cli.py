"""Generate — and optionally publish — the social-media promo posts.

Usage:
    python -m src.promo_cli                          # gera e imprime tudo (dry run)
    python -m src.promo_cli --platform x             # só uma plataforma
    python -m src.promo_cli --url https://meusite    # link usado nas legendas
    python -m src.promo_cli --platform x --publish   # publica de verdade (pede confirmação)
    python -m src.promo_cli --platform instagram --publish --image-url https://.../post.jpg

Gerar exige ANTHROPIC_API_KEY. Publicar exige as credenciais da rede — veja src/social.py.
"""

from __future__ import annotations

import sys

from .console import use_utf8_output
from .promo import PLATFORMS, PLATFORMS_BY_KEY, campaign_facts, generate_posts, render_text, verify_posts
from .profile import UserProfile
from .social import PUBLISHABLE, PublishError, publish

DEFAULT_URL = "https://github.com/junqueiralucas10-design/Cacati-Invention"


def _demo_profile() -> UserProfile:
    """The persona whose real plan supplies the numbers in the copy."""
    return UserProfile(
        age=30,
        sex="male",
        height_cm=178,
        weight_kg=82,
        activity_level="moderate",
        goal="gain_muscle",
        dietary_restrictions=[],
        allergies=[],
    )


def _flag_value(argv: list[str], name: str) -> str | None:
    """Return the value after `--name`, or None if the flag isn't present."""
    if name not in argv:
        return None
    i = argv.index(name)
    if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
        print(f"⚠ {name} precisa de um valor")
        sys.exit(1)
    return argv[i + 1]


def _print_post(post: dict) -> None:
    platform = PLATFORMS_BY_KEY[post["platform"]]
    text = render_text(post)
    print(f"\n=== {platform.name} ({len(text)}/{platform.max_chars} caracteres) ===")
    print(text)
    print(f"\n[CTA] {post['cta']}")
    print(f"[Alt] {post['alt_text']}")


def _confirm(platform: str, text: str) -> bool:
    """Publishing is public and hard to undo — make the user type it out."""
    print(f"\nIsto será publicado agora em {platform}:\n")
    print(text)
    print()
    return input('Digite PUBLICAR para confirmar (qualquer outra coisa cancela): ').strip() == "PUBLICAR"


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    use_utf8_output()

    only = _flag_value(argv, "--platform")
    if only is not None and only not in PLATFORMS_BY_KEY:
        print(f"⚠ plataforma desconhecida: {only} (disponíveis: {', '.join(PLATFORMS_BY_KEY)})")
        sys.exit(1)

    platforms = tuple(p for p in PLATFORMS if only is None or p.key == only)
    url = _flag_value(argv, "--url") or DEFAULT_URL
    image_url = _flag_value(argv, "--image-url")
    should_publish = "--publish" in argv

    print("Gerando conteúdo a partir de um plano real do app...")
    facts = campaign_facts(_demo_profile(), app_url=url)
    print(
        f"Base: {facts['target_calories']} kcal/dia, {facts['meal_count']} refeições, "
        f"mercado do dia {facts['daily_cost_brl']}\n"
    )

    posts = generate_posts(facts, platforms=platforms)
    for post in posts:
        _print_post(post)

    problems = verify_posts(posts)
    if problems:
        print("\n⚠ Posts fora do limite (corrija antes de publicar):")
        for problem in problems:
            print(f"   - {problem}")
    else:
        print("\n✓ Todos os posts cabem no limite da plataforma.")

    if not should_publish:
        print("\n(Nada foi publicado. Use --publish para postar de verdade.)")
        return

    if problems:
        print("\nPublicação cancelada: corrija os posts acima primeiro.")
        sys.exit(1)

    for post in posts:
        platform = post["platform"]
        if platform not in PUBLISHABLE:
            print(f"\n{platform}: publicação automática não disponível — poste manualmente.")
            continue
        text = render_text(post)
        if not _confirm(platform, text):
            print(f"{platform}: cancelado.")
            continue
        try:
            result = publish(text, platform, dry_run=False, image_url=image_url)
        except PublishError as exc:
            print(f"✗ {platform}: {exc}")
            continue
        print(f"✓ {platform}: publicado — {result['response']}")


if __name__ == "__main__":
    main()
