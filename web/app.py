"""PiClock web control panel - phase 1, read only.

Run it with:

    venv/bin/python3 web/app.py

It refuses to start rather than starting insecurely: no password set, no
certificate, or web_enabled left at 0 are all hard stops with an explanation,
because the alternative is a panel quietly listening with no password on a
machine its owner believes is switched off.
"""

import datetime
import os
import ssl
import sys

from flask import (Flask, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import security                                                # noqa: E402
import status                                                  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(REPO, 'conf')
SECRETS = os.path.join(CONF, 'web_secret.json')

DEFAULTS = {
    'web_enabled': 0,
    'web_port': 8443,
    'web_bind': '0.0.0.0',
    'web_session_hours': 12,
    'web_cert': os.path.join(CONF, 'web-cert.pem'),
    'web_key': os.path.join(CONF, 'web-key.pem'),
}


def panel_settings():
    """The web_* settings, read out of Config.py without executing it."""
    values = dict(DEFAULTS)
    sys.path.insert(0, REPO)
    try:
        import merge_config
        text, _ = merge_config.read_text(os.path.join(CONF, 'Config.py'))
        for name, value in merge_config.literal_settings(text).items():
            if name in DEFAULTS:
                values[name] = value
    except (ImportError, OSError, SyntaxError):
        pass
    finally:
        sys.path.pop(0)
    return values


def create_app(settings=None, secrets_path=SECRETS):
    settings = settings or panel_settings()
    secrets = security.read_secrets(secrets_path)

    app = Flask(__name__)
    app.config['SETTINGS'] = settings
    app.config['PASSWORD_HASH'] = secrets.get('password_hash', '')
    app.secret_key = secrets.get('session_key') or security.ensure_session_key(secrets_path)
    app.config.update(
        # Secure: never send the session cookie over plain http, so a
        # misconfigured redirect cannot leak it.
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        # Lax rather than Strict: Strict would drop the cookie when you follow
        # a bookmark to the panel, which looks like a random logout.
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=datetime.timedelta(
            hours=int(settings.get('web_session_hours', 12))),
    )
    throttle = security.LoginThrottle()

    def caller():
        """The address this request actually came from.

        request.remote_addr deliberately, never X-Forwarded-For: that header is
        caller-supplied, so trusting it would let anyone on the internet claim
        to be 192.168.1.5 and walk straight through the address gate. Putting a
        real proxy in front of the panel means teaching it about that proxy on
        purpose - see the documentation.
        """
        return request.remote_addr or ''

    @app.before_request
    def gate():
        # First gate, ahead of everything including the login form.
        if not security.is_private_address(caller()):
            app.logger.warning('refused %s (not a private address)', caller())
            return ('This panel is reachable from local networks only.\n',
                    403, {'Content-Type': 'text/plain'})
        # Second gate. The login page and the stylesheet are the only things
        # served without a session.
        if request.endpoint in ('login', 'static'):
            return None
        if not session.get('authenticated'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'not authenticated'}), 401
            return redirect(url_for('login', next=request.path))
        return None

    @app.after_request
    def harden(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'")
        return response

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error = ''
        wait = throttle.locked_for(caller())
        if request.method == 'POST':
            if wait:
                error = 'Too many attempts. Try again in %d seconds.' % wait
            elif check_password_hash(app.config['PASSWORD_HASH'],
                                     request.form.get('password', '')):
                throttle.record_success(caller())
                session.clear()
                session['authenticated'] = True
                session.permanent = True
                target = request.args.get('next', '')
                # Only ever redirect within this site; an absolute URL here
                # would turn the login form into an open redirect.
                if not target.startswith('/') or target.startswith('//'):
                    target = url_for('index')
                return redirect(target)
            else:
                throttle.record_failure(caller())
                app.logger.warning('failed login from %s', caller())
                error = 'Incorrect password.'
                wait = throttle.locked_for(caller())
        return render_template('login.html', error=error, wait=wait), (401 if error else 200)

    @app.route('/logout', methods=['POST'])
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.route('/')
    def index():
        return render_template('status.html', data=status.snapshot())

    @app.route('/api/status')
    def api_status():
        return jsonify(status.snapshot())

    return app


def fail(message):
    print('ERROR: ' + message, file=sys.stderr)
    raise SystemExit(1)


def main():
    settings = panel_settings()
    if not int(settings.get('web_enabled', 0)):
        fail('web_enabled is 0 in conf/Config.py, so the panel will not start.')

    secrets = security.read_secrets(SECRETS)
    if not secrets.get('password_hash'):
        fail('no panel password is set. Run:\n'
             '       venv/bin/python3 web/set_password.py')

    cert, key = settings['web_cert'], settings['web_key']
    if not (os.path.isfile(cert) and os.path.isfile(key)):
        fail('TLS certificate missing (%s). Run:\n'
             '       bash web/make_cert.sh' % cert)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # TLS 1.2 is the floor; everything that can reach a Pi on your LAN speaks
    # it, and it drops the older versions with known problems.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)

    app = create_app(settings)
    port = int(settings['web_port'])
    print('PiClock control panel on https://%s:%d/' % (settings['web_bind'], port))
    print('Reachable from private networks only; the certificate is self-signed,')
    print('so your browser will ask you to accept it the first time.')
    app.run(host=settings['web_bind'], port=port, ssl_context=context,
            threaded=True, debug=False)


if __name__ == '__main__':
    main()
