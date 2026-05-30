"""
Admin blueprint — approve/reject deposits & withdrawals, balance adjustments,
audit log, daily profit monitor.
URL prefix: /admin
"""
from datetime import datetime, timezone
from flask import (Blueprint, render_template, request,
                   redirect, url_for, session, flash)
from utils.supabase_client import get_admin_supabase
from utils.helpers import admin_required

admin_bp = Blueprint('admin', __name__)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route('/')
@admin_required
def dashboard():
    db = get_admin_supabase()

    users       = db.table('profiles').select('*').execute().data or []
    deposits    = db.table('deposits').select('*, profiles(username, email)').order('created_at', desc=True).execute().data or []
    withdrawals = db.table('withdrawals').select('*, profiles(username, email)').order('created_at', desc=True).execute().data or []
    transactions = db.table('transactions').select('*, profiles(username)').order('created_at', desc=True).limit(60).execute().data or []
    investments = db.table('investments').select('*, profiles(username)').order('created_at', desc=True).execute().data or []
    actions     = db.table('admin_actions').select('*').order('created_at', desc=True).limit(50).execute().data or []

    return render_template('admin.html',
        users=users,
        deposits=deposits,
        withdrawals=withdrawals,
        transactions=transactions,
        investments=investments,
        actions=actions,
        total_balance=sum(u.get('balance', 0) for u in users),
        pending_deposits=[d for d in deposits if d['status'] == 'pending'],
        pending_withdrawals=[w for w in withdrawals if w['status'] == 'pending'],
        active_investments=[i for i in investments if i['status'] == 'active'],
    )


# ── Approve / reject deposits ─────────────────────────────────────────────────

@admin_bp.route('/deposit/<deposit_id>/<action>', methods=['POST'])
@admin_required
def handle_deposit(deposit_id, action):
    from routes.investments import pay_referral_commissions

    db  = get_admin_supabase()
    now = datetime.now(timezone.utc).isoformat()

    dep = db.table('deposits').select('*').eq('id', deposit_id).single().execute().data
    if not dep:
        flash('Deposit not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    if action == 'approve':
        uid    = dep['user_id']
        amount = dep['amount']

        prof = db.table('profiles').select('balance').eq('id', uid).single().execute().data
        db.table('profiles').update({'balance': round(prof['balance'] + amount, 2)}).eq('id', uid).execute()
        db.table('deposits').update({'status': 'approved', 'reviewed_at': now}).eq('id', deposit_id).execute()
        db.table('transactions').insert({
            'user_id':     uid,
            'type':        'deposit',
            'amount':      amount,
            'description': f"Deposit approved — ${amount} via {dep.get('network','N/A')}",
            'status':      'completed',
            'created_at':  now,
        }).execute()

        pay_referral_commissions(db, uid, amount, tx_type='deposit')
        flash(f'Deposit of ${amount} approved and credited.', 'success')

    elif action == 'reject':
        db.table('deposits').update({'status': 'rejected', 'reviewed_at': now}).eq('id', deposit_id).execute()
        flash('Deposit rejected.', 'info')

    _log_action(db, f'{action}_deposit', deposit_id,
                f'{action.capitalize()} deposit #{deposit_id[:8]}', now)
    return redirect(url_for('admin.dashboard'))


# ── Approve / reject withdrawals ──────────────────────────────────────────────

@admin_bp.route('/withdrawal/<wd_id>/<action>', methods=['POST'])
@admin_required
def handle_withdrawal(wd_id, action):
    db  = get_admin_supabase()
    now = datetime.now(timezone.utc).isoformat()

    wd = db.table('withdrawals').select('*').eq('id', wd_id).single().execute().data
    if not wd:
        flash('Withdrawal not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    if action == 'approve':
        uid    = wd['user_id']
        amount = wd['amount']

        prof = db.table('profiles').select('balance').eq('id', uid).single().execute().data
        new_bal = round(max(prof['balance'] - amount, 0), 2)
        db.table('profiles').update({'balance': new_bal}).eq('id', uid).execute()
        db.table('withdrawals').update({'status': 'approved', 'reviewed_at': now}).eq('id', wd_id).execute()
        db.table('transactions').insert({
            'user_id':     uid,
            'type':        'withdrawal',
            'amount':      -amount,
            'description': f"Withdrawal approved — ${amount} to {(wd.get('wallet_address') or '')[:20]}",
            'status':      'completed',
            'created_at':  now,
        }).execute()
        flash(f'Withdrawal of ${amount} approved.', 'success')

    elif action == 'reject':
        db.table('withdrawals').update({'status': 'rejected', 'reviewed_at': now}).eq('id', wd_id).execute()
        flash('Withdrawal rejected.', 'info')

    _log_action(db, f'{action}_withdrawal', wd_id,
                f'{action.capitalize()} withdrawal #{wd_id[:8]}', now)
    return redirect(url_for('admin.dashboard'))


# ── Manual balance adjustment ─────────────────────────────────────────────────

@admin_bp.route('/adjust-balance', methods=['POST'])
@admin_required
def adjust_balance():
    db     = get_admin_supabase()
    now    = datetime.now(timezone.utc).isoformat()
    uid    = request.form.get('user_id', '')
    amount = float(request.form.get('amount', 0))
    reason = request.form.get('reason', 'Admin adjustment')

    prof = db.table('profiles').select('balance').eq('id', uid).single().execute().data
    if not prof:
        flash('User not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    new_bal = round(prof['balance'] + amount, 2)
    if new_bal < 0:
        flash('Resulting balance cannot be negative.', 'error')
        return redirect(url_for('admin.dashboard'))

    db.table('profiles').update({'balance': new_bal}).eq('id', uid).execute()
    db.table('transactions').insert({
        'user_id':     uid,
        'type':        'admin_adjustment',
        'amount':      amount,
        'description': f'Admin adjustment: {reason}',
        'status':      'completed',
        'created_at':  now,
    }).execute()
    _log_action(db, 'adjust_balance', uid, f'Adjusted ${amount} — {reason}', now)

    flash(f'Balance adjusted by ${amount}.', 'success')
    return redirect(url_for('admin.dashboard'))


# ── Private helper ────────────────────────────────────────────────────────────

def _log_action(db, action: str, target_id: str, details: str, now: str):
    db.table('admin_actions').insert({
        'admin_id':  'admin',
        'action':    action,
        'target_id': target_id,
        'details':   details,
        'created_at': now,
    }).execute()
