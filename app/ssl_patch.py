"""
Windows + Python 3.12+ (OpenSSL 3.x) can fail to connect to servers that
request legacy/unsafe TLS renegotiation mid-handshake — some servers built
on older frameworks do this, including Africa's Talking's sandbox API
(Akka HTTP). It shows up as a confusing `ssl.SSLError: WRONG_VERSION_NUMBER`,
even though the exact same server connects fine via curl or a browser,
because those use Windows' own TLS stack (schannel), which allows this
automatically — Python's OpenSSL-based ssl module is stricter by default.

This patches Python's SSLContext class itself — at the __init__ level, so
it applies no matter which internal function (ssl.create_default_context,
urllib3's own context builder, etc.) ends up constructing the context —
to explicitly allow legacy server connections, matching what curl/browsers
already do automatically via Windows' own TLS stack.

Import this BEFORE importing `requests` or `africastalking` anywhere
they're used — it must run before any HTTPS connection is opened.
"""

import ssl

_original_new = ssl.SSLContext.__new__


def _patched_new(cls, *args, **kwargs):
    instance = _original_new(cls, *args, **kwargs)
    if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
        instance.options |= ssl.OP_LEGACY_SERVER_CONNECT
    # Some servers (often behind certain load balancers) negotiate TLS 1.3
    # in a way that trips up Python's OpenSSL-based client even though
    # Windows' own TLS stack (schannel, used by curl/browsers) handles it
    # fine. Capping at TLS 1.2 is a common, targeted fix for exactly this
    # "WRONG_VERSION_NUMBER against one specific server" pattern.
    try:
        instance.maximum_version = ssl.TLSVersion.TLSv1_2
    except (ValueError, AttributeError):
        pass
    return instance


ssl.SSLContext.__new__ = _patched_new