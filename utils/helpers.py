"""
Shared helpers used across multiple blueprints.
"""
import hashlib
from functools import wraps
from flask import session, redirect, url_for


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ── Route guards ──────────────────────────────────────────────────────────────

def login_required(f):
    """Redirect to login if user is not authenticated, or if they are admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('is_admin'):
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Redirect to login if the session is not an admin session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated
