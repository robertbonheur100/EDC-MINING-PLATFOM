"""
Shared helpers used across multiple blueprints.
"""

import hashlib
from functools import wraps
from flask import session, redirect, url_for


# ─────────────────────────────────────────────
# PASSWORD HASHING (SHA256 simple version)
# ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    """
    Hash password using SHA256.
    Must be used consistently for register + login.
    """
    return hashlib.sha256(password.encode()).hexdigest()


# ─────────────────────────────────────────────
# LOGIN PROTECTION
# ─────────────────────────────────────────────

def login_required(f):
    """
    Protect routes that require a logged-in user.
    Redirect to login if user is not authenticated.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


# ─────────────────────────────────────────────
# ADMIN PROTECTION
# ─────────────────────────────────────────────

def admin_required(f):
    """
    Protect admin-only routes.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function
