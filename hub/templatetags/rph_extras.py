from django import template

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
