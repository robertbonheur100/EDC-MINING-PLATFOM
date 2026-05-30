"""
Authentication blueprint — register, login, logout.
URL prefix: /auth
"""
import uuid
from flask import (Blueprint, render_template, request,
                   redirect, url_for, session, flash)
from config import Config
from utils.supabase_client import get_supabase, get_admin_supabase
from utils.helpers import hash_password

auth_bp = Blueprint('auth', __name__)


# ── Register ──────────────────────────────────────────────────────────────────

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')
        username = request.form.get('username', '').strip()
        ref_code = request.form.get('ref_code', '').strip()

        # Validation
        if not all([email, password, username]):
            flash('All fields are required.', 'error')
            return render_template('register.html', ref_code=ref_code)

        if password != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('register.html', ref_code=ref_code)

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('register.html', ref_code=ref_code)

        try:
            db = get_admin_supabase()

            # Check duplicate email
            existing = db.table('profiles').select('id').eq('email', email).execute()
            if existing.data:
                flash('Email already registered.', 'error')
                return render_template('register.html', ref_code=ref_code)

            # Resolve referral chain
            referrer_id    = None
            referrer_l2_id = None
            if ref_code:
                ref_res = db.table('profiles') \
                    .select('id, referred_by') \
                    .eq('referral_code', ref_code) \
                    .execute()
                if ref_res.data:
                    referrer_id    = ref_res.data[0]['id']
                    referrer_l2_id = ref_res.data[0].get('referred_by')

            # Self-referral guard
            user_id      = str(uuid.uuid4())
            my_ref_code  = str(uuid.uuid4())[:8].upper()

            db.table('profiles').insert({
                'id':             user_id,
                'email':          email,
                'username':       username,
                'password_hash':  hash_password(password),
                'balance':        0.0,
                'referral_code':  my_ref_code,
                'referred_by':    referrer_id,
                'referred_by_l2': referrer_l2_id,
                'is_admin':       False,
            }).execute()

            flash('Account created! Please log in.', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            flash(f'Registration error: {e}', 'error')
            return render_template('register.html', ref_code=ref_code)

    return render_template('register.html', ref_code=request.args.get('ref', ''))


# ── Login ─────────────────────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        # Admin shortcut
        if email == Config.ADMIN_EMAIL and password == Config.ADMIN_PASSWORD:
            session.clear()
            session['user_id']  = 'admin'
            session['is_admin'] = True
            session['username'] = 'Admin'
            return redirect(url_for('admin.dashboard'))

        try:
            db = get_admin_supabase()
            res = db.table('profiles') \
                .select('*') \
                .eq('email', email) \
                .eq('password_hash', hash_password(password)) \
                .execute()

            if res.data:
                user = res.data[0]
                session.clear()
                session['user_id']  = user['id']
                session['is_admin'] = user.get('is_admin', False)
                session['username'] = user['username']
                return redirect(url_for('dashboard.index'))

            flash('Invalid email or password.', 'error')

        except Exception as e:
            flash(f'Login error: {e}', 'error')

    return render_template('login.html')


# ── Logout ────────────────────────────────────────────────────────────────────

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('auth.login'))
