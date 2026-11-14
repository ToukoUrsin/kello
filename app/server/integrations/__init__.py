"""Kello integrations: Oxylabs Web API (live search + scrape), claim verification
(Oxylabs + Claude), and the Gemini report reader. Imports are lazy so that a missing
optional dependency in one module does not break the others."""

__all__ = ["search", "scrape", "verify_claim", "read_report"]


def search(*args, **kwargs):
    from .oxylabs import search as f

    return f(*args, **kwargs)


def scrape(*args, **kwargs):
    from .oxylabs import scrape as f

    return f(*args, **kwargs)


def verify_claim(*args, **kwargs):
    from .verify import verify_claim as f

    return f(*args, **kwargs)


def read_report(*args, **kwargs):
    from .gemini_reader import read_report as f

    return f(*args, **kwargs)
