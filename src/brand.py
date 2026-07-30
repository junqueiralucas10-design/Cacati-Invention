"""Brand positioning — the single source of the product's voice.

Both surfaces read from here: the landing page (src/webapp.py) and the social
copy generator (src/promo.py). Defined once so the page and the posts can't
drift into saying different things about what the product stands for.

The positioning line is the spine: the app is a tool, not a transformation.
It hands you the numbers; the change is yours. Every piece of copy should be
consistent with that — which is also what keeps the marketing honest about an
app that builds meal plans and makes no promises about results.
"""

from __future__ import annotations

from dataclasses import dataclass

NAME = "NutriForge"

# The core positioning. This is the brand's one sentence.
POSITIONING = "A mudança não vem de fora pra dentro, mas de dentro pra fora."

TAGLINE = "Coma para o seu objetivo. A disciplina é sua; a conta é nossa."

LEAD = (
    "Plano alimentar personalizado que bate exatamente as suas metas de calorias "
    "e macros — para ganhar massa ou perder peso, do jeito saudável. "
    "Nós entregamos o número. O resto começa em você."
)

# The manifesto expands the positioning without over-promising: it draws the
# line between what the app does (the outside part) and what it can't do
# (the inside part).
MANIFESTO: tuple[str, ...] = (
    "Nenhum aplicativo emagrece ninguém. Nenhuma planilha ganha massa por você.",
    "O que vem de fora é ferramenta: a meta calculada, a refeição montada, "
    "a lista de compras pronta, o custo do mercado estimado.",
    "O que vem de dentro é o que decide: aparecer no dia em que não deu vontade, "
    "repetir na terça o que funcionou na segunda, continuar quando ninguém está vendo.",
    "A gente cuida da parte de fora para você não ter desculpa na parte de dentro.",
)


@dataclass(frozen=True)
class Quote:
    """A line illustrating the inside-out idea, and who it belongs to.

    `attribution` describes an athlete by discipline and moment, never by name.
    These lines are original copy written for this product — they are NOT
    quotations from real athletes. Attributing invented words to a real
    medalist would be putting words in their mouth, and naming real champions
    on a commercial page implies an endorsement they never gave.

    To ship real quotes, replace these entries with ones you have verified
    against a primary source and have permission to use commercially. The
    rendering doesn't change — only the data.
    """

    text: str
    attribution: str


# Archetypes, not people. See Quote's docstring before adding a real name.
QUOTES: tuple[Quote, ...] = (
    Quote(
        "A medalha foi decidida nos seis meses em que ninguém estava olhando. "
        "A final só mostrou o resultado.",
        "Uma velocista, sobre o pódio olímpico",
    ),
    Quote(
        "Todo mundo quer saber o que eu como. Ninguém pergunta o que eu faço "
        "no dia em que não quero comer isso.",
        "Um maratonista, sobre o quilômetro 35",
    ),
    Quote(
        "Treinei o mesmo movimento por quatro anos para que ele durasse "
        "onze segundos. A parte difícil foi acreditar nos anos, não nos segundos.",
        "Uma ginasta, sobre a série que valeu o ouro",
    ),
    Quote(
        "Meu adversário nunca foi o outro lado da rede. Era eu, às cinco da manhã, "
        "decidindo se levantava.",
        "Um tenista, sobre o primeiro título internacional",
    ),
)


# Guidance handed to the copywriter model, so social posts carry the same
# positioning as the landing page.
VOICE = (
    f"Posicionamento da marca, que toda peça deve respeitar: \"{POSITIONING}\"\n"
    "Isso significa: o app é ferramenta, não transformação. Ele entrega o número, "
    "a refeição e a lista; o mérito da mudança é de quem faz. Fale com respeito por "
    "esse esforço — nunca prometa o resultado, nunca sugira que o app é o autor da "
    "mudança, nunca use tom de solução mágica ou de atalho. Pode e deve falar de "
    "disciplina, constância e do que acontece quando ninguém está vendo."
)
