from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Dict access in templates: {{ docs_by_phase|get_item:ph.pk }}"""
    if isinstance(mapping, dict):
        return mapping.get(key, 0)
    try:
        return mapping[key]
    except (KeyError, IndexError, TypeError):
        return 0


@register.filter
def json(value):
    """JSON-encode a value for embedding in <script type="application/json">."""
    import json as _json

    out = _json.dumps(value, ensure_ascii=False)
    # Prevent "</script>" from terminating the element early.
    return mark_safe(out.replace("</", "<\\/"))
