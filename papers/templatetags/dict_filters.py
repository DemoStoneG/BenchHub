from django import template
from django.template.defaultfilters import floatformat

register = template.Library()


@register.filter
def dict_key(d, key):
    """字典取值：{{ my_dict|dict_key:key }}"""
    if d is None:
        return None
    return d.get(key)


@register.filter
def score(value):
    """数值展示：None → "-"，float → 2位小数"""
    if value is None:
        return '-'
    try:
        f = float(value)
        if f == int(f):
            return str(int(f))
        return str(round(f, 2))
    except (TypeError, ValueError):
        return str(value)[:10]
