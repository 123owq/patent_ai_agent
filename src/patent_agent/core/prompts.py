from pathlib import Path
from jinja2 import Environment, FileSystemLoader

_PROMPT_DIR = Path(__file__).parent.parent / "prompts"
_env = Environment(loader=FileSystemLoader(str(_PROMPT_DIR)), autoescape=False)


def render(template_name: str, **kwargs: object) -> str:
    """Jinja2 템플릿 렌더링. template_name 예: 'tool1.j2'"""
    return _env.get_template(template_name).render(**kwargs)
