"""Exact positive major-unit parsing; business limits belong to adapters.

Callers supply the provider/currency precision from a trusted configuration.
This module does not infer a currency or use a two-decimal default globally.
"""
import re


def parse_major_units(text, *, exponent, max_major_digits=8):
    if type(exponent) is not int or not 0 <= exponent <= 6:
        raise ValueError('Unsupported currency precision')
    if type(max_major_digits) is not int or not 1 <= max_major_digits <= 18:
        raise ValueError('Invalid major-unit digit limit')
    suffix = rf'(?:\.[0-9]{{1,{exponent}}})?' if exponent else ''
    if not isinstance(text, str) or not re.fullmatch(rf'[0-9]{{1,{max_major_digits}}}' + suffix, text):
        raise ValueError('Expected an unsigned decimal string within currency precision')
    whole, _, fraction = text.partition('.')
    # Integer arithmetic avoids rounding and Decimal context changes in callers.
    amount = int(whole) * (10 ** exponent) + int(fraction.ljust(exponent, '0') or '0')
    if amount <= 0:
        raise ValueError('Amount must be positive')
    return amount
