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
import secrets as secrets_module
import ssl
import sys

from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import audit                                                   # noqa: E402
import commands                                                # noqa: E402
import control                                                 # noqa: E402
import security                                                # noqa: E402
import settings as config_settings                             # noqa: E402
import status                                                  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(REPO, 'conf')
SECRETS = os.path.join(CONF, 'web_secret.json')
AUDIT_DB = os.path.join(REPO, 'logs', 'panel-audit.db')

DEFAULTS = {
    'web_enabled': 0,
    'web_port': 8443,
    'web_bind': '0.0.0.0',
    'web_session_hours': 12,
    'web_cert': os.path.join(CONF, 'web-cert.pem'),
    'web_key': os.path.join(CONF, 'web-key.pem'),
    'web_command_port': 8128,
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


def create_app(settings=None, secrets_path=SECRETS, audit_db=AUDIT_DB):
    settings = settings or panel_settings()
    secrets = security.read_secrets(secrets_path)

    app = Flask(__name__)
    app.config['SETTINGS'] = settings
    app.config['PASSWORD_HASH'] = secrets.get('password_hash', '')
    app.config['COMMAND_TOKEN'] = secrets.get('command_token', '')
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

    def csrf_token():
        """This session's CSRF token, minted on first use."""
        token = session.get('csrf')
        if not token:
            token = secrets_module.token_urlsafe(32)
            session['csrf'] = token
        return token

    app.jinja_env.globals['csrf_token'] = csrf_token

    def wants_json():
        return 'application/json' in (request.headers.get('Accept') or '')

    @app.before_request
    def gate():
        # First gate, ahead of everything including the login form.
        if not security.is_private_address(caller()):
            app.logger.warning('refused %s (not a private address)', caller())
            return ('This panel is reachable from local networks only.\n',
                    403, {'Content-Type': 'text/plain'})

        # Second gate: nothing may change state without a token that came from
        # a page we served. SESSION_COOKIE_SAMESITE='Lax' already stops a
        # browser sending the session cookie on a cross-site POST, but stopping
        # the clock is worth two controls rather than one.
        if request.method == 'POST':
            sent = request.form.get('csrf', '')
            held = session.get('csrf', '')
            if not (held and secrets_module.compare_digest(sent, held)):
                app.logger.warning('CSRF check failed from %s on %s',
                                   caller(), request.path)
                stale = ('This page expired or did not come from the panel. '
                         'Reload it and try again.')
                if wants_json():
                    return jsonify({'ok': False, 'message': stale}), 400
                return (stale + '\n', 400, {'Content-Type': 'text/plain'})

        # Third gate. The login page and the stylesheet are the only things
        # served without a session.
        if request.endpoint in ('login', 'static'):
            return None
        if not session.get('authenticated'):
            # A redirect to the login form is useless to a fetch() - it would
            # read as an unexpected reply rather than "you were signed out".
            if request.path.startswith('/api/') or wants_json():
                return jsonify({'ok': False,
                                'message': 'Your session has expired. Reload '
                                           'the page and sign in again.'}), 401
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
                audit.record(audit_db, caller(), 'sign in', 'ok')
                # Cleared rather than updated so the pre-login session id and
                # CSRF token cannot be reused: signing in gets a fresh one.
                session.clear()
                session['authenticated'] = True
                session.permanent = True
                # Minted here rather than left to whichever template happens to
                # ask first, so a signed-in session always has one.
                csrf_token()
                target = request.args.get('next', '')
                # Only ever redirect within this site; an absolute URL here
                # would turn the login form into an open redirect.
                if not target.startswith('/') or target.startswith('//'):
                    target = url_for('index')
                return redirect(target)
            else:
                throttle.record_failure(caller())
                app.logger.warning('failed login from %s', caller())
                audit.record(audit_db, caller(), 'sign in', 'refused',
                             'wrong password')
                error = 'Incorrect password.'
                wait = throttle.locked_for(caller())
        return render_template('login.html', error=error, wait=wait), (401 if error else 200)

    @app.route('/logout', methods=['POST'])
    def logout():
        audit.record(audit_db, caller(), 'sign out', 'ok')
        session.clear()
        return redirect(url_for('login'))

    @app.route('/')
    def index():
        return render_template('status.html', data=status.snapshot())

    @app.route('/control')
    def control_page():
        return render_template('control.html',
                               actions=control.listed(),
                               available=control.available(),
                               live=commands.grouped(),
                               service=status.service_status(),
                               events=audit.recent(audit_db))

    @app.route('/command', methods=['POST'])
    def command():
        """Pass one live command to the running clock.

        Checked against the catalogue here and against the clock's own table
        there, so a name has to appear in both to reach anything.
        """
        name = request.form.get('command', '')
        ok, message = commands.send(name,
                                    settings.get('web_command_port', 8128),
                                    app.config['COMMAND_TOKEN'])
        audit.record(audit_db, caller(), name, 'ok' if ok else 'failed', message)
        app.logger.info('%s sent command %s -> %s', caller(), name, message)
        return outcome(ok, message)

    def outcome(ok, message, back=None):
        """Answer a control request.

        JSON when the page asked for it, so the browser can update in place
        rather than reloading and losing your scroll position; a redirect
        otherwise, which is what a plain form post with no JavaScript gets.
        The state and the log come back with it, so one round trip refreshes
        everything the page shows.

        Every route a data-live form can post to must come through here. One
        that returns a bare redirect instead leaves the browser following it,
        reading the HTML page that comes back as if it were JSON, and showing
        "the panel returned an unexpected reply".
        """
        if wants_json():
            return jsonify({'ok': ok, 'message': message,
                            'service': status.service_status(),
                            'events': audit.recent(audit_db)})
        flash(message, 'ok' if ok else 'error')
        return redirect(back or url_for('control_page'))

    @app.route('/action', methods=['POST'])
    def action():
        """Carry out one allowlisted action.

        The submitted name is only ever a key into control.ACTIONS; an
        unrecognised one is refused there before any process is started.
        """
        name = request.form.get('action', '')
        ok, message = control.run(name)
        if not audit.record(audit_db, caller(), name,
                            'ok' if ok else 'failed', message):
            message += ' (this could not be written to the audit log)'
        app.logger.info('%s requested %s -> %s', caller(), name, message)
        return outcome(ok, message)

    @app.route('/settings')
    def settings_page():
        return render_template('settings.html',
                               groups=config_settings.grouped(
                                   config_settings.read()),
                               backups=config_settings.backups())

    @app.route('/settings/save', methods=['POST'])
    def settings_save():
        submitted = {k: v for k, v in request.form.items()
                     if k not in ('csrf',)}
        ok, message, changed = config_settings.apply(submitted)
        audit.record(audit_db, caller(), 'edit settings',
                     'ok' if ok else 'failed',
                     ', '.join(changed) if changed else message)
        app.logger.info('%s edited settings -> %s', caller(), message)
        return outcome(ok, message, url_for('settings_page'))

    @app.route('/settings/restore', methods=['POST'])
    def settings_restore():
        name = request.form.get('backup', '')
        ok, message = config_settings.restore(name)
        audit.record(audit_db, caller(), 'restore config',
                     'ok' if ok else 'failed', message)
        return outcome(ok, message, url_for('settings_page'))

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

    # Created here as well as in set_password.py, so a panel upgraded from a
    # version without live commands starts working without being reconfigured.
    if not secrets.get('command_token'):
        security.ensure_command_token(SECRETS)
        print('NOTE: created a command token for live commands. Restart the '
              'clock so it picks it up:')
        print('      systemctl --user restart piclock')

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
