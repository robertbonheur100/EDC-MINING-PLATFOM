from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash

from utils.supabase_client import get_admin_supabase
from utils.helpers import admin_required

admin_bp = Blueprint('admin', __name__)


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────
@admin_bp.route('/')
@admin_required
def dashboard():
    db = get_admin_supabase()

    users = db.table('profiles').select('*').execute().data or []

    deposits = db.table('deposits')\
        .select('*')\
        .order('created_at', desc=True)\
        .execute().data or []

    withdrawals = db.table('withdrawals')\
        .select('*')\
        .order('created_at', desc=True)\
        .execute().data or []

    transactions = db.table('transactions')\
        .select('*')\
        .order('created_at', desc=True)\
        .limit(60)\
        .execute().data or []

    investments = db.table('investments')\
        .select('*')\
        .order('created_at', desc=True)\
        .execute().data or []

    actions = db.table('admin_actions')\
        .select('*')\
        .order('created_at', desc=True)\
        .limit(50)\
        .execute().data or []

    return render_template(
        'admin.html',
        users=users,
        deposits=deposits,
        withdrawals=withdrawals,
        transactions=transactions,
        investments=investments,
        actions=actions,
        total_balance=sum(u.get('balance', 0) or 0 for u in users),
        pending_deposits=[d for d in deposits if d.get('status') == 'pending'],
        pending_withdrawals=[w for w in withdrawals if w.get('status') == 'pending'],
        active_investments=[i for i in investments if i.get('status') == 'active'],
    )


# ─────────────────────────────────────────────
# DEPOSIT APPROVAL
# ─────────────────────────────────────────────
@admin_bp.route('/deposit/<deposit_id>/<action>', methods=['POST'])
@admin_required
def handle_deposit(deposit_id, action):
    db = get_admin_supabase()
    now = datetime.now(timezone.utc).isoformat()

    dep_res = db.table('deposits').select('*').eq('id', deposit_id).execute()
    dep = (dep_res.data or [None])[0]

    if not dep:
        flash('Deposit not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    uid = dep.get('user_id')
    amount = dep.get('amount', 0)

    if action == 'approve':
        prof_res = db.table('profiles').select('balance').eq('id', uid).execute()
        prof = (prof_res.data or [{}])[0]
        balance = prof.get('balance', 0)

        db.table('profiles').update({
            'balance': round(balance + amount, 2)
        }).eq('id', uid).execute()

        db.table('deposits').update({
            'status': 'approved',
            'reviewed_at': now
        }).eq('id', deposit_id).execute()

        db.table('transactions').insert({
            'user_id': uid,
            'type': 'deposit',
            'amount': amount,
            'description': f"Deposit approved",
            'status': 'completed',
            'created_at': now
        }).execute()

        flash('Deposit approved.', 'success')

    elif action == 'reject':
        db.table('deposits').update({
            'status': 'rejected',
            'reviewed_at': now
        }).eq('id', deposit_id).execute()

        flash('Deposit rejected.', 'info')

    _log_action(db, action, deposit_id, f"{action} deposit", now)
    return redirect(url_for('admin.dashboard'))


# ─────────────────────────────────────────────
# WITHDRAWAL APPROVAL
# ─────────────────────────────────────────────
@admin_bp.route('/withdrawal/<wd_id>/<action>', methods=['POST'])
@admin_required
def handle_withdrawal(wd_id, action):
    db = get_admin_supabase()
    now = datetime.now(timezone.utc).isoformat()

    wd_res = db.table('withdrawals').select('*').eq('id', wd_id).execute()
    wd = (wd_res.data or [None])[0]

    if not wd:
        flash('Withdrawal not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    uid = wd.get('user_id')
    amount = wd.get('amount', 0)

    if action == 'approve':
        prof_res = db.table('profiles').select('balance').eq('id', uid).execute()
        prof = (prof_res.data or [{}])[0]
        balance = prof.get('balance', 0)

        new_balance = round(max(balance - amount, 0), 2)

        db.table('profiles').update({
            'balance': new_balance
        }).eq('id', uid).execute()

        db.table('withdrawals').update({
            'status': 'approved',
            'reviewed_at': now
        }).eq('id', wd_id).execute()

        db.table('transactions').insert({
            'user_id': uid,
            'type': 'withdrawal',
            'amount': -amount,
            'description': "Withdrawal approved",
            'status': 'completed',
            'created_at': now
        }).execute()

        flash('Withdrawal approved.', 'success')

    elif action == 'reject':
        db.table('withdrawals').update({
            'status': 'rejected',
            'reviewed_at': now
        }).eq('id', wd_id).execute()

        flash('Withdrawal rejected.', 'info')

    _log_action(db, action, wd_id, f"{action} withdrawal", now)
    return redirect(url_for('admin.dashboard'))


# ─────────────────────────────────────────────
# BALANCE ADJUST
# ─────────────────────────────────────────────
@admin_bp.route('/adjust-balance', methods=['POST'])
@admin_required
def adjust_balance():
    db = get_admin_supabase()
    now = datetime.now(timezone.utc).isoformat()

    uid = request.form.get('user_id')
    amount = float(request.form.get('amount', 0))
    reason = request.form.get('reason', 'Admin adjustment')

    prof_res = db.table('profiles').select('balance').eq('id', uid).execute()
    prof = (prof_res.data or [{}])[0]
    balance = prof.get('balance', 0)

    new_balance = round(balance + amount, 2)

    db.table('profiles').update({
        'balance': new_balance
    }).eq('id', uid).execute()

    db.table('transactions').insert({
        'user_id': uid,
        'type': 'admin_adjustment',
        'amount': amount,
        'description': reason,
        'status': 'completed',
        'created_at': now
    }).execute()

    _log_action(db, 'adjust_balance', uid, reason, now)

    flash('Balance updated.', 'success')
    return redirect(url_for('admin.dashboard'))


# ─────────────────────────────────────────────
# LOG HELPER
# ─────────────────────────────────────────────
def _log_action(db, action, target_id, details, now):
    db.table('admin_actions').insert({
        'admin_id': 'admin',
        'action': action,
        'target_id': target_id,
        'details': details,
        'created_at': now
    }).execute()
