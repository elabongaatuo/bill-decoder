"""
Diagnostic: checks whether ssl_patch.py is actually taking effect on this
machine, and whether the underlying Python/OpenSSL build even supports the
flag we're relying on. Run this directly:

    python3 check_ssl_patch.py
"""

import ssl

print(f"Python ssl module OpenSSL version: {ssl.OPENSSL_VERSION}")
print(f"Has OP_LEGACY_SERVER_CONNECT attribute: {hasattr(ssl, 'OP_LEGACY_SERVER_CONNECT')}")

if not hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
    print("\n>>> This Python/OpenSSL build does not expose OP_LEGACY_SERVER_CONNECT at all.")
    print(">>> That means our patch silently does nothing — this is likely the root cause.")
else:
    # Test BEFORE importing the patch
    ctx_before = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    print(f"\nBEFORE importing ssl_patch — flag set: {bool(ctx_before.options & ssl.OP_LEGACY_SERVER_CONNECT)}")

    import ssl_patch  # noqa: F401

    ctx_after = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    print(f"AFTER importing ssl_patch  — flag set: {bool(ctx_after.options & ssl.OP_LEGACY_SERVER_CONNECT)}")

    try:
        import urllib3.util.ssl_ as u
        ctx_urllib3 = u.create_urllib3_context()
        print(f"Via urllib3.create_urllib3_context() — flag set: {bool(ctx_urllib3.options & ssl.OP_LEGACY_SERVER_CONNECT)}")
    except Exception as e:
        print(f"Could not test urllib3's context builder: {e}")

print("\n--- Now attempting an actual connection to Africa's Talking's sandbox API ---")
try:
    import ssl_patch  # noqa: F401  (harmless if already imported above)
    import requests
    r = requests.get("https://api.sandbox.africastalking.com/version1/messaging", timeout=10)
    print(f"SUCCESS — got HTTP {r.status_code} back (a 404 here is fine, it means the connection worked)")
except Exception as e:
    print(f"FAILED — {type(e).__name__}: {e}")