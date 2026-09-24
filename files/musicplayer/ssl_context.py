import os
import ssl


def ca_bundle(app_dir):
    bundled = os.path.join(app_dir, "certs", "cacert.pem")
    if os.path.isfile(bundled):
        return bundled
    development = os.path.abspath(os.path.join(app_dir, "..", "assets", "cacert.pem"))
    return development if os.path.isfile(development) else None


def verified_context(app_dir):
    bundle = ca_bundle(app_dir)
    context = ssl.create_default_context(cafile=bundle) if bundle else ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context
